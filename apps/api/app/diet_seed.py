"""Optional, read-only starter dishes, isolated from all personal data.

Configuration contract: ``recipe_seed`` in config.json, or PDP_RECIPE_SEED,
may be ``none`` (the default) or ``home_style_v1``. An explicit ``selection``
argument overrides configuration. Selecting a seed adds recipe candidates only;
it never initializes a profile, records intake, or supplies nutrition targets.

The planner consumes ``collect()["items"]`` after the current user's explicit
preferences and actual history. Composition data and portions must be provided
by the planner independently. This module cannot read any private data root.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import re

from . import config


VERSION = "starter-recipe-seed-v1"
SEED_ROOT = Path(__file__).with_name("recipe_seeds")
AVAILABLE = {"home_style_v1": "home_style_v1.json"}
NOTICE = ("可选入门菜式，仅提供食材、烹调类别和主食搭配；不代表任何用户吃过、喜欢或会制作。"
          "个人明确偏好、忌口和实际记录优先；份量与目标须根据使用者自己的资料另算。")
ROOT_KEYS = {"schema_version", "seed_id", "title", "description", "recipes"}
RECIPE_KEYS = {"id", "title", "foods", "methods", "dish_components", "staples", "combination_pattern", "meal_types"}
TEXT_LIST_KEYS = {"foods", "methods", "dish_components", "staples", "meal_types"}


def available():
    """Choices for onboarding/configuration, without opting anyone in."""
    return [{"id": "none", "title": "使用自己的资料，不启用入门菜式"},
            {"id": "home_style_v1", "title": "可选家常菜式入门资料"}]


def selected(selection=None):
    value = selection if selection is not None else os.environ.get("PDP_RECIPE_SEED", config.CONFIG.get("recipe_seed", "none"))
    if value is None:
        value = "none"
    if not isinstance(value, str) or value not in ("none", *AVAILABLE):
        raise ValueError("recipe_seed 只能选择 none 或 home_style_v1；不接受文件路径或个人数据。")
    return value


def validate(payload):
    """Deny unrecognized metadata rather than carrying personal fields through."""
    if not isinstance(payload, dict) or set(payload) != ROOT_KEYS:
        raise ValueError("入门资料仅允许通用菜式字段。")
    if payload["schema_version"] != "1.0" or payload["seed_id"] not in AVAILABLE:
        raise ValueError("入门资料版本或标识不符。")
    if any(not isinstance(payload[key], str) or not payload[key].strip() for key in ("title", "description")):
        raise ValueError("入门资料说明无效。")
    if not isinstance(payload["recipes"], list) or not payload["recipes"]:
        raise ValueError("入门资料缺少菜式。")
    seen = set()
    for row in payload["recipes"]:
        if not isinstance(row, dict) or set(row) != RECIPE_KEYS:
            raise ValueError("入门菜式含未允许的字段。")
        identifier = row["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,79}", identifier) or identifier in seen:
            raise ValueError("入门菜式标识无效或重复。")
        seen.add(identifier)
        for key in TEXT_LIST_KEYS:
            value = row[key]
            if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError("入门菜式只接受非空文字列表。")
        if any(not isinstance(row[key], str) or not row[key].strip() for key in ("title", "combination_pattern")):
            raise ValueError("入门菜式名称或搭配说明无效。")
        if not set(row["meal_types"]) <= {"早餐", "午餐", "晚餐", "加餐"}:
            raise ValueError("入门菜式餐次无效。")
    return deepcopy(payload)


def load(selection=None):
    """Load only the enumerated bundled JSON, never private archives or a DB."""
    choice = selected(selection)
    if choice == "none":
        return None
    payload = validate(json.loads((SEED_ROOT / AVAILABLE[choice]).read_text(encoding="utf-8")))
    if payload["seed_id"] != choice:
        raise ValueError("入门资料与配置不一致。")
    return payload


def collect(selection=None):
    """Return reference-compatible candidates with explicit non-intake flags."""
    payload = load(selection)
    rows = []
    for recipe in payload["recipes"] if payload else []:
        rows.append({
            **deepcopy(recipe),
            "id": "starter:" + payload["seed_id"] + ":" + recipe["id"],
            "kind": "starter_recipe_seed", "seed_id": payload["seed_id"],
            "foods": [{"name": food, "certainty": "clear", "evidence": "入门菜式的可选食材；不是摄入记录"} for food in recipe["foods"]],
            "methods": [{"name": method, "certainty": "clear", "evidence": "入门菜式的可选烹调类别；不是用户技能或历史做法"} for method in recipe["methods"]],
            "reference_only": True, "eligible_for_meal_totals": False,
            "eligible_for_consumption_frequency": False,
            "explicit_current_preference": None, "user_cooking_skill_confirmed": False,
            "date": None, "nutrition": None,
        })
    return {"version": VERSION, "seed_id": payload["seed_id"] if payload else "none",
            "enabled": payload is not None, "items": rows, "notice": NOTICE}
