"""Load versioned software policy afresh; no personal data or network access."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

POLICY_PATH = Path(__file__).with_name("diet_policy.json")
SKILL_PATH = Path(__file__).resolve().parents[3] / "SKILL.md"
QUANTIFICATION_KEYS = {"energy_tolerance_ratio", "min_energy_tolerance_kcal", "protein_tolerance_g", "fat_tolerance_g", "carbs_tolerance_g", "max_portion_scale"}


def get_policy() -> dict:
    """Read every call, validate required controls, and bind exact source bytes."""
    raw = POLICY_PATH.read_bytes()
    skill = SKILL_PATH.read_bytes()
    result = json.loads(raw)
    if result.get("schema_version") != "1.0" or not isinstance(result.get("policy_version"), str):
        raise ValueError("Unsupported or missing diet policy version")
    if result.get("recent_days") != 3 or result.get("habit_windows_days") != [7, 14]:
        raise ValueError("Unsupported diet evidence windows")
    if result.get("day_boundary") != {"timezone": "Asia/Shanghai", "hour": 7, "time": "07:00", "explicit_date_precedence": True, "legacy_attribution": "preserve"}:
        raise ValueError("Diet day policy cannot silently change historical attribution")
    values = result.get("quantification", {})
    if set(values) != QUANTIFICATION_KEYS or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in values.values()):
        raise ValueError("Invalid quantification policy")
    if values["energy_tolerance_ratio"] > 1 or values["max_portion_scale"] < 1:
        raise ValueError("Invalid tolerance or scaling policy")
    rules = result.get("rules", [])
    if not rules or len({rule["id"] for rule in rules}) != len(rules) or any(rule.get("status") not in {"active", "insufficient_data", "proposal"} for rule in rules):
        raise ValueError("Invalid policy rule manifest")
    execution = result.get("execution", {})
    if any(execution.get(key) is not False for key in ("external_model_calls", "new_providers_allowed", "scheduler_enabled")):
        raise ValueError("Diet policy cannot enable external execution or scheduling")
    publication = result.get("publication", {})
    if (publication.get("timezone") != "Asia/Shanghai" or publication.get("formal_time") != "07:00"
            or publication.get("formal_success_limit_per_date") != 1
            or publication.get("before_formal_time") != "collect_and_save_context_only"
            or publication.get("ordinary_context_changes") != "save_only"
            or publication.get("skipped_meal_changes") != "save_only"
            or publication.get("formal_uses_latest_context") is not True
            or publication.get("test_preview_promoted_to_formal") is not False
            or publication.get("evening_settlement") != "intake_and_context_only"):
        raise ValueError("Diet policy cannot prebuild or repeatedly replace formal daily menus")
    if publication.get("scoring") != {"time": "07:00", "timezone": "Asia/Shanghai",
            "diet_day": "07:00_to_next_07:00", "scope": "previous_completed_diet_day_only",
            "ordinary_changes": "save_only", "preview_scores": False,
            "score_only_bypass": False, "insufficient_evidence": "null_with_reasons"}:
        raise ValueError("Diet scoring must remain in the once-daily morning workflow")
    result["policy_hash"] = hashlib.sha256(raw).hexdigest()
    result["skill_hash"] = hashlib.sha256(skill).hexdigest()
    result["hash_algorithm"] = "sha256"
    result["loaded_from"] = "project_software_policy"
    return deepcopy(result)
