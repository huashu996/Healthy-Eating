"""Read-only three-diet-day evidence for plans, without treating gaps as deficits."""
from __future__ import annotations

from datetime import date, timedelta
import math
import json

from . import diet_day, diet_tracking, diet_policy

VERSION = "three-diet-days-v1"
NUTRIENTS = ("kcal", "protein_g", "fat_g", "carbs_g")


def _refs(rows):
    return sorted({(row["id"], row["version"]): {"id": row["id"], "version": row["version"]}
                   for row in rows}.values(), key=lambda item: (item["id"], item["version"]))


def summarize_three_days(target_date, reports, meals, target):
    """Summarize target-3 through target-1; new target never fills old target gaps.

    Pending meals retain recorded nutrition estimates, not confirmed full-day intake.
    Planned/skipped/replaced/reference-only records are excluded. Values remain
    ranges of recorded meals and are not represented as full-day actual intake
    unless completion, portions and all nutrient coverage are established.
    """
    from .diet import current_analysis

    target_date = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
    policy = diet_policy.get_policy()
    window_days = policy["recent_days"]
    end = target_date - timedelta(days=1)
    start = end - timedelta(days=window_days - 1)
    current = {}
    for row in meals:
        if row["id"] not in current or row["version"] > current[row["id"]]["version"]:
            current[row["id"]] = row
    recorded = []
    for row in current.values():
        data = row["data"]
        if (row.get("deleted_at") or data.get("execution") not in ("done", "partial")
                or data.get("eaten_fraction", 1) <= 0 or data.get("reference_only") or data.get("is_reference")):
            continue
        if start <= diet_day.meal_diet_date(row) <= end:
            recorded.append(row)
    ordered_reports = sorted(reports, key=lambda row: (row.get("created_at", ""), row.get("version", 0), row["id"]), reverse=True)
    # Deliberately do not pass the next plan's target into a historical summary.
    # This also avoids backfilling the still-open day when previewing tomorrow.
    reviewed = diet_tracking.review_days(start, end, ordered_reports, recorded, {}, calculate=False, timezone=diet_day.TIMEZONE)
    days, refs, analyses, target_refs = [], list(recorded), [], []
    for review in reviewed:
        day = review["date"]
        rows = [row for row in recorded if diet_day.meal_diet_date(row).isoformat() == day]
        actual = [row for row in rows if row["data"].get("status") == "confirmed"]
        pending_count = len(rows) - len(actual)
        matching = [report for row in rows if (report := current_analysis(row, ordered_reports)) is not None]
        confirmed_totals = {}
        for key in NUTRIENTS:
            values = []
            for actual_row in actual:
                analysis = current_analysis(actual_row, ordered_reports)
                value = (analysis or {}).get("data", {}).get("nutrition", {}).get(key)
                if value is not None:
                    values.append({side: value[side] * actual_row["data"].get("eaten_fraction", 1) for side in ("low", "high")})
            confirmed_totals[key] = ({"low": round(sum(value["low"] for value in values), 2),
                                       "high": round(sum(value["high"] for value in values), 2), "coverage": len(values)}
                                      if values else None)
        analyses.extend(matching)
        if review.get("log"):
            refs.append(review["log"])
        coverage = {key: {"meals_with_values": (review["totals"][key] or {}).get("coverage", 0),
                          "confirmed_meals": len(actual), "recorded_meals": len(rows),
                          "complete": bool(rows) and not pending_count and (review["totals"][key] or {}).get("coverage", 0) == len(rows)}
                    for key in NUTRIENTS}
        nutrition_complete = all(item["complete"] for item in coverage.values())
        finished = bool(review["finished"] and not pending_count)
        saved = review["target"]
        saved_plan = next((report for report in ordered_reports
                           if report.get("timezone") == diet_day.TIMEZONE and report["data"].get("cycle_version")
                           and report["data"].get("plan_mode") != "test_preview"
                           and report["data"].get("publication_trigger") != "score_only"
                           and report["data"].get("target_date") == day and report["data"].get("reference_targets")), None)
        saved_refs = [saved_plan] if saved_plan else []
        saved_target_state = "archived" if saved_plan and saved else "unknown"
        if not saved_plan:
            saved_refs = [report for report in matching if report["data"].get("reference_targets", {}).get("daily")]
            archived = {json.dumps(report["data"]["reference_targets"]["daily"], sort_keys=True): report["data"]["reference_targets"]["daily"] for report in saved_refs}
            # A preview may include today's still-open diary. Its already saved
            # analysis reference is legitimate; a newly passed plan target is not.
            saved = next(iter(archived.values())) if len(archived) == 1 else None
            saved_target_state = "analysis_reference" if len(archived) == 1 else "conflicting_sources" if archived else "unknown"
        target_refs.extend(saved_refs)
        target_complete = bool(saved) and all(
            isinstance(saved.get(key), (int, float)) and not isinstance(saved.get(key), bool)
            and math.isfinite(saved[key]) and saved[key] > 0 for key in NUTRIENTS)
        can_assess = bool(rows and finished and nutrition_complete and target_complete)
        completeness = ("unrecorded" if not rows else "pending_confirmation" if pending_count else
                        "partial_nutrition" if not nutrition_complete else "not_finished" if not finished else
                        "missing_saved_target" if not target_complete else "complete")
        days.append({"date": day, "recorded_meals": len(rows), "confirmed_meals": len(actual),
                     "pending_meals": pending_count, "analyzed_meals": len(matching),
                     "totals": review["totals"], "recorded_totals": review["totals"],
                     "confirmed_totals": confirmed_totals, "nutrition_coverage": coverage,
                     "finished": finished, "nutrition_complete": nutrition_complete,
                     "completeness": completeness, "saved_target": saved, "saved_target_state": saved_target_state, "can_assess_intake": can_assess,
                     "input_refs": _refs(rows + ([review["log"]] if review.get("log") else [])),
                     "analysis_refs": _refs(matching), "target_refs": _refs(saved_refs)})
    recorded_days = sum(day["recorded_meals"] > 0 for day in days)
    complete_days = sum(day["can_assess_intake"] for day in days)
    finished_days = sum(day["finished"] and day["recorded_meals"] > 0 for day in days)
    fully_covered_days = sum(day["nutrition_complete"] for day in days)
    totals = {}
    for key in NUTRIENTS:
        known = [day["totals"][key] for day in days if day["totals"][key] is not None]
        totals[key] = ({"low": round(sum(value["low"] for value in known), 2),
                        "high": round(sum(value["high"] for value in known), 2),
                        "coverage": sum(value["coverage"] for value in known),
                        "days_with_values": len(known), "complete": all(day["nutrition_coverage"][key]["complete"] for day in days)}
                       if known else None)
    short_reason = f"近3个饮食日有{recorded_days}天留有记录，{fully_covered_days}天已确认且营养齐全、{finished_days}天确认记完。"
    if complete_days < window_days:
        short_reason += "记录或当日参考不齐，不能认定热量过少；按方案目标日的已确认训练安排和餐食结构调整。"
    else:
        short_reason += "仅比较这些完整记录与各日已存参考，今天仍按当天训练安排分配，不追补此前差额。"
    structure_notes = [
        "热量与三大营养素保留已记录餐食的估算范围；缺少的餐次、份量和营养值保持未知，不填零。",
        "待确认餐次保留为已记录估算，不作为已确认的完整全天摄入；参考图不计餐，未记完不能判摄入低。",
        "明日或今日的新目标不回填历史；不因某天记录偏少多吃补账，也不靠跳餐抵扣前日。",
        "三日摘要只支持近期餐食结构调整，7/14日习惯观察继续单独保留；训练状态未知时先确认，不默认训练或休息。",
    ]
    return {"version": VERSION, "target_date": target_date.isoformat(), "window_start": start.isoformat(),
            "window_end": end.isoformat(), "window_days": window_days,
            "policy_version": policy["policy_version"], "policy_hash": policy["policy_hash"], "skill_hash": policy["skill_hash"], "days": days, "recorded_days": recorded_days,
            "complete_days": complete_days, "finished_days": finished_days, "fully_covered_days": fully_covered_days,
            "totals": totals, "recorded_totals": totals, "can_assess_intake": complete_days == window_days, "short_reason": short_reason,
            "structure_notes": structure_notes, "input_refs": _refs(refs), "analysis_refs": _refs(analyses),
            "target_refs": _refs(target_refs)}
