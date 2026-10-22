"""Pure, conservative deduplication of dish candidates, never a preference claim.

Input is ``diet_reference.collect(...)["items"]``. The caller keeps its original
references and intake statistics; this additional view merges only equal known
ingredient/method/staple/combination signatures. Unknowns remain unknown.
"""
from copy import deepcopy
import hashlib
import json
import re
import unicodedata


VERSION = "canonical-dish-candidates-v1"
# Exact lexical synonyms only. Do not equate different species, products,
# preparation states, or broad categories with a specific ingredient.
FOOD_ALIASES = {"西红柿": "番茄", "马铃薯": "土豆", "洋芋": "土豆", "奇异果": "猕猴桃",
                "青花菜": "西兰花", "花椰菜": "花菜", "黄豆": "大豆"}
NOTICE = ("菜式去重只合并相同食材、做法、主食和组合的候选，保留全部来源。"
          "来源数量不是吃过次数或喜欢程度；不产生摄入、个人喜好或做饭能力结论。"
          "资料缺失或不确定时保守区分，原始参考和实际记录均保持不变。")


def _text(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip().casefold()


def _food(value):
    text = _text(value)
    return FOOD_ALIASES.get(text, text)


def _pattern(value):
    text = _text(value)
    # Word-level ingredient aliases within a declared combination, without
    # inventing missing components or swapping one cooking method for another.
    for alias, name in FOOD_ALIASES.items():
        text = text.replace(alias, name)
    return re.sub(r"\s*\+\s*", "+", text)


def _named(values, *, food=False):
    entries = set()
    for row in values or []:
        if isinstance(row, str):
            name, certainty = row, "unspecified"
        elif isinstance(row, dict):
            name, certainty = row.get("name", ""), row.get("certainty") or "unspecified"
        else:
            continue
        name = _food(name) if food else _pattern(name)
        if name:
            entries.add((name, _text(certainty)))
    return [{"name": name, "certainty": certainty} for name, certainty in sorted(entries)]


def signature(row):
    """Expose the auditable canonical fields behind a deterministic group key."""
    ingredients = _named(row.get("foods"), food=True)
    methods = _named(row.get("methods"))
    staples = sorted({_food(value) for value in row.get("staples", []) if _food(value)})
    combination = _pattern(row.get("combination_pattern"))
    complete = bool(ingredients and methods and staples and combination)
    return {"ingredients": ingredients, "methods": methods, "staples": staples,
            "combination_key": combination,
            # Equal known ingredients alone cannot equate frying and steaming.
            "incomplete_description": None if complete else _pattern(row.get("title")),
            "preparation_context": _text(row.get("preparation_context"))}


def _version(row):
    def integer(value):
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
    return (integer(row.get("meal_version")), integer(row.get("analysis_version")), integer(row.get("version")))


def _current(items):
    """Defensive latest-version handling for repeated source references."""
    current = {}
    for index, row in enumerate(items):
        if not isinstance(row, dict):
            continue
        identity = ("meal", row["meal_id"]) if row.get("meal_id") else ("reference", row.get("id", ""))
        if not identity[1]:
            # An anonymous row has no reliable shared source identity.
            identity = ("anonymous", index)
        old = current.get(identity)
        if old is None or _version(row) > _version(old):
            current[identity] = row
    return [row for row in current.values() if not row.get("deleted_at")]


def _source(row):
    result = {"reference_id": row.get("id"), "kind": row.get("kind"), "title": row.get("title", "")}
    for key in ("meal_id", "meal_version", "analysis_id", "analysis_version", "seed_id", "source",
                "date", "eaten_at", "status", "confirmed", "confirmation_status"):
        if row.get(key) is not None:
            result[key] = deepcopy(row[key])
    return result


def aggregate(items):
    """Build an additional candidate view without mutating its source or stats."""
    groups = {}
    current = _current(items)
    for row in current:
        canonical = signature(row)
        encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if key not in groups:
            groups[key] = {
                "id": "dish-candidate:" + key[:20], "canonical_key": key,
                "title": row.get("title", ""), **canonical,
                "source_refs": [], "source_kinds": [], "contains_actual_reference": False,
                "eligible_for_meal_totals": False, "eligible_for_consumption_frequency": False,
                "explicit_current_preference": None, "user_cooking_skill_confirmed": False,
            }
        group = groups[key]
        group["source_refs"].append(_source(row))
        kind = row.get("kind")
        if kind not in group["source_kinds"]:
            group["source_kinds"].append(kind)
        group["contains_actual_reference"] |= kind == "actual_meal_reference"
    result = list(groups.values())
    for group in result:
        group["source_count"] = len(group["source_refs"])
    return {"version": VERSION, "items": result, "source_count": len(current),
            "candidate_count": len(result), "notice": NOTICE}
