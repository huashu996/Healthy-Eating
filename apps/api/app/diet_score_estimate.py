"""Audited midpoint display; never discards original scoring evidence.

Created by standing morning policy or an explicit historical correction. Missing food,
clinical/applicability, alcohol, and macro consistency evidence still block it.
The full original ranges and review reasons remain in the formal snapshot.
"""
from copy import deepcopy

from . import diet_scoring

NOTICE = "估算评分：按已记录营养区间中点计算；外食份量和酒精度含估计，实际可能跨分档。原估算范围与复核提示保留，整数分不代表测量精度。"
V8_NOTICE = "估算评分：按已记录营养区间中点及该日连续评分规则计算；外食份量和酒精度含估计。原估算范围与复核提示保留，整数分不代表测量精度。"
WEIGHTS = {"energy": 25, "protein": 20, "fat": 15, "carbs": 10,
           "vegetables_raw_edible_g": 10, "fruit_edible_g": 10,
           "whole_grains_mixed_beans_dry_g": 10}
V8_WEIGHTS = {**WEIGHTS, "carbs": 15, "whole_grains_mixed_beans_dry_g": 5}
ALLOWED_REVIEW = {label + "估算范围跨越明显偏离目标分档，需收窄估算依据"
                  for _, _, label, _ in diet_scoring.TARGET_PARTS} | {
    "脂肪供能估算范围跨越原复核界线，需复核份量/用油"}
V8_ALLOWED_REVIEW = {label + "估算范围跨越连续评分零分界线，需保留区间复核"
                     for _, _, label, _ in diet_scoring.TARGET_PARTS} | {
    "脂肪供能估算范围跨越原复核界线，需复核份量/用油"}
PROTEIN_SHARE_REVIEW = "蛋白供能估算范围跨越一般参考上界，需结合背景复核"


def _protein_share_estimate_supported(snapshot):
    """Allow only uncertainty crossing, never a midpoint applicability failure."""
    context = snapshot.get("score_context") or {}
    weight = context.get("weight_kg")
    totals = snapshot.get("totals") or {}
    meals = snapshot.get("meals")
    if (context.get("applicable") is not True
            or not diet_scoring.number(weight, positive=True)
            or not isinstance(context.get("training"), bool)
            or not isinstance(meals, int) or isinstance(meals, bool) or meals <= 0
            or snapshot.get("analyzed") != meals
            or any(not diet_scoring.valid_range(totals.get(k))
                   or totals[k].get("coverage") != meals for k in diet_scoring.MACROS)):
        return False
    energy = diet_scoring.midpoint(totals["kcal"])
    protein = diet_scoring.midpoint(totals["protein_g"])
    return (totals["kcal"]["low"] > 0
            and protein * 4 / energy <= diet_scoring.RULES["protein"]["max_energy_fraction"]
            and protein / weight <= diet_scoring.RULES["protein_individual_review_g_per_kg"])


def total(parts, *, version=diet_scoring.VERSION):
    value = max(0, sum(p["points"] for p in parts))
    rules = diet_scoring.rules_for_version(version)
    if "severe_domain_cap" in rules and any(p["points"] == 0 for p in parts if p["key"] in ("energy", "protein", "fat", "carbs")):
        value = min(value, rules["severe_domain_cap"])
    return round(value)


def _parts_valid(parts, *, version=diet_scoring.V7_VERSION):
    weights = WEIGHTS if version == diet_scoring.V7_VERSION else V8_WEIGHTS
    if not isinstance(parts, list) or len(parts) not in (7, 8):
        return False
    seen = set()
    for p in parts:
        if not isinstance(p, dict) or p.get("key") in seen:
            return False
        key = p.get("key")
        seen.add(key)
        points = p.get("points")
        if key == "alcohol":
            if p.get("maximum") != 0 or not diet_scoring.number(-points if isinstance(points, (int, float)) and not isinstance(points, bool) else None) or not -30 <= points <= 0:
                return False
        elif key not in weights or p.get("maximum") != weights[key] or not diet_scoring.number(points) or not 0 <= points <= weights[key]:
            return False
    return set(weights).issubset(seen)


PARTIAL_METHOD = "v7-partial-food-score-interval-midpoint-v1"
V8_PARTIAL_METHOD = "v8-partial-food-score-interval-midpoint-v1"
PARTIAL_NOTICE = "估算评分：宏量按原营养区间中点；一个部分记录食物组按已知量下限得分至满分的区间中点估分，未记录部分仍未知，并非按零摄入。该分数区间仅表示固定宏量中点后的缺项影响，不是全天不确定性区间。原记录与复核提示保留。"


def _partial_component(snapshot, parts):
    unknown = [p for p in parts if p.get("points") is None]
    if len(unknown) != 1 or not _protein_share_estimate_supported(snapshot):
        return None
    part = unknown[0]
    key = part.get("key")
    quality = snapshot.get("score_quality_evidence") or {}
    value = (quality.get("totals") or {}).get(key)
    partial = quality.get("partial_meal_groups") or []
    if (key not in diet_scoring.CORE_FOODS
            or not any(p.get("key") == key and p.get("source_ids") and p.get("basis") for p in partial)
            or quality.get("unresolved_portions") != [key]
            or not diet_scoring.valid_range(value)
            or not isinstance(value.get("coverage"), int) or isinstance(value.get("coverage"), bool)
            or not 0 < value["coverage"] < snapshot["meals"]):
        return None
    low = diet_scoring.food_points(value["low"], key, version=snapshot["score_version"])
    maximum = diet_scoring.food_maximum(key, version=snapshot["score_version"])
    bounds = {"low": low, "high": float(maximum)}
    part.update(points=(low + maximum) / 2, status="estimated",
                reason=f"已合格记录的下限量可支持{low:g}分；部分记录餐次的剩余量未知。按原公式得分区间{low:g}–{maximum}的中点估分，不推定未知食物克数或零摄入。",
                score_bounds=bounds)
    return {"key": key, "component_score_bounds": bounds,
            "known_eligible_intake_low_g": value["low"],
            "scope": "conditional_on_recorded_macro_midpoints_not_full_uncertainty_interval"}


def retained_historical_estimate(snapshot):
    """Only an audited regrade may retain old uncertainty with no new missing data."""
    audit = snapshot.get('score_policy_override') or {}
    prior = audit.get('retained_estimate_audit') or {}
    return (diet_scoring.historical_override_supported(snapshot)
            and audit.get('previous_estimated') is True
            and audit.get('recalculated_readiness') == {'status': 'ready', 'missing': []}
            and snapshot.get('score_readiness') == {'status': 'estimate_retained', 'missing': []}
            and prior.get('method') in ('v7-recorded-midpoint-v1', PARTIAL_METHOD,
                                        'v8-recorded-midpoint-v1', V8_PARTIAL_METHOD)
            and bool(prior.get('source_id')) and len(prior.get('reason', '')) >= 10
            and bool(prior.get('created_at')))


def build(snapshot, *, source_id, reason, created_at):
    version = snapshot.get("score_version")
    if version not in (diet_scoring.V7_VERSION, diet_scoring.VERSION):
        raise ValueError("不支持此版本的独立估算")
    legacy = version == diet_scoring.V7_VERSION
    missing = (snapshot.get("score_readiness") or {}).get("missing")
    allowed = ALLOWED_REVIEW if legacy else V8_ALLOWED_REVIEW
    parts = deepcopy(snapshot.get("components") or [])
    partial = _partial_component(snapshot, parts)
    if partial:
        allowed = allowed | {diet_scoring.LABELS[partial["key"]] + "需由AI完成已发照片的份量估算；不因未称重扣分"}
    if isinstance(missing, list) and PROTEIN_SHARE_REVIEW in missing and _protein_share_estimate_supported(snapshot):
        allowed = allowed | {PROTEIN_SHARE_REVIEW}
    if (snapshot.get("score") is not None
            or not isinstance(missing, list) or (not missing and not retained_historical_estimate(snapshot))
            or not set(missing).issubset(allowed)):
        raise ValueError("仅营养区间跨档导致待复核时可保存独立估算；其他评分保护仍生效")
    quality = snapshot.get("score_quality_evidence") or {}
    if quality.get("alcohol_missing") or len(parts) != 7 or not _parts_valid(parts, version=version):
        raise ValueError("估算仍需要完整七项与饮酒依据")
    if quality.get("alcohol_doses"):
        ethanol = quality.get("ethanol_g")
        if not diet_scoring.number(ethanol):
            raise ValueError("缺少完整酒精量依据")
        penalty = diet_scoring.alcohol_penalty(ethanol)
        parts.append({"key": "alcohol", "name": "酒精摄入", "maximum": 0, "points": -penalty,
            "reason": f"按已记录饮用量与酒精度估算，纯酒精约{ethanol:.2f}g，扣{penalty:g}分；饮用ml×酒精度÷100×0.789，合计每3g扣1分、最高30分。酒精度含估计；软件权重非医学风险，少量也非无风险。",
            "status": "estimated", "intake": round(ethanol, 4), "unit": "g纯酒精"})
    extra = {}
    if partial:
        bound_parts = deepcopy(parts)
        bounds = {}
        for side in ("low", "high"):
            next(p for p in bound_parts if p["key"] == partial["key"])["points"] = partial["component_score_bounds"][side]
            bounds[side] = total(bound_parts, version=version)
        extra = {"conditional_score_bounds": bounds, "partial_food_estimate": partial}
    method = (PARTIAL_METHOD if legacy else V8_PARTIAL_METHOD) if partial else ("v7-recorded-midpoint-v1" if legacy else "v8-recorded-midpoint-v1")
    return {"estimated_score": total(parts, version=version), "estimated_components": parts, "estimate_notice": PARTIAL_NOTICE if partial else NOTICE if legacy else V8_NOTICE,
            "estimate_audit": {"method": method, "created_at": created_at, **extra,
                               "source_id": source_id, "reason": reason}}


def valid(snapshot):
    """Read-time validation. Fresh input/analysis identities are checked upstream."""
    try:
        expected = build(snapshot, source_id="validation", reason="validation", created_at="validation")
    except (ValueError, TypeError, KeyError):
        return False
    audit = snapshot.get("estimate_audit") or {}
    value = snapshot.get("estimated_score")
    return (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100
            and value == expected["estimated_score"]
            and snapshot.get("estimated_components") == expected["estimated_components"]
            and snapshot.get("estimate_notice") == expected["estimate_notice"]
            and audit.get("method") == expected["estimate_audit"]["method"]
            and audit.get("conditional_score_bounds") == expected["estimate_audit"].get("conditional_score_bounds")
            and audit.get("partial_food_estimate") == expected["estimate_audit"].get("partial_food_estimate")
            and bool(audit.get("source_id")) and len(audit.get("reason", "")) >= 10
            and bool(audit.get("created_at")))


def apply_daily_policy(snapshot):
    """Apply the user's standing midpoint-display policy at morning settlement.

    Never rewrites historical snapshots or removes evidence/clinical guards.
    The existing estimate validator and mirror contract remain authoritative.
    """
    from . import db, diet_policy
    policy = diet_policy.get_policy().get("daily_estimated_scoring", {})
    if (policy.get("enabled") is not True
            or snapshot.get("date", "") < policy.get("effective_diet_date", "9999")
            or snapshot.get("score") is not None or valid(snapshot)):
        return snapshot
    try:
        estimate = build(snapshot, source_id=policy["source_id"],
                         reason=policy["reason"], created_at=db.now())
    except (ValueError, KeyError, TypeError):
        return snapshot  # Missing real evidence is not a zero-intake assumption.
    if estimate["estimate_audit"]["method"] in (PARTIAL_METHOD, V8_PARTIAL_METHOD):
        partial_policy = policy.get("partial_reported_food_group") or {}
        expected_method = (partial_policy.get("methods_by_score_version") or {}).get(snapshot["score_version"], partial_policy.get("method"))
        if (expected_method != estimate["estimate_audit"]["method"]
                or snapshot.get("date", "") < partial_policy.get("effective_diet_date", "9999")):
            return snapshot
        estimate["estimate_audit"]["policy_source_id"] = partial_policy.get("source_id")
    snapshot.update(estimate)
    snapshot["state"] = "已结算（估算）"
    return snapshot
