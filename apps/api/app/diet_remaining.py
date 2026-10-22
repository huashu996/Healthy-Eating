"""Conservative data-only adjustments to the *remaining* part of a diet day.

Contract: ``plan`` contains ``reference_targets.daily`` and quantified ``recipes``
(also accepted under ``next_meal``). ``intake_snapshot`` is either overview's
``today`` object (date, meals_count, totals with coverage), or a dict with
``entries`` containing explicit done/partial execution and nutrition ranges.
Entry nutrition describes the whole photographed serving; eaten_fraction is
applied once. Aggregate totals are already fraction-adjusted. A caller may add
snapshot_scope="recorded_actual"; any other declared scope is rejected.

skipped_meals and remaining_meals are explicit planning inputs, never persisted
meal facts. Pass an aware ``now`` to assess Beijing time; omitted now is not read
from the clock. Only versioned software policy is read; no database or network
access occurs and nothing is written.
The caller selects a concrete full-day variant and persists a new plan version.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from itertools import product
from math import isfinite
import hashlib
import json
from collections.abc import Mapping
from zoneinfo import ZoneInfo

from . import diet_policy

VERSION = "remaining-portioned-plan-v1"
KEYS = ("kcal", "protein_g", "fat_g", "carbs_g")
ZONE = ZoneInfo("Asia/Shanghai")
ALIASES = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐",
           "pre_workout": "练前餐", "preworkout": "练前餐", "加餐 / 练前餐": "加餐",
           "下午餐": "下午咖啡 / 水果", "post_workout": "练后", "训练后": "练后", "afternoon": "下午咖啡 / 水果"}
MEALS = {"早餐", "午餐", "晚餐", "加餐", "练前餐", "练后", "下午咖啡 / 水果"}
LIMITS = {"早餐": (250, 750), "午餐": (350, 950), "晚餐": (350, 950),
          "加餐": (80, 350), "练前餐": (80, 350), "练后": (50, 350), "下午咖啡 / 水果": (50, 750)}
NOTICE = "仅调整尚未吃的建议；已吃记录、份量和原方案均保持不变。未记录不等于没吃，不为补齐数字安排巨大补餐或跳餐抵消。"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _range(value):
    return (isinstance(value, Mapping) and all(_number(value.get(s)) for s in ("low", "high"))
            and 0 <= value["low"] <= value["high"])


def _meal(value):
    return ALIASES.get(value, value) if isinstance(value, str) else None


def _names(values):
    if isinstance(values, str) or not isinstance(values, (list, tuple, set)):
        raise ValueError("餐次须为列表")
    result = list(dict.fromkeys(_meal(v) for v in values))
    if any(v not in MEALS for v in result):
        raise ValueError("餐次名称无效")
    return result


def _data(value):
    return value.get("data", value) if isinstance(value, Mapping) else {}


def intake_snapshot_fingerprint(snapshot):
    """Compare the same snapshot shape before reusing a stored proposal."""
    encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _intake(snapshot, day):
    """Accept actual-only aggregates or independently filter explicit entries."""
    issues, refs, eaten_meals = [], [], []
    totals = {k: {"low": 0.0, "high": 0.0} for k in KEYS}
    coverage = {k: 0 for k in KEYS}
    if snapshot.get("snapshot_scope", "recorded_actual") != "recorded_actual":
        return {k: None for k in KEYS}, [], [], ["摄入快照不是实际已吃范围，不能把计划或参考图当作已吃。"], None
    if day and snapshot.get("date") and snapshot["date"] != day:
        issues.append("摄入快照与目标方案不是同一饮食日。")
    if "entries" not in snapshot:
        count, values = snapshot.get("meals_count", snapshot.get("meals")), snapshot.get("totals", {})
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return {k: None for k in KEYS}, [], [], issues + ["摄入快照缺少实际已吃餐数，不能默认已吃为零。"], None
        for key in KEYS:
            value = values.get(key) if isinstance(values, Mapping) else None
            coverage[key] = value.get("coverage") if isinstance(value, Mapping) else 0
            if count == 0 and value is None:
                continue
            if not _range(value) or not _number(value.get("coverage")) or value["coverage"] < count:
                totals[key] = None
                issues.append(f"已吃记录的{key}范围或分析覆盖不完整。")
            elif count == 0 and (value["low"] or value["high"]):
                totals[key] = None
                issues.append("零餐快照含非零营养量，需先核对。")
            else:
                totals[key] = {side: float(value[side]) for side in ("low", "high")}
        return totals, deepcopy(snapshot.get("input_refs", [])), eaten_meals, issues, {"meals_count": count, "nutrient_coverage": coverage}
    entries = snapshot["entries"]
    if not isinstance(entries, list):
        return {k: None for k in KEYS}, [], [], issues + ["已吃记录列表格式无效。"], None
    seen_ids = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            issues.append("已吃记录格式无效。")
            continue
        wrapper = entry.get("meal", entry)
        meal = _data(wrapper)
        scope = entry.get("snapshot_scope", meal.get("snapshot_scope"))
        if (entry.get("deleted_at") or wrapper.get("deleted_at") or meal.get("deleted_at")
                or meal.get("execution") in ("planned", "skipped", "replaced", "reference")
                or entry.get("is_reference") or meal.get("is_reference")
                or entry.get("reference_only") or meal.get("reference_only")
                or entry.get("eligible_for_meal_totals") is False or meal.get("eligible_for_meal_totals") is False
                or entry.get("kind", meal.get("kind")) in ("history_reference", "actual_meal_reference")
                or entry.get("is_plan") or meal.get("is_plan")
                or entry.get("source_kind", meal.get("source_kind")) in ("reference_image", "reference")
                or entry.get("plan_scope", meal.get("plan_scope")) in ("full_day_reference", "remaining_today")
                or scope in ("reference", "full_day_reference", "remaining_today", "planned")):
            continue
        if meal.get("execution") not in ("done", "partial"):
            issues.append("记录没有明确已吃状态，未按已吃计入。")
            continue
        if wrapper.get("id") in seen_ids:
            issues.append("摄入快照重复包含同一餐，需先保留其当前版本。")
            continue
        if wrapper.get("id"):
            seen_ids.add(wrapper["id"])
        if day and meal.get("diet_date") and meal["diet_date"] != day:
            issues.append("已吃记录包含其他饮食日，需核对快照。")
            continue
        fraction = meal.get("eaten_fraction", 1)
        if not _number(fraction) or not 0 <= fraction <= 1:
            issues.append("已吃份量比例无效。")
            continue
        eaten_meals.append(_meal(meal.get("meal_type")))
        if wrapper.get("id"):
            refs.append({k: wrapper[k] for k in ("id", "version") if k in wrapper})
        nutrition = _data(entry.get("analysis", {})).get("nutrition", meal.get("nutrition", {}))
        for key in KEYS:
            value = nutrition.get(key) if isinstance(nutrition, Mapping) else None
            if not _range(value):
                totals[key] = None
                issues.append(f"已吃记录的{key}未知；包括类型或份量不明的咖啡，不作补猜。")
            else:
                coverage[key] += 1
                if totals[key] is not None:
                    for side in ("low", "high"):
                        totals[key][side] += value[side] * fraction
    return totals, refs, eaten_meals, issues, {"meals_count": len(eaten_meals), "nutrient_coverage": coverage}


def _item_limit(item):
    """Operational bounds for this template, not medical portion prescriptions."""
    values, name = item["per_100g"], item["name"].lower()
    if _is_protein_powder(item):
        return 50
    if values["fat_g"] >= 80:
        return 20
    if values["protein_g"] >= 15:
        return 300
    if any(word in name for word in ("milk", "牛奶", "酸奶", "yogurt")):
        return 350
    if any(word in name for word in ("banana", "apple", "香蕉", "苹果", "水果")):
        return 250
    if values["kcal"] < 70:
        return 400
    if values["carbs_g"] >= 20:
        return 400 if values["kcal"] <= 180 else 180
    return 300


def _is_protein_powder(item):
    return any(s in str(item.get("name", "")).lower() for s in ("蛋白粉", "乳清", "whey", "protein powder"))


def _valid_item(item, allow_labeled_protein=False):
    if not isinstance(item, Mapping):
        return False
    values, quantity = item.get("per_100g"), item.get("quantity")
    name = str(item.get("name", "")).lower()
    if any(s in name for s in ("增肌粉", "肌酸", "creatine")):
        return False
    if _is_protein_powder(item) and not (allow_labeled_protein and isinstance(item.get("source"), Mapping)
                                       and item["source"].get("kind") == "personal_label"):
        return False
    if ("咖啡" in name or "coffee" in name) and not any(s in name for s in ("拿铁", "黑咖啡", "美式", "latte", "black", "espresso", "americano")):
        return False
    return (bool(name) and item.get("unit") == "g" and _number(quantity) and quantity > 0
            and bool(item.get("weight_basis")) and bool(item.get("source"))
            and isinstance(values, Mapping)
            and all(_number(values.get(k)) and 0 <= values[k] <= (1000 if k == "kcal" else 100) for k in KEYS))


def _total(items):
    return {k: round(sum(i["per_100g"][k] * i["quantity"] / 100 for i in items), 4) for k in KEYS}


def _options(recipe, slot, late, max_scale, allow_labeled_protein=False):
    items = recipe.get("items", [])
    if not items or not all(_valid_item(i, allow_labeled_protein) for i in items):
        return []
    lower, upper = LIMITS[slot]
    if late:
        upper = min(upper, 450 if late == "overnight" else 650)
    choices, seen = [], set()
    # A selected, label-backed post-training serving is retained, never enlarged
    # to fill a protein/calorie difference. Other ingredients have bounded scaling.
    has_powder = any(_is_protein_powder(i) for i in items)
    # A bounded grid remains practical even if a later policy raises the ratio;
    # independent food gram and meal-energy limits still apply to every option.
    scales = sorted({.5, 1.0, max_scale, *[round(.5 + (max_scale - .5) * step / 10, 6) for step in range(11)]})
    for scale in ([1.0] if has_powder else scales):
        rows = []
        for original in items:
            step = 1 if original["per_100g"]["fat_g"] >= 80 else 5
            quantity = original["quantity"] if _is_protein_powder(original) else round(original["quantity"] * scale / step) * step
            if (quantity <= 0 or quantity < original["quantity"] * .5 - 1e-7
                    or quantity > min(original["quantity"] * max_scale, _item_limit(original)) + 1e-7):
                break
            row = deepcopy(original)
            row["quantity"] = quantity
            row["nutrition"] = {k: round(row["per_100g"][k] * quantity / 100, 4) for k in KEYS}
            rows.append(row)
        if len(rows) != len(items):
            continue
        signature = tuple(row["quantity"] for row in rows)
        nutrients = _total(rows)
        if signature in seen or not lower <= nutrients["kcal"] <= upper:
            continue
        seen.add(signature)
        choices.append({"items": rows, "nutrition": nutrients, "scale": scale})
    return choices


def proposed_remaining(plan, intake_snapshot, *, skipped_meals, remaining_meals,
                       training_status="unknown", now=None):
    """Return a new proposal only; valid_for_use=False must not become a ready plan.

    All discrepancy fields remain explicit when only a partial, bounded proposal
    is possible. No candidate budget/nutrition total is accepted as food actuals.
    An exceeded target returns review advice, never an instruction to skip food.
    """
    if not isinstance(plan, Mapping) or not isinstance(intake_snapshot, Mapping):
        raise ValueError("方案和摄入快照须为对象")
    data = _data(plan)
    menu = data.get("next_meal") or data
    issues = []
    result = {"adjustment_version": VERSION, "quantification_version": VERSION,
              "plan_scope": "remaining_today", "quantification_status": "needs_review", "valid_for_use": False,
              "recipes": [], "remaining_target_ranges": {k: None for k in KEYS},
              "remaining_reference_midpoints": {k: None for k in KEYS}, "target_comparison": None,
              "remaining_nutrition": {k: 0.0 for k in KEYS}, "scope_notice": NOTICE,
              "original_intake_snapshot": deepcopy(intake_snapshot),
              "source_plan_ref": {k: plan[k] for k in ("id", "version") if k in plan},
              "training_status": training_status, "planning_assumptions": {}, "reason": "", "limitations": []}
    try:
        policy = diet_policy.get_policy()
    except (OSError, ValueError, KeyError, TypeError):
        result["reason"] = "量化规则配置无法通过核验，暂不生成剩余方案。"
        return result
    controls = policy["quantification"]
    max_scale = controls["max_portion_scale"]
    result["policy"] = policy
    try:
        result["intake_snapshot_sha256"] = intake_snapshot_fingerprint(intake_snapshot)
    except (TypeError, ValueError):
        result["reason"] = "摄入快照含无法保存或非有限的值，需先复核。"
        return result
    try:
        skipped, remaining = _names(skipped_meals), _names(remaining_meals)
    except ValueError as error:
        result["reason"] = str(error)
        return result
    result["planning_assumptions"] = {"skipped_meals": skipped, "remaining_meals": remaining,
                                      "skipped_is_intake_fact": False, "time_assessed": now is not None}
    if training_status not in ("unknown", "training", "rest"):
        issues.append("训练状态无效，不能据此生成建议。")
    if set(skipped) & set(remaining):
        issues.append("同一餐次同时标为跳过和剩余，需先核对。")
    if menu.get("valid_for_use") is False or menu.get("quantification_status") == "needs_review":
        issues.append("原候选菜单尚未通过核验，不能发布其剩余调整。")
    target = (data.get("reference_targets") or {}).get("daily") or data.get("daily_target") or (menu.get("target_comparison") or {}).get("targets") or {}
    if any(not _number(target.get(k)) or target[k] <= 0 for k in KEYS):
        result["reason"] = "当前每日参考目标不完整，不能用旧食谱预算替代。"
        return result
    # This adult reference-template boundary is a review guard, not a prescription.
    if not 1600 <= target["kcal"] <= 3600:
        issues.append("每日参考量超出当前模板的1600–3600千卡校验范围，需人工复核。")
    day = data.get("target_date", intake_snapshot.get("date"))
    actual, refs, eaten_meals, intake_issues, coverage = _intake(intake_snapshot, day)
    issues.extend(intake_issues)
    result.update({"target_date": day, "actual_intake_ranges": deepcopy(actual), "actual_input_refs": refs})
    result["intake_basis"] = {"scope": "recorded_actual", "date": intake_snapshot.get("date", day),
                              "as_of": None, **(coverage or {"meals_count": None, "nutrient_coverage": dict.fromkeys(KEYS)}),
                              "notice": "基于这个时点已记录的实际摄入；漏记不算零，也不证明已记完。新增、修正或删除已吃记录后须重新计算。"}
    if set(skipped) & set(eaten_meals):
        issues.append("跳过餐次与现有已吃记录冲突；不能删除或覆盖已吃事实。")
    for key in KEYS:
        if actual[key] is not None:
            result["remaining_target_ranges"][key] = {"low": round(target[key] - actual[key]["high"], 4),
                                                       "high": round(target[key] - actual[key]["low"], 4)}
            result["remaining_reference_midpoints"][key] = round(target[key] - (actual[key]["low"] + actual[key]["high"]) / 2, 4)
    result["remaining_allowance_ranges"] = {k: {s: max(0, value[s]) for s in ("low", "high")} if value else None
                                            for k, value in result["remaining_target_ranges"].items()}
    late = None
    if now is not None:
        try:
            stamp = datetime.fromisoformat(now) if isinstance(now, str) else now
            if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("时间必须含时区")
            local = stamp.astimezone(ZONE)
            result["planning_assumptions"]["as_of"] = local.isoformat()
            result["intake_basis"]["as_of"] = local.isoformat()
            if day and day != (local - timedelta(hours=7)).date().isoformat():
                issues.append("当前时间与方案的北京07:00饮食日不一致。")
            late = "overnight" if local.hour < 7 else "late_evening" if local.hour >= 22 else None
        except (TypeError, ValueError):
            issues.append("当前时间无效；请传入含时区时间。")
    else:
        result["limitations"].append("未提供当前时间，仅按明确剩余餐次安排；使用前还需核对进餐时间。")
    if issues:
        result["reason"] = " ".join(dict.fromkeys(issues))
        return result
    midpoint = result["remaining_reference_midpoints"]
    tolerances = {"kcal": max(controls["min_energy_tolerance_kcal"], target["kcal"] * controls["energy_tolerance_ratio"]),
                  "protein_g": controls["protein_tolerance_g"], "fat_g": controls["fat_tolerance_g"],
                  "carbs_g": controls["carbs_tolerance_g"]}
    choices, selected = [], []
    if midpoint["kcal"] <= 0:
        issues.append("已记录热量中点已达或超过参考，不机械追加补餐；这不代表需要跳餐或挨饿，请结合饥饿与正常作息复核。")
    elif not remaining:
        issues.append("没有明确的剩余餐次，未把数字差额变成补餐任务。")
    elif len(remaining) > 6:
        issues.append("剩余餐次数超出当前模板范围，需复核。")
    else:
        candidates = menu.get("recipes", [])
        for slot in remaining:
            if slot in skipped:
                continue
            if slot in ("练前餐", "练后") and training_status != "training":
                issues.append("训练未确认或为休息日，不安排练前餐或练后补充。")
                continue
            recipe = next((r for r in candidates if _meal(r.get("meal_type")) == slot
                           and (r.get("contributes_to_daily_total") is True or slot in ("加餐", "练前餐"))), None)
            options = _options(recipe, slot, late, max_scale, allow_labeled_protein=slot == "练后" and training_status == "training") if recipe else []
            if not options:
                issues.append(f"{slot}缺少可验证且份量合理的量化食物候选，不用预算、未核对的补剂或类型不明咖啡补齐。")
                continue
            choices.append(options)
            selected.append((slot, recipe))
    total_cap = 500 if late == "overnight" else 900 if late else float("inf")
    best, best_score = None, float("inf")
    if choices:
        for combination in product(*choices):
            summed = {k: sum(c["nutrition"][k] for c in combination) for k in KEYS}
            if summed["kcal"] > total_cap:
                continue
            # Leave a visible gap rather than wildly overshooting a small allowance.
            if summed["kcal"] > midpoint["kcal"] + tolerances["kcal"]:
                continue
            score = sum(((summed[k] - midpoint[k]) / tolerances[k]) ** 2 for k in KEYS)
            score += .05 * sum(abs(c["scale"] - 1) for c in combination)
            if score < best_score:
                best, best_score = combination, score
    if best:
        for (slot, recipe), choice in zip(selected, best):
            rows = choice["items"]
            portions = [f"{r['name']}{r['quantity']:g}g（{r['weight_basis']}）" for r in rows]
            title = recipe.get("dish_title") or " + ".join(r["name"] for r in rows)
            if slot == "加餐":
                title = title.replace("练前餐", "加餐")
            preparation = ("按所列生熟重量称量；新增油酱另计。这是尚未吃的建议，不移动或撤销已吃记录。"
                           if recipe.get("optional") or recipe.get("redistribution_from") else
                           recipe.get("preparation", "按所列生熟重量称量；新增油酱另计。"))
            result["recipes"].append({"meal_type": slot, "dish_title": title,
                                      "items": rows, "foods": portions, "portion_summary": "；".join(portions),
                                      "nutrition": choice["nutrition"], "contributes_to_daily_total": True,
                                      "optional": False, "selection_basis": "sourced_remaining_portions",
                                      "preparation": preparation,
                                      "reference_sources": deepcopy(recipe.get("reference_sources", [])),
                                      "unquantified_items": deepcopy(recipe.get("unquantified_items", [])),
                                      "nutrition_scope": "quantified_items_only",
                                      "source_meal_type": recipe.get("meal_type"), "portion_scale": choice["scale"]})
            if recipe.get("unquantified_items"):
                issues.append(f"{slot}仍有未核算内容，数值只含明确称重的食品；未知咖啡奶糖不能当作零。")
    elif choices:
        issues.append("剩余时间或热量不足以容纳合理份量，暂不自动生成补餐；不要靠巨大份量或跳餐抵消差额。")
    remaining_total = _total([i for r in result["recipes"] for i in r["items"]])
    projected = {k: {s: round(actual[k][s] + remaining_total[k], 4) for s in ("low", "high")} for k in KEYS}
    projected_midpoints = {k: round((projected[k]["low"] + projected[k]["high"]) / 2, 4) for k in KEYS}
    difference = {k: round(projected_midpoints[k] - target[k], 4) for k in KEYS}
    within = all(abs(difference[k]) <= tolerances[k] for k in KEYS)
    result["remaining_nutrition"], result["projected_daily_ranges"] = remaining_total, projected
    result["target_comparison"] = {"targets": deepcopy(target), "remaining_reference_midpoints": deepcopy(midpoint),
                                    "proposed_remaining": remaining_total, "projected_daily_midpoints": projected_midpoints,
                                    "difference": difference, "tolerances": tolerances, "within_tolerance": within,
                                    "unfilled_midpoints": {k: max(0, -difference[k]) for k in KEYS},
                                    "excess_midpoints": {k: max(0, difference[k]) for k in KEYS},
                                    "after_proposal_target_ranges": {k: {"low": round(target[k] - projected[k]["high"], 4),
                                                                        "high": round(target[k] - projected[k]["low"], 4)} for k in KEYS},
                                    "note": "范围保留原摄入不确定性；中点只用于规划，不把中点改写为实际摄入。容差为本模板校验。"}
    if not within:
        issues.append("在当前食物、剩余餐次及份量上限内无法完整贴合目标；差额已列出，不强行凑满。")
    if late:
        result["limitations"].append("已按北京深夜时段收紧每餐与合计能量上限；仍需按真实作息、饥饿和舒适度复核。")
    if training_status == "unknown":
        result["limitations"].append("今天训练未知，不增加练前餐或蛋白粉，也不推定运动消耗。")
    elif training_status == "rest":
        result["limitations"].append("休息日不安排练前餐，不额外添加补剂。")
    result["portion_constraints"] = {"minimum_original_multiplier": .5, "maximum_original_multiplier": max_scale,
                                      "meal_kcal_ranges": deepcopy(LIMITS), "late_time_total_kcal_cap": total_cap if late else None,
                                      "note": "模板操作边界，并非个人医学份量上限；不满足时转人工复核。"}
    if not issues and result["recipes"]:
        result["valid_for_use"] = True
        result["quantification_status"] = "verified_estimate"
        result["reason"] = "按当前参考减去已记录实际摄入范围，以范围中点规划剩余餐次；食物营养由每100g来源和明确克数重新求和。"
    else:
        result["reason"] = " ".join(dict.fromkeys(issues)) or "暂无可执行的剩余方案，请复核。"
    result["quantification_note"] = result["reason"]
    return result
