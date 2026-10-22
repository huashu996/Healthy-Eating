"""Read-only history: current actual meals and valid saved settlement scores.

Never settles, edits a meal, copies a plan into intake, or backfills old targets.
"""
from calendar import monthrange
from datetime import date
from math import isfinite
import re

from . import db, diet, diet_cycle, diet_day, diet_tracking, diet_score_estimate
from .security import SafeError

KEYS = tuple(diet_tracking.NUTRIENTS)


def _actual(row, today):
    data = row.get("data", {})
    fraction = data.get("eaten_fraction", 1)
    if (row.get("deleted_at") or data.get("execution") not in ("done", "partial")
            or isinstance(fraction, bool) or not isinstance(fraction, (int, float))
            or not isfinite(fraction) or not 0 < fraction <= 1
            or data.get("is_reference") or data.get("reference_only") or data.get("is_plan")
            or data.get("eligible_for_meal_totals") is False
            or data.get("kind") in ("history_reference", "actual_meal_reference")
            or data.get("source_kind") in ("reference", "reference_image")
            or data.get("plan_scope") in ("full_day_reference", "remaining_today")
            or data.get("snapshot_scope") in ("reference", "full_day_reference", "remaining_today", "planned")):
        return False
    try:
        return diet_day.meal_diet_date(row) <= today
    except (KeyError, TypeError, ValueError):
        return False


def _load():
    today = diet_day.current_diet_day()
    with db.connect() as con:
        meals = [db.unpack(r) for r in con.execute("SELECT * FROM records WHERE kind='meals' AND module='diet' AND mode='live' AND deleted_at IS NULL ORDER BY updated_at DESC")]
        reports = [db.unpack(r) for r in con.execute("SELECT * FROM reports WHERE module='diet' AND mode='live' ORDER BY created_at DESC,id DESC")]
    return today, [m for m in meals if _actual(m, today)], reports


def _score_valid(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value) and 0 <= value <= 100


def _settled_at_valid(value):
    try:
        diet_day.aware_datetime(value)
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def _range(value, fraction=1):
    if not isinstance(value, dict):
        return None
    low, high = value.get("low"), value.get("high")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in (low, high)) or not 0 <= low <= high:
        return None
    return {"low": round(low * fraction, 2), "high": round(high * fraction, 2)}


def _days(start, end, meals, reports, today):
    with db.connect() as con:
        logs = [db.unpack(r) for r in con.execute("SELECT * FROM records WHERE kind='diet_days' AND mode='live' AND deleted_at IS NULL ORDER BY updated_at DESC,id")]
    target = diet.active_target()
    current = diet_tracking.review_days(start, end, reports, meals, target, calculate=False, day_logs=logs)
    saved = diet_cycle.settled_days(start, end, reports, meals, target, day_logs=logs)
    snapshots = {}
    for report in reports:
        if (report.get("timezone") == diet_day.TIMEZONE and report["data"].get("cycle_version") == diet_cycle.VERSION
                and report["data"].get("scores_settled") is not False and report["data"].get("plan_mode") != "test_preview"):
            for snapshot in report["data"].get("review_days", []):
                snapshots.setdefault(snapshot["date"], (snapshot, report))
    result = []
    for actual, settled in zip(current, saved):
        snapshot, source = snapshots.get(actual["date"], ({}, None))
        saved_target = snapshot.get("target") or {}
        complete = (actual["analyzed"] == actual["meals"] and all(
            _range(actual["totals"].get(key)) is not None
            and actual["totals"][key].get("coverage") == actual["meals"]
            and not isinstance(saved_target.get(key), bool)
            and isinstance(saved_target.get(key), (int, float))
            and isfinite(saved_target[key]) and saved_target[key] > 0 for key in KEYS))
        matching_snapshot = (bool(snapshot) and not settled.get("pending_changes")
                             and diet_tracking.diet_scoring.saved_version_supported(snapshot))
        readiness = snapshot.get("score_readiness")
        maximum = snapshot.get("score_maximum", 100)
        denominator_valid = (_score_valid(maximum) and maximum > 0
            and _score_valid(settled.get("score")) and settled["score"] <= maximum
            and isinstance(readiness, dict)
            and (readiness.get("status") == "ready" and maximum == 100
                 or readiness.get("status") == "partial" and maximum < 100
                    and snapshot.get("score_scope") == "recorded_partial"))
        valid = (denominator_valid and complete and isinstance(readiness, dict) and readiness.get("status") in ("ready", "partial") and actual["date"] <= today.isoformat() and actual["meals"] > 0
                 and not settled.get("pending_changes") and _settled_at_valid(snapshot.get("settled_at"))
                 and _score_valid(settled.get("score"))
                 and diet_tracking.diet_scoring.saved_version_supported(settled))
        score = settled["score"] if valid else None
        estimate_valid = (not valid and matching_snapshot and complete and actual["meals"] > 0
                          and actual["date"] < today.isoformat()
                          and _settled_at_valid(snapshot.get("settled_at"))
                          and _settled_at_valid((snapshot.get("estimate_audit") or {}).get("created_at"))
                          and diet_score_estimate.valid(snapshot))
        estimated_score = snapshot["estimated_score"] if estimate_valid else None
        display_score = score if valid else estimated_score
        state = settled.get("state", "未评分")
        if not valid and settled.get("score") is not None:
            state = "评分无效"
        if actual["date"] > today.isoformat():
            state = "未到日期"
        elif not actual["meals"]:
            state = "未记录"
        result.append({**actual, "score": score, "score_status": "saved" if valid else "estimated" if estimate_valid else "unscored",
                       "estimated_score": estimated_score,
                       "estimated_components": snapshot["estimated_components"] if estimate_valid else [],
                       "estimate_notice": snapshot["estimate_notice"] if estimate_valid else "",
                       "score_band": ("green" if display_score >= 85 else "yellow" if display_score >= 70 else "red") if display_score is not None and (estimate_valid or readiness.get("status") == "ready") else "neutral",
                       "score_maximum": snapshot.get("score_maximum", 100) if valid else None,
                       "score_coverage_pct": snapshot.get("score_coverage_pct", 100) if valid else 0,
                       "score_scope": snapshot.get("score_scope", "recorded_full") if valid else "unavailable",
                       "state": state, "components": snapshot.get("components", []) if matching_snapshot else [],
                       "score_readiness": snapshot.get("score_readiness") if matching_snapshot else None,
                       "score_limitations": snapshot.get("score_limitations", []) if matching_snapshot else [],
                       "score_evidence_sources": snapshot.get("score_evidence_sources", []) if matching_snapshot else [],
                       "target": snapshot.get("target") if valid else actual["target"],
                       "score_source": {"id": source["id"], "version": source["version"], "settled_at": snapshot.get("settled_at")} if source else None,
                       "pending_changes": bool(settled.get("pending_changes")),
                       "score_method": snapshot.get("score_method") or diet_tracking.SCORE_METHOD if matching_snapshot else diet_tracking.SCORE_METHOD,
                       "score_method_scope": "saved" if matching_snapshot and snapshot.get("score_method") else "current_rule",
                       "score_version": snapshot.get("score_version") if matching_snapshot else diet_tracking.SCORE_VERSION,
                       "snapshot_score_version": snapshot.get("score_version"),
                       "is_future": actual["date"] > today.isoformat()})
    return result


def calendar(month=None):
    today, meals, reports = _load()
    month = month or today.strftime("%Y-%m")
    try:
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise ValueError
        start = date.fromisoformat(month + "-01")
        end = start.replace(day=monthrange(start.year, start.month)[1])
    except (TypeError, ValueError):
        raise SafeError("invalid_month", "月份须为有效的 YYYY-MM", 422)
    return {"read_only": True, "month": month, "today": today.isoformat(), "timezone": diet_day.TIMEZONE,
            "rollover_hour": diet_day.ROLLOVER_HOUR, "days": _days(start, end, meals, reports, today),
            "first_weekday": start.weekday(), "recorded_days": len({diet_day.meal_diet_date(m) for m in meals if start <= diet_day.meal_diet_date(m) <= end}),
            "notice": "按北京时间07:00划分饮食日；旧记录保留原日期。只显示实际已吃记录，未评分不代表0分。"}


def day_detail(value):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        selected = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise SafeError("invalid_date", "日期须为有效的 YYYY-MM-DD", 422)
    today, meals, reports = _load()
    day = _days(selected, selected, meals, reports, today)[0]
    entries = []
    totals = {key: None for key in KEYS}
    for row in sorted(meals, key=diet_day.meal_time_key):
        if diet_day.meal_diet_date(row) != selected:
            continue
        report = diet.current_analysis(row, reports)
        analysis = report["data"] if report else {}
        nutrition = analysis.get("nutrition") or {}
        scaled = {key: _range(nutrition.get(key), row["data"].get("eaten_fraction", 1)) for key in KEYS}
        for key, amount in scaled.items():
            if amount is not None:
                total = totals[key] or {"low": 0, "high": 0, "coverage": 0}
                total = {"low": round(total["low"] + amount["low"], 2), "high": round(total["high"] + amount["high"], 2), "coverage": total["coverage"] + 1}
                totals[key] = total
        entries.append({"id": row["id"], "version": row["version"], "title": analysis.get("meal_title") or row["data"]["title"],
                        "meal_type": row["data"]["meal_type"], "eaten_at": row["data"]["eaten_at"],
                        "diet_date": value, "eaten_fraction": row["data"].get("eaten_fraction", 1),
                        "nutrition": scaled, "basis": nutrition.get("basis", ""), "limitations": analysis.get("limitations", []),
                        "notes": row["data"].get("notes", ""), "analysis_ref": {"id": report["id"], "version": report["version"]} if report else None})
    return {**day, "read_only": True, "totals": totals, "entries": entries, "timezone": diet_day.TIMEZONE,
            "rollover_hour": diet_day.ROLLOVER_HOUR,
            "notice": "合计仅包含已记录且有营养数据的实际餐次；缺值保留待补，未记录不等于没吃。历史目标采用当时存档，不用今天目标回填。"}
