"""Local diet scores and longitudinal body check-ins; never sends private data."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, diet_energy, diet_day, diet_scoring

NUTRIENTS = {"kcal": "热量", "protein_g": "蛋白质", "fat_g": "脂肪", "carbs_g": "碳水"}
SCORE_VERSION = diet_scoring.VERSION
SCORE_METHOD = diet_scoring.METHOD


def fact_observed_date(row, through=None):
    """Upload/edit time is not evidence of when a body measurement was taken."""
    try:
        observed = date.fromisoformat(row["data"].get("observed_at") or "")
    except (TypeError, ValueError):
        return ""
    return observed.isoformat() if through is None or observed <= through else ""


def health_state():
    values, sources, dates = {}, {}, {}
    today = datetime.now(ZoneInfo(db.settings()["timezone"])).date()
    facts = sorted(db.records("facts", 1000)["items"],
                   key=lambda row: (fact_observed_date(row, today), row["updated_at"]), reverse=True)
    for row in facts:
        data = row["data"]
        if data["category"] == "health" and data["key"] not in values:
            key = data["key"]
            values[key], sources[key] = data["value"], row
            dates[key] = (fact_observed_date(row, today), row["updated_at"])
    checkins = sorted(db.records("body_checkins", 1000)["items"], key=lambda r: (r["data"]["measured_on"], r["updated_at"]), reverse=True)
    for key, field in (("体重", "weight_kg"), ("体脂率", "body_fat_pct")):
        row = next((r for r in checkins if r["data"].get(field) is not None), None)
        if row and (row["data"]["measured_on"], row["updated_at"]) > dates.get(key, ("", "")):
            values[key], sources[key] = row["data"][field], row
    return values, sources, checkins


def day_score(totals, target, meals, analyzed, finished, *, context=None, quality=None):
    return diet_scoring.score(totals, target, meals, analyzed, finished, context=context, quality=quality)


def review_days(start, end, reports, meals, current_target, calculate=True, timezone=None, day_logs=None):
    # A past day's target comes from its saved analysis, never today's new body weight.
    from .diet import current_analysis
    zone = ZoneInfo(timezone or db.settings()["timezone"])
    today = diet_day.current_diet_day()
    logs = {}
    for row in (day_logs if day_logs is not None else db.records("diet_days", 1000)["items"]):
        logs.setdefault(row["data"]["date"], row)
    days = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        rows = [m for m in meals if diet_day.meal_diet_date(m) == day and m["data"]["execution"] not in ("planned", "skipped", "replaced")]
        totals = {key: None for key in NUTRIENTS}
        planned = next((r["data"]["reference_targets"] for r in reports
                        if r.get("timezone") == str(zone) and r["data"].get("cycle_version")
                        and r["data"].get("plan_mode") != "test_preview"
                        and r["data"].get("publication_trigger") != "score_only"
                        and r["data"].get("target_date") == day.isoformat()), None)
        saved_reference = current_target if day == today and current_target.get("target_override") else planned if planned else current_target if day == today else None
        from . import diet_targets
        explicit = diet_targets.selected(day)
        if explicit:
            saved_reference = diet_targets.apply({}, explicit)
        analyzed, reference = 0, saved_reference.get("daily") if saved_reference else None
        analysis_refs, quality_entries = [], []
        for meal in rows:
            report = current_analysis(meal, reports)
            if not report:
                continue
            analyzed += 1
            analysis_refs.append({"id": report["id"], "version": report["version"]})
            quality_entries.append((report["data"], meal["data"].get("eaten_fraction", 1)))
            if day != today and reference is None:
                saved = report["data"].get("reference_targets", {})
                reference = saved.get("daily") if saved.get("version") == diet_energy.VERSION else None
                saved_reference = saved if reference is not None else None
            for key in NUTRIENTS:
                value = report["data"].get("nutrition", {}).get(key)
                if value:
                    total = totals[key] or {"low": 0, "high": 0, "coverage": 0}
                    for side in ("low", "high"):
                        total[side] += value[side] * meal["data"].get("eaten_fraction", 1)
                    total["coverage"] += 1
                    totals[key] = total
        log = logs.get(day.isoformat())
        # An explicit end-of-day marker is invalidated by later edits/uploads.
        finished = bool(log and log["data"]["finished"] and all(m["updated_at"] <= log["updated_at"] for m in rows))
        days.append({"date": day.isoformat(), "meals": len(rows), "analyzed": analyzed, "totals": totals, "target": reference,
                     "log": log, "exercise": log["data"]["exercise"] if log else "", "finished": finished,
                     "input_refs": sorted([{"id": r["id"], "version": r["version"]} for r in [*rows, *([log] if log else [])]], key=lambda r: r["id"]),
                     "analysis_refs": sorted(analysis_refs, key=lambda r: r["id"]),
                     **(day_score(totals, reference, len(rows), analyzed, finished,
                                  context=(saved_reference or {}).get("scoring_context"),
                                  quality=diet_scoring.aggregate_quality(quality_entries)) if calculate else
                        {"score": None, "state": "待早上结算", "components": [], "score_version": SCORE_VERSION})})
    return days


def body_progress(target, reports, meals):
    values, sources, checkins = health_state()
    latest = checkins[0] if checkins else None
    if not latest:
        return {"checkins": [], "current": {"weight_kg": values.get("体重"), "body_fat_pct": values.get("体脂率")}, "review": None}
    current = latest["data"]
    end = date.fromisoformat(current["measured_on"])
    previous = next((r for r in checkins[1:] if r["data"]["measured_on"] < current["measured_on"]), None)
    baseline = previous["data"] if previous else None
    if not baseline:
        candidates = [r for r in db.records("facts", 1000)["items"] if r["data"].get("key") == "体重" and r["data"].get("category") == "health" and r["data"].get("value") != "" and fact_observed_date(r) and fact_observed_date(r) < current["measured_on"]]
        fact = max(candidates, key=lambda r: (fact_observed_date(r), r["updated_at"]), default=None)
        if fact:
            baseline = {"measured_on": fact_observed_date(fact), "weight_kg": float(fact["data"]["value"])}
    start = max(end - timedelta(days=14), date.fromisoformat(baseline["measured_on"])) if baseline else end - timedelta(days=6)
    from . import diet_cycle
    days = diet_cycle.settled_days(start, end, reports, meals, target)
    complete = [d for d in days if d["finished"] and d["score"] is not None and not d.get("pending_changes")]
    suggestions = []
    if len(complete) >= 3:
        for key, food in (("protein_g", "在后续餐次补充你喜欢的蛋白质食物"), ("fat_g", "注意食用油、坚果等来源与份量"), ("carbs_g", "结合训练安排调整主食份量")):
            average = sum((d["totals"][key]["low"] + d["totals"][key]["high"]) / 2 for d in complete) / len(complete)
            reference = sum(d["target"][key] for d in complete) / len(complete)
            if average < reference * .8 or average > reference * 1.2:
                direction = "低于" if average < reference else "高于"
                suggestions.append(f"已确认记完的{len(complete)}天，记录的{NUTRIENTS[key]}日均约{average:.0f}克，{direction}当时日均参考{reference:.0f}克；可{food}。")
        if not suggestions:
            suggestions.append(f"已确认记完的{len(complete)}天，三大营养素的记录均值接近当时参考，可保持当前搭配并继续观察。")
    else:
        suggestions.append("已确认记完且有完整营养数据的天数不足3天，暂不能判断这段时间吃多或吃少；先补齐记录，避免依据漏记调整饮食。")
    delta = round(current["weight_kg"] - baseline["weight_kg"], 2) if baseline else None
    gap = (end - date.fromisoformat(baseline["measured_on"])).days if baseline else None
    fat_delta = round(current["body_fat_pct"] - baseline["body_fat_pct"], 2) if baseline and current.get("body_fat_pct") is not None and baseline.get("body_fat_pct") is not None else None
    summary = f"较上次相隔{gap}天，体重变化{delta:+g} kg。" if baseline else "这是第一次体重跟踪记录，已作为后续对比起点。"
    if fat_delta is not None:
        summary += f"体脂率变化{fat_delta:+g}个百分点。"
    active_weight = sources.get("体重", {}).get("id") == latest["id"]
    if target.get("daily") and active_weight:
        suggestions.append("这次测量已保存，按每15天复评策略结合趋势评估目标；单次测量不重算目标或菜单。")
    elif not active_weight:
        suggestions.append("这条记录早于个人资料里的最新测量，不覆盖较新的参考量。")
    else:
        suggestions.append(target["note"])
    suggestions.append("单次体重和体脂会受测量条件与水分影响，不能证明营养估算准确，也不能据此归因于米饭或某一种食物。建议保持相近测量条件，结合后续一至两周趋势再评估。")
    return {"checkins": checkins[:30], "current": {"weight_kg": values.get("体重"), "body_fat_pct": values.get("体脂率")},
            "review": {"date": current["measured_on"], "summary": summary, "weight_change": delta, "body_fat_change": fat_delta,
                       "recorded_days": sum(d["meals"] > 0 for d in days), "complete_days": len(complete), "suggestions": suggestions, "target": target.get("daily")}}


def body_measurement_series():
    """Dated source observations, one latest value per natural day and metric.

    Charts and fortnightly review share the same daily representative evidence.
    recorded_at is the report/save timestamp, not a claimed measurement time.
    """
    today = datetime.now(ZoneInfo(db.settings()["timezone"])).date()
    points = {"weight": [], "body_fat": []}
    rows = db.records("facts", 1000)["items"] + db.records("body_checkins", 1000)["items"]
    for row in sorted(rows, key=lambda r: (r["updated_at"], r["id"])):
        data = row["data"]
        if row["kind"] == "facts" and data.get("category") != "health": continue
        raw = data.get("measured_on") if row["kind"] == "body_checkins" else data.get("observed_at")
        try: day = date.fromisoformat(raw or "")
        except (ValueError, TypeError): continue
        if day > today: continue
        fields = [("weight", data.get("weight_kg")), ("body_fat", data.get("body_fat_pct"))] if row["kind"] == "body_checkins" else [("weight" if data.get("key") == "体重" else "body_fat" if data.get("key") == "体脂率" else "other", data.get("value"))]
        for key, value in fields:
            if key not in points: continue
            try: value = float(value)
            except (ValueError, TypeError): continue
            if not (10 <= value <= 500 if key == "weight" else 1 <= value <= 75): continue
            point = {"date": str(day), "value": value, "recorded_at": row["updated_at"]}
            if not any(p == point for p in points[key]): points[key].append(point)
    return {key: list({p["date"]: p for p in sorted(rows, key=lambda p: (p["date"], p["recorded_at"]))}.values()) for key, rows in points.items()}
