"""One Beijing 07:00 diet-day boundary, without reassigning legacy records.

New records persist their assigned diet_date. Legacy records without that field
keep their former Beijing calendar-date grouping. Reading never migrates data.
Actual eaten_at / received_at timestamps are not shifted to fabricate a date.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Mapping
from zoneinfo import ZoneInfo

from .diet_policy import get_policy

_BOUNDARY = get_policy()["day_boundary"]
TIMEZONE = _BOUNDARY["timezone"]
ZONE = ZoneInfo(TIMEZONE)
ROLLOVER_HOUR = _BOUNDARY["hour"]
RULE_VERSION = "beijing-0700-v1"


def aware_datetime(value: datetime | str) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("饮食记录时间必须含时区")
    return result


def _date(value: date | str) -> date:
    if isinstance(value, datetime):
        raise ValueError("饮食日期必须是 YYYY-MM-DD，不是时间")
    return date.fromisoformat(value) if isinstance(value, str) else value


def now_beijing() -> datetime:
    return datetime.now(ZONE)


def current_diet_day(now: datetime | str | None = None) -> date:
    """Before 07:00 Beijing, the current diet day is the previous date."""
    stamp = aware_datetime(now) if now is not None else now_beijing()
    return (stamp.astimezone(ZONE) - timedelta(hours=ROLLOVER_HOUR)).date()


def next_boundary(now: datetime | str | None = None) -> datetime:
    return datetime.combine(current_diet_day(now) + timedelta(days=1), time(ROLLOVER_HOUR), ZONE)


def _data(meal: Mapping) -> Mapping:
    return meal["data"] if isinstance(meal.get("data"), Mapping) else meal


def meal_time_key(meal: Mapping) -> tuple:
    """Chronology uses instants, never ISO text or the last edit timestamp.

    If an actual eating time is unavailable, retain the original receipt/record
    time. Stable original-record ties prevent later corrections from reordering.
    This is read-only: no timestamp or dietary-date attribution is rewritten.
    """
    data = _data(meal)

    def instant(*values):
        for value in values:
            try:
                return aware_datetime(value).timestamp()
            except (TypeError, ValueError, AttributeError, OverflowError):
                continue
        return float("inf")

    return (instant(data.get("eaten_at"), data.get("received_at"), meal.get("created_at")),
            instant(data.get("received_at"), meal.get("created_at")), str(meal.get("id", "")))


def meal_diet_date(meal: Mapping) -> date:
    """Use saved attribution; preserve original natural dates for legacy rows."""
    data = _data(meal)
    if data.get("diet_date"):
        return _date(data["diet_date"])
    return aware_datetime(data["eaten_at"]).astimezone(ZONE).date()


def assign_diet_date(data: Mapping, *, received_at: datetime | str | None = None,
                     existing: Mapping | None = None) -> dict:
    """Assign once for a new meal; keep the original day on later corrections.

    A caller-supplied diet_date represents an explicit meal date and wins over
    the receipt boundary. Chat importers should supply the original message's
    received_at even when processing is delayed. No inferred timestamp replaces
    eaten_at, and editing an existing meal cannot move its attribution.
    """
    result = dict(data)
    if existing is not None:
        old = _data(existing)
        day = meal_diet_date(old)
        if result.get("diet_date") and _date(result["diet_date"]) != day:
            raise ValueError("补充或修正原餐不能改变原饮食日期")
        if result.get("received_at") and (
            not old.get("received_at")
            or aware_datetime(result["received_at"]) != aware_datetime(old["received_at"])
        ):
            raise ValueError("补充或修正原餐不能改变原接收时间")
        result["diet_date"] = day.isoformat()
        result["received_at"] = old.get("received_at")
        return result
    if received_at is not None and result.get("received_at") and (
        aware_datetime(received_at) != aware_datetime(result["received_at"])
    ):
        raise ValueError("消息与餐食的接收时间不一致")
    stamp = received_at if received_at is not None else result.get("received_at")
    stamp = aware_datetime(stamp) if stamp is not None else now_beijing()
    explicit = result.get("diet_date")
    result["diet_date"] = (_date(explicit) if explicit else current_diet_day(stamp)).isoformat()
    result["received_at"] = stamp.isoformat()
    return result


def training_plan_for_date(target_date: date | str, records=None) -> dict:
    """Return only an explicit plan for this exact date, never infer from exercise.

    Absence, legacy rows and missing provenance remain unknown. A newer unknown
    record supersedes an older known plan. This read does not modify the record,
    mark any day finished, or count a planned session as performed exercise.
    """
    day = _date(target_date).isoformat()
    if records is None:
        from . import db
        records = db.records("diet_days", 10000)["items"]
    matches = [row for row in records
               if not row.get("deleted_at") and row["data"].get("date") == day]
    row = max(matches, key=lambda item: (item.get("updated_at", ""), item.get("version", 0), item.get("id", "")), default=None)
    data = row["data"] if row else {}
    status = data.get("training_status", "unknown")
    source = data.get("training_source", "")
    if status not in ("training", "rest") or not source.strip():
        status = "unknown"
    return {"date": day, "training_status": status, "training_source": source,
            "training_source_id": data.get("training_source_id", ""),
            "needs_confirmation": status == "unknown", "is_plan": True,
            "input_refs": [{"id": row["id"], "version": row["version"]}] if row else []}


def dish_requests_for_date(target_date: date | str, records=None) -> dict:
    """Read versioned explicit wishes for one date, never intake or preferences.

    Consumers must either fulfill these exact request_refs or mark the plan as
    needing review. An unsupported dish is not permission to silently drop it.
    """
    from copy import deepcopy
    from .schemas import DishRequest

    day = _date(target_date).isoformat()
    if records is None:
        from . import db
        records = db.records("diet_days", 10000)["items"]
    current = {}
    for row in records:
        if row["id"] not in current or row["version"] > current[row["id"]]["version"]:
            current[row["id"]] = row
    matches = [row for row in current.values()
               if not row.get("deleted_at") and row["data"].get("date") == day]
    row = max(matches, key=lambda item: (item.get("updated_at", ""), item.get("version", 0), item.get("id", "")), default=None)
    items = [DishRequest.model_validate(item).model_dump(mode="json")
             for item in (row["data"].get("dish_requests", []) if row else [])]
    refs = [{"id": row["id"], "version": row["version"], "dish": item["dish"]} for item in items]
    return {"date": day, "items": deepcopy(items),
            "input_refs": [{"id": row["id"], "version": row["version"]}] if row else [],
            "request_refs": refs, "is_plan": True,
            "priority": "explicit_target_date_request", "is_consumption": False,
            "is_persistent_preference": False}
