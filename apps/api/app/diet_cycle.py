"""Parent-managed 07:00 diet settlement. No external model calls."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from . import diet_publication

from . import db, diet_tracking, diet_history, diet_day, diet_policy, diet_reference, diet_recent, diet_quantified

VERSION = "diet-cycle-03-v1"


def latest(reports, through, timezone, *, include_previews=True):
    return next((r for r in reports if r.get("timezone") == timezone
                 and r["data"].get("cycle_version") == VERSION
                 and r["data"].get("publication_trigger") != "score_only"
                 and (include_previews or r["data"].get("plan_mode") != "test_preview")
                 and r["data"]["target_date"] <= through.isoformat()), None)


def recommendations():
    settings = db.settings()
    today = diet_day.current_diet_day()
    with db.connect() as con:
        reports = [db.unpack(r) for r in con.execute("SELECT * FROM reports WHERE module='diet' ORDER BY created_at DESC LIMIT 1000")]
    plan = latest(reports, today, settings["timezone"])
    data = plan["data"] if plan else {}
    identifier = plan["id"] if plan else None
    from . import diet
    current_target = diet.active_target()
    daily = current_target.get("daily") or {}
    return {**data, "id": identifier, "status": data.get("status", "pending"),
            "advice": data.get("next_meal", {}).get("additions", []),
            "dimensions": {"goal": {"target_energy": daily.get("kcal"), "target_protein": daily.get("protein_g")}},
            "feedback": [r for r in db.records("feedback")["items"] if identifier and r["data"]["recommendation_ref"] == identifier]}


def settled_days(start, end, reports, meals, target, day_logs=None):
    """Only persisted morning snapshots can expose a score in the UI."""
    current = diet_tracking.review_days(start, end, reports, meals, target, calculate=False, day_logs=day_logs)
    saved = {}
    timezone = db.settings()["timezone"]
    for report in reports:
        if (report.get("timezone") == timezone and report["data"].get("cycle_version") == VERSION
                and report["data"].get("scores_settled", True)
                and report["data"].get("plan_mode") != "test_preview"):
            for day in report["data"]["review_days"]:
                saved.setdefault(day["date"], day)
    result = []
    for day in current:
        snapshot = saved.get(day["date"])
        if snapshot:
            changed = (snapshot.get("input_refs") != day.get("input_refs")
                       or snapshot.get("analysis_refs") != day.get("analysis_refs")
                       or not diet_tracking.diet_scoring.saved_version_supported(snapshot))
            if changed:
                result.append({**day, "pending_changes": True, "score": None,
                               "components": [], "state": "待重算"})
            else:
                result.append({**snapshot, "log": day["log"], "pending_changes": False})
        else:
            result.append({**day, "score": None, "components": [], "state": "待早上结算" if day["meals"] else "未记录"})
    return result


def advice(day, target, preferences, values, target_date, history=None, products=None, references=None, training=None, recent=None):
    """Explain observed differences; budgets are targets, not invented recipe nutrition."""
    foods = day.get("foods", [])
    history = history or diet_history.summarize([], [], target_date, "Asia/Shanghai")
    supplement_habit = str(values.get("补剂习惯", "")).strip()
    supplement_notes = []
    if supplement_habit not in ("", "无", "没有", "未服用"):
        supplement_notes.append(
            f"补剂习惯背景：{supplement_habit} "
            "具体配方及微量营养含量未核对时，不重复建议同类补充；不据此认定当天已服用，"
            "不估算补剂的微量营养或用其替代食物记录，也不自动计入当日摄入。")
    hydration_advice = str(values.get("饮水建议", "")).strip()
    hydration_notes = ([f"每日饮水参考（目标，不是饮水记录）：{hydration_advice} "
                        "按当天实际训练、出汗量与环境温度调整；不据此认定当天已喝够，不自动计入实际摄入。"]
                       if hydration_advice else [])
    summary = f"{day['date']} 已记录{day['meals']}餐、分析{day['analyzed']}餐。"
    if foods:
        summary += "记录食物：" + "、".join(foods[:12]) + "。"
    notes = []
    # Quality components can be unknown or use g/kg and energy-share ranges.
    # They are not the old intake/target percentage components.
    for part in day["components"]:
        if part.get("reason"):
            notes.append(part["reason"])
            if (part["key"] == "fat" and part.get("unit") == "%能量"
                    and isinstance(part.get("intake"), (int, float)) and part["intake"] > 35):
                notes.append("熟悉的饭菜可少油烹调、油酱单独计量，蔬菜照常搭配，主食与蛋白质不因此省掉；不用跳餐抵扣。")
        elif (part.get("key") in diet_tracking.NUTRIENTS
              and isinstance(part.get("intake"), (int, float)) and isinstance(part.get("target"), (int, float))):
            # Preserve previously saved numeric observations without recalculating their score.
            unit = "大卡" if part["key"] == "kcal" else "克"
            if part["intake"] < part["target"] * .9:
                notes.append(f"昨日记录的{part['name']}约{part['intake']:g}{unit}，低于昨日参考{part['target']:g}{unit}；今天按每餐预算安排，未记完的差额不等于实际缺口。")
            elif part["intake"] > part["target"] * 1.1:
                adjustment = ("熟悉的饭菜可少油烹调、油酱单独计量，蔬菜照常搭配，主食与蛋白质不因此省掉。" if part["key"] == "fat_g" else "")
                notes.append(f"昨日记录的{part['name']}约{part['intake']:g}{unit}，高于昨日参考{part['target']:g}{unit}；今天回到正常目标，不用跳餐抵扣。" + adjustment)
    if not day["finished"]:
        notes.append("以下按昨日已记录内容安排，未记录不等于没有吃，不据记录差额断言实际吃多或吃少。")
    if day["score"] is None:
        notes.append("昨日基础营养、当日参考或估算依据不足，可评参考分留空；今天仍按现有个人资料安排，不追补昨日差额。")
    notes.append("优先沿用你实际吃过、明确喜欢的搭配。若当天尚未安排蔬菜、水果、全谷或适合的蛋白质来源，可在熟悉食物上补充；不要求每天换陌生食谱，不据照片判断维生素或Omega-3是否缺乏。")
    constraints = [r["data"]["rule"] for r in preferences if r["data"]["confirmed"] and r["data"]["kind"] in ("allergy", "constraint", "dislike")]
    if str(values.get("忌口", "")).strip() not in ("", "无", "没有", "无忌口"):
        constraints.append(str(values["忌口"]))
    restricted = bool(constraints or values.get("特殊健康情况", "无") not in ("", "无"))
    quantified = (diet_quantified._empty("已有忌口或特殊健康情况，须人工核对食物适用性。") if restricted else
                  diet_quantified.build(target, preferences, history, products, references, (training or {}).get("training_status", "unknown")))
    recent = recent or {}
    why = (recent.get("short_reason") or "近期记录不足，不能据此判定摄入多少。") + " 选菜沿用素材中的西葫芦炒蛋鸡胸饭、三文鱼叶菜汤锅和已吃过的牛肉三明治样式，优先明确偏好；按当前参考目标分配份量，不追补前日欠账。"
    if quantified.get("starter_seed_id"):
        why = (recent.get("short_reason") or "近期记录不足。") + " 使用本人明确选入的入门菜式及通用补充搭配，份量按本人资料计算；不表示吃过或喜欢，不追补漏记差额。"
    if not quantified.get("valid_for_use"):
        why = (recent.get("short_reason") or "近期记录不足，不能据此判定摄入多少。") + " 当前候选还不足以核算完整全天份量，保留真实记录与已确认偏好，等待核对，不把预算当食物营养。"
    if values.get("水果摄入习惯") and quantified.get("valid_for_use"):
        why += " 你说目前水果吃得较少，方案加入香蕉和苹果共270g可食部，计入能量和碳水。"
    quantified.update(reference_date=target_date, training_plan=training or {}, reason_summary=why,
                      recent_three_days=recent, policy=diet_policy.get_policy(),
                      dynamic_adjustment={"status": "insufficient_data", "applied": False,
                          "baseline_unchanged": True, "missing": ["连续可比的体重趋势", "完整饮食记录", "实际训练与恢复反馈"],
                          "explanation": "现有数据不能支持自动改变基线或把昨日差额移到今日；仍用现有起始参考。"})
    pattern_notes = (["已记录忌口或特殊健康情况，食物结构提示暂不指定替换食材；先确认适用食物，再结合实际记录安排。"]
                     if restricted else diet_history.pattern_additions(history, preferences))
    return {**quantified, "title": "全天参考饮食方案" if quantified.get("valid_for_use") else "方案待核算", "today_summary": summary, "foods": [],
            "reason": why, "additions": [recent.get("short_reason", "")] + recent.get("structure_notes", []) + notes + [history["notice"]] + pattern_notes + supplement_notes + hydration_notes,
            "hydration_advice": hydration_advice or None,
            "caveat": "建议份量按指定标签或官方成分代表值核算，不是已吃记录；完整菜单不能叠加到当天已经吃过的食物上。目标为现有起始参考，未临床核定。",
            "constraints": constraints, "food_history": history, "diet_patterns": history.get("diet_patterns", {})}



def build(target_date, timezone, *, force=False, plan_mode="test_preview", generate_menu=True, settle_scores=False):
    from . import diet
    today = date.fromisoformat(target_date)
    yesterday = today - timedelta(days=1)
    if settle_scores:
        if not generate_menu or plan_mode != "formal":
            raise ValueError("每日评分仅由北京时间07:00正式流程结算上一完整饮食日")
        diet_publication.require_formal_window(target_date)
    with db.connect() as con:
        reports = [db.unpack(r) for r in con.execute("SELECT * FROM reports WHERE module='diet' ORDER BY created_at DESC LIMIT 1000")]
    if plan_mode == "formal" and generate_menu:
        diet_publication.require_formal_window(target_date)
    existing = diet_publication.successful_formal(reports, target_date) if plan_mode == "formal" else None
    if existing and generate_menu:
        return existing["data"]  # Retries/manual duplicate jobs cannot rewrite the day's plan.
    if plan_mode == "formal" and generate_menu:
        from . import diet_target_review
        diet_target_review.require_review()
    target = diet.calorie_target(target_date=target_date)
    values, _, _ = diet_tracking.health_state()
    meals = db.records("meals", 10000)["items"]
    preferences = db.records("diet_preferences", 1000)["items"]
    # Read historical snapshots without recalculating. A morning run settles
    # exactly the just-closed diet day; previews never invoke the score engine.
    days = settled_days(yesterday - timedelta(days=6), yesterday, reports, meals, target)
    if settle_scores:
        previous = diet_tracking.review_days(yesterday, yesterday, reports, meals, target,
                                             calculate=True, timezone=timezone)[0]
        from .diet_score_estimate import apply_daily_policy
        apply_daily_policy(previous)
        previous["settled_at"] = db.now()
        previous["state"] = "已结算" if previous["score"] is not None else previous["state"]
        days[-1] = previous
    previous = days[-1]
    zone = ZoneInfo(timezone)
    previous["foods"] = list(dict.fromkeys(food["name"] for meal in meals
        if diet_day.meal_diet_date(meal) == yesterday
        and meal["data"]["execution"] not in ("planned", "skipped", "replaced")
        for food in (diet.current_analysis(meal, reports) or {}).get("data", {}).get("foods", []) if food["certainty"] == "clear"))
    history = diet_history.summarize(meals, reports, target_date, timezone)
    references = diet_reference.collect(meals, reports)
    products = db.records("food_products", 1000)["items"]
    training = diet_day.training_plan_for_date(target_date)
    recent = diet_recent.summarize_three_days(target_date, reports, meals, target)
    plan = (advice(previous, target, preferences, values, target_date, history, products, references, training, recent)
            if generate_menu else {"valid_for_use": False, "recipes": [], "today_summary": "仅整理评分与上下文，未生成菜单。"})
    requests = diet_day.dish_requests_for_date(target_date)
    from . import diet_pantry
    pantry = diet_pantry.for_date(target_date)
    plan["pantry_constraints"] = pantry
    plan["applied_pantry_constraint_refs"] = pantry["constraint_refs"]
    plan["dish_requests"] = requests
    plan["fulfilled_dish_requests"] = []
    if requests["items"]:
        plan.update(valid_for_use=False, quantification_status="needs_review", recipes=[], variants=[], active_variant_id=None, daily_nutrition=None,
                    quantification_note="目标日已有明确点菜，须由主聊天按请求提供结构化新菜式，经过来源和份量校验后发布；不静默替换成旧模板。")
        plan["reason_summary"] = "目标日想吃：" + "、".join(r["dish"] for r in requests["items"]) + "。已保留请求与来源，当前等待按点菜核算全天搭配。"
    if plan.get("valid_for_use"):
        from .diet_planning import validate_menu
        try:
            from . import diet_rotation
            rotation = diet_rotation.context(target_date, meals, reports)
            assessment = diet_rotation.evaluate(plan, rotation)
            if assessment['overlaps']:
                raise ValueError("近期主食材或菜式重复，需优先轮换或明确复核理由")
            plan['rotation_review'] = diet_rotation.review(plan, rotation, [],
                '已检查前三个饮食日实际餐食及既有建议，当前主菜未检出重复。', 'software:no_overlap_check')
            plan['rotation_validation'] = diet_rotation.validate(plan, rotation)
            plan["numeric_validation"] = validate_menu(plan, target["daily"], pantry)
        except (ValueError, KeyError):
            plan.update(valid_for_use=False, quantification_status="needs_review", recipes=[], variants=[], active_variant_id=None, daily_nutrition=None,
                        quantification_note="当前菜式未通过近期重复、来源、数值或目标日库存校验，需按最新上下文优先轮换并重新核算；暂不发布可执行菜单。")
    if generate_menu:
        diet_publication.label_menu(plan, plan_mode)
    refs = {r["id"]: r for day in days for r in day["input_refs"]}
    refs.update({r["id"]: r for r in history["input_refs"]})
    refs.update({r["id"]: r for r in target["input_refs"]})
    refs.update({r["id"]: r for r in training.get("input_refs", [])})
    refs.update({r["id"]: r for r in pantry.get("input_refs", [])})
    refs.update({r["id"]: {"id": r["id"], "version": r["version"]} for r in products})
    refs.update({r["id"]: {"id": r["id"], "version": r["version"]} for r in preferences})
    return {"cycle_version": VERSION, "score_version": diet_tracking.SCORE_VERSION, "title": "每日饮食结算", "target_date": target_date,
            "plan_mode": plan_mode if generate_menu else None, "scores_settled": settle_scores, "generated_at": db.now(),
            "publication_trigger": "morning_0700" if plan_mode == "formal" and generate_menu else "explicit_test_request" if generate_menu else "score_only",
            "review_date": yesterday.isoformat(), "review_days": days, "previous_day": previous,
            "reference_targets": target, "next_meal": plan, "policy": diet_policy.get_policy(), "recent_three_days": recent, "input_refs": list(refs.values()),
            "summary": plan["today_summary"], "status": "succeeded" if previous["score"] is not None and target.get("daily") else "partial",
            "sources": [*diet.GUIDANCE, *history.get("diet_patterns", {}).get("guidance", []), {"title": "NIDDK：饮食、活动和体重记录", "url": "https://www.niddk.nih.gov/health-information/weight-management/adult-overweight-obesity/eating-physical-activity"}]}
