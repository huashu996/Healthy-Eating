"""Menu publication timing, separate from intake calculation and context storage.

This module never schedules work or records meals. Formal daily menus are made
from fresh morning context; an explicitly requested preview stays a preview.
"""
from datetime import date, datetime, time

from . import diet_day


def window(target_date, now=None):
    day = date.fromisoformat(str(target_date))
    stamp = diet_day.aware_datetime(now) if now is not None else diet_day.now_beijing()
    stamp = stamp.astimezone(diet_day.ZONE)
    boundary = datetime.combine(day, time(7), diet_day.ZONE)
    eligible = stamp.date() == day and stamp >= boundary
    return {"target_date": day.isoformat(), "timezone": diet_day.TIMEZONE,
            "formal_not_before": boundary.isoformat(), "formal_allowed_now": eligible,
            "stage": "morning_publication_window" if eligible else "context_collection_only",
            "ordinary_updates_generate_menu": False, "test_preview_becomes_formal": False,
            "formal_success_limit": 1}


def require_formal_window(target_date, now=None):
    result = window(target_date, now)
    if not result["formal_allowed_now"]:
        raise ValueError("正式当日菜单只在目标日期北京时间07:00后生成；此前只保存上下文，显式测试须用test_preview")
    return result


def successful_formal(reports, target_date):
    """Only newly evidenced formal full-day menus count, never legacy/preview."""
    day = str(target_date)
    for report in reports:
        data = report.get("data", {})
        menu = data.get("next_meal") or {}
        if (data.get("plan_mode") == "formal" and menu.get("plan_mode") == "formal"
                and menu.get("plan_scope") == "full_day_reference"
                and menu.get("reference_date", data.get("target_date")) == day
                and menu.get("valid_for_use") is True
                and menu.get("quantification_status") == "verified_estimate"):
            return report
    return None


def label_menu(menu, mode):
    if mode not in ("formal", "test_preview"):
        raise ValueError("菜单模式必须为formal或test_preview")
    notice = ("测试预览：仅用于本次明确测试，不是07:00正式菜单，正式菜单须在当日读取最新上下文重新生成。"
              if mode == "test_preview" else "当日正式菜单：基于本次早间流程的最新上下文；全天新信息先保存，默认不反复生成菜单。")
    for item in [menu] + list(menu.get("variants") or []):
        item.update(plan_mode=mode, publication_notice=notice)
    return menu
