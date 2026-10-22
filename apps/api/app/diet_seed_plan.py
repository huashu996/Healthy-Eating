"""Opt-in starter menus for an empty personal history and a computed own target.

This fallback is deliberately separate from the existing personal menu. It uses
bundled starter dish combinations and independently sourced composition data;
it cannot create meals, preferences, profile defaults, or supplement habits.
"""
from copy import deepcopy
import math

from . import diet_history, diet_quantified as quantified, diet_reference, diet_seed


VERSION = "starter-portioned-menu-v1"
KEYS = quantified.KEYS
REQUIRED_DISHES = ("chicken-zucchini-egg-rice", "salmon-lemon-greens-soup")


def should_use(references):
    """Personal evidence always stays with the personal planner, ahead of seed."""
    seed = references.get("seed") or {}
    rows = references.get("items") or []
    return (seed.get("enabled") is True and seed.get("seed_id") == "home_style_v1"
            and bool(rows) and all(row.get("kind") == "starter_recipe_seed" for row in rows))


def _empty(reason, target_status=None):
    return {"quantification_version": VERSION, "quantification_status": "needs_review", "valid_for_use": False,
            "plan_scope": "full_day_reference", "recipes": [], "daily_nutrition": None,
            "target_comparison": None, "quantification_note": reason,
            "target_status": target_status, "variants": [], "active_variant_id": None}


def _source_rows(references):
    # Reload only the enumerated public recipe seed, never trust personal-looking
    # metadata added to a candidate. All ingredient nutrients come from USDA.
    rows = diet_seed.collect(references["seed"]["seed_id"])["items"]
    return {slug: next((row for row in rows if row["id"].endswith(":" + slug)), None) for slug in REQUIRED_DISHES}


def _selection(preferences):
    """Supported explicit likes influence the starter, without becoming bans."""
    likes = diet_history.confirmed_likes(preferences)
    recognized_protein = {"鸡胸肉", "去皮鸡胸肉", "鸡肉", "三文鱼", "鸡蛋", "水煮蛋", "牛奶", "全脂牛奶", "牛肉", "瘦牛肉", "豆腐"}
    recognized_carbs = {"米饭", "白米饭", "熟米饭", "全麦面包", "全麦吐司", "土司", "吐司", "面包"}
    if likes["protein"] and not recognized_protein.intersection(likes["protein"]):
        return None, "已确认的蛋白质食物喜好超出这份入门菜单可核算的范围，请先补充对应食材来源或另选菜式。"
    if likes["carbs"] and not recognized_carbs.intersection(likes["carbs"]):
        return None, "已确认的主食喜好超出这份入门菜单可核算的范围，请先补充对应食材来源或另选菜式。"
    if likes["fiber"] and not {"西葫芦", "生菜", "叶菜", "绿叶菜", "绿叶生菜"}.intersection(likes["fiber"]):
        return None, "已确认的蔬菜喜好与这份入门菜式尚未匹配，请另选本人愿意吃且可以核算的蔬菜组合。"
    if likes["fats"] and "橄榄油" not in likes["fats"]:
        return None, "已确认的油脂食物喜好与这份入门配方尚未匹配，请补充对应成分后重新核算。"
    # Generic breakfast is explicitly supplementary, not a reconstructed photo.
    breakfast = "beef" if {"牛肉", "瘦牛肉"}.intersection(likes["protein"]) else "tofu" if "豆腐" in likes["protein"] else "egg"
    return breakfast, None


def _solve(target, breakfast_key):
    foods = {key: quantified.reference(key) for key in
             ("bread", "milk", "egg", "beef", "tofu", "banana", "apple", "zucchini", "raw_egg", "lettuce", "chicken", "salmon", "rice", "oil")}
    breakfast_g = 100 if breakfast_key in ("beef", "tofu") else 50
    fixed = [(breakfast_key, breakfast_g), ("milk", 250), ("banana", 100), ("apple", 150),
             ("zucchini", 250), ("raw_egg", 50), ("lettuce", 250)]
    candidates = []
    for bread_g in range(60, 171, 10):
        for salmon_g in range(80, 211, 10):
            chosen = fixed + [("bread", bread_g), ("salmon", salmon_g)]
            base = {key: sum(foods[food]["per_100g"][key] * grams / 100 for food, grams in chosen) for key in KEYS}
            rice_g = round((target["carbs_g"] - base["carbs_g"]) / foods["rice"]["per_100g"]["carbs_g"] * 100 / 5) * 5
            chicken_g = round((target["protein_g"] - base["protein_g"] - foods["rice"]["per_100g"]["protein_g"] * rice_g / 100)
                              / foods["chicken"]["per_100g"]["protein_g"] * 100 / 5) * 5
            oil_g = round(target["fat_g"] - base["fat_g"] - foods["rice"]["per_100g"]["fat_g"] * rice_g / 100
                          - foods["chicken"]["per_100g"]["fat_g"] * chicken_g / 100)
            # Practical bounds for this particular template, not medical limits.
            if not (30 <= chicken_g <= 300 and 200 <= rice_g <= 1000 and 0 <= oil_g <= 30):
                continue
            totals = {key: round(base[key] + sum(foods[food]["per_100g"][key] * grams / 100
                       for food, grams in (("chicken", chicken_g), ("rice", rice_g), ("oil", oil_g))), 4) for key in KEYS}
            if not quantified.compare(totals, target)["within_tolerance"]:
                continue
            cost = (abs(totals["kcal"] - target["kcal"]) / 100 + abs(bread_g - 100) / 60
                    + abs(salmon_g - 140) / 80 + abs(chicken_g - 180) / 150 + abs(rice_g - 500) / 300)
            candidates.append((cost, bread_g, salmon_g, rice_g, chicken_g, oil_g))
    if not candidates:
        return None
    _, bread_g, salmon_g, rice_g, chicken_g, oil_g = min(candidates)
    return foods, breakfast_g, bread_g, salmon_g, rice_g, chicken_g, oil_g


def _recipe(slot, title, portions, sources, note, foods):
    items = [quantified.item(foods[key], grams, slot, index) for index, (key, grams) in enumerate(portions) if grams > 0]
    return {"meal_type": slot, "dish_title": title, "items": items,
            "foods": [quantified.portion_text(row) for row in items], "nutrition": quantified.total(items),
            "portion_summary": "；".join(quantified.portion_text(row) for row in items),
            "contributes_to_daily_total": True, "optional": False,
            "selection_basis": "opt_in_starter_recipe_with_independent_portions",
            "reference_sources": [diet_reference.source_ref(row) for row in sources],
            "preparation": note + " 所列油是本餐全部新增烹调油；未列出的酱料、糖或其他食材若加入需另算。"}


def _variant(target, solution, sources, breakfast_key, training=False, skipped=False):
    foods, breakfast_g, bread_g, salmon_g, rice_g, chicken_g, oil_g = solution
    lunch_rice = round(rice_g / 2 / 5) * 5
    lunch_oil = round(oil_g / 2)
    breakfast_name = {"egg": "水煮鸡蛋", "beef": "熟制瘦牛肉", "tofu": "加热豆腐"}[breakfast_key]
    breakfast = [("bread", bread_g), (breakfast_key, breakfast_g), ("milk", 250)]
    recipes = [
        _recipe("早餐", "全麦面包＋" + breakfast_name + "＋牛奶", breakfast, [],
                "这是入门计划的通用早餐补充搭配，不来自照片或任何人的已吃记录，也不代表已确认喜好。按各食材标明的生熟可食重称量；牛奶按克核算，不把克当毫升。", foods),
        _recipe("午餐", "鸡胸肉＋西葫芦炒蛋＋米饭",
                [("chicken", chicken_g), ("zucchini", 250), ("raw_egg", 50), ("rice", lunch_rice), ("oil", lunch_oil)],
                [sources[REQUIRED_DISHES[0]]], "从已选择的入门菜式借用组合；鸡肉按所用方法熟制，西葫芦和去壳蛋液炒制，米饭按熟重。份量是本次按个人目标计算的新建议。", foods),
        _recipe("下午水果", "苹果", [("apple", 150)], [], "苹果是这份计划明确列出的通用水果搭配，按可食重；不表示已经吃过。", foods),
        _recipe("练前餐" if training else "水果搭配", "香蕉", [("banana", 100)], [],
                "训练分支把同一份香蕉放在练前，全天不额外叠加。" if training else "香蕉属于全天已列份量，可在合适时段吃；无需另外追加一份。", foods),
        _recipe("晚餐", "三文鱼生菜汤锅＋米饭",
                [("salmon", salmon_g), ("lettuce", 250), ("rice", rice_g - lunch_rice), ("oil", oil_g - lunch_oil)],
                [sources[REQUIRED_DISHES[1]]], "采用入门鱼类叶菜汤锅配米饭的组合；本次独立配方明确用生菜与清水汤底，未列柠檬或其他汤料，不能当作原图配方。鱼与叶菜按生可食重称量后做熟。", foods),
    ]
    if skipped:
        moved = recipes.pop(0)
        afternoon = next(recipe for recipe in recipes if recipe["meal_type"] == "下午水果")
        afternoon["items"].extend(moved["items"])
        afternoon["dish_title"] = "下午餐：原早餐搭配＋苹果"
        afternoon["preparation"] += " 仅在本人明确选择不吃早餐时，将原早餐移到此时，全天份量不增加；这不是对漏记早餐的推断。"
        afternoon["foods"] = [quantified.portion_text(row) for row in afternoon["items"]]
        afternoon["portion_summary"] = "；".join(afternoon["foods"])
        afternoon["nutrition"] = quantified.total(afternoon["items"])
    totals = quantified.total([row for recipe in recipes for row in recipe["items"]])
    comparison = quantified.compare(totals, target)
    label = ("训练日" if training else "休息日") + (" · 不吃早餐" if skipped else " · 吃早餐")
    return {"quantification_version": VERSION, "quantification_status": "verified_estimate", "valid_for_use": comparison["within_tolerance"],
            "plan_scope": "full_day_reference", "recipes": recipes, "daily_nutrition": totals,
            "target_comparison": comparison, "id": ("training" if training else "rest") + ("_no_breakfast" if skipped else "_breakfast"),
            "label": label, "condition": label + "时可选；不代表已确认执行", "training_status": "training" if training else "rest",
            "skipped_breakfast": skipped, "quantification_note": "入门菜单使用本人的当前计算目标，逐食材独立核算；训练分支只调整水果时段，没有默认补剂或额外训练热量。",
            "scope_notice": "这是可审核的全天建议，不是剩余应吃量；尚未记录为任何一餐，已经吃过的食物应另行按真实情况记录。",
            "energy_consistency": {"source_kcal": totals["kcal"], "macro_4_4_9_kcal": round(totals["protein_g"] * 4 + totals["fat_g"] * 9 + totals["carbs_g"] * 4, 4),
                "difference_kcal": round(totals["kcal"] - totals["protein_g"] * 4 - totals["fat_g"] * 9 - totals["carbs_g"] * 4, 4),
                "note": "来源热量保持数据库原值，不通过4/4/9反改。"},
            "sources": [dict(quantified.DATA["source"], title="USDA SR Legacy 官方成分数据", url=quantified.DATA["source"]["official_csv_zip"])],
            "limitations": ["入门菜式是可选建议，不是本人的饮食历史、喜好或烹调技能；有个人来源后应优先使用个人资料。",
                            "通用成分与指定份量的估计不等于实际品牌或烹调结果，购买食品有明确标签后应重算。",
                            "此有限模板不能处理所有忌口、偏好或目标；适配不成功时保持待复核，不强行凑目标。"]}


def build(target, preferences, history, products=None, references=None, training_status="unknown"):
    """Return a reviewable starter plan, with no reads/writes of personal data."""
    references = references or {}
    if not should_use(references):
        return _empty("未显式选择入门资料，或已有个人菜式来源；不使用入门模板覆盖个人资料。")
    daily = target.get("daily") or {}
    if target.get("status") != "estimated" or any(isinstance(daily.get(key), bool) or not isinstance(daily.get(key), (int, float))
            or not math.isfinite(daily[key]) or daily[key] <= 0 for key in KEYS):
        return _empty("须先用本人的完整健康资料计算有效目标；入门菜式不携带或补造目标。", target.get("status", "needs_info"))
    if not 1600 <= daily["kcal"] <= 3600:
        return _empty("本人的目标超出这份有限入门模板的份量校验范围，需另行复核。", target["status"])
    if any(row.get("data", {}).get("confirmed") and row["data"].get("kind") in ("allergy", "constraint", "dislike") for row in preferences):
        return _empty("已记录个人忌口或限制，当前入门菜式无法可靠核对，不自动给出可能冲突的菜单。", target["status"])
    if history.get("meals_7d") or history.get("meals_14d"):
        return _empty("已有实际饮食历史，应先使用个人候选；不以入门菜单盖过本人记录。", target["status"])
    breakfast_key, reason = _selection(preferences)
    if reason:
        return _empty(reason, target["status"])
    sources = _source_rows(references)
    if not all(sources.values()):
        return _empty("入门菜式组合不完整，无法给出可追溯的量化菜单。", target["status"])
    solution = _solve(daily, breakfast_key)
    if solution is None:
        return _empty("在这份入门菜式的份量范围内未能匹配本人的目标，请补充其他可选食材或复核目标。", target["status"])
    variants = [_variant(daily, solution, sources, breakfast_key, training, skipped) for training in (False, True) for skipped in (False, True)]
    choice = ("training" if training_status == "training" else "rest") + "_breakfast"
    selected = deepcopy(next(plan for plan in variants if plan["id"] == choice))
    return {**selected, "variants": variants, "active_variant_id": choice if training_status in ("training", "rest") else None,
            "training_status": training_status, "condition_label": "可选入门菜单；" + ("按本人已确认的训练安排选择分支，未说跳过早餐不推断没吃。" if training_status in ("training", "rest") else "训练状态未确认，先选对应分支。"),
            "reference_materials": {"version": references.get("version"), "seed": deepcopy(references["seed"]),
                "archive": None, "archive_count": 0, "actual_reference_count": 0},
            "target_status": target["status"], "starter_seed_id": references["seed"]["seed_id"]}
