"""Portioned food-first reference menus with traceable, independently summed nutrients.

This is an estimate using specified foods, not a claim about an unseen meal.
No quantities from a past meal (especially supplement servings) become defaults.
"""
from copy import deepcopy
import json
from pathlib import Path

from . import diet_history, diet_reference, diet_policy

VERSION = "portioned-reference-menu-v1"
KEYS = ("kcal", "protein_g", "fat_g", "carbs_g")
SOURCE_PATH = Path(__file__).with_name("data") / "usda_foods_verified.json"
DATA = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
IDS = {"chicken": 171077, "salmon": 175167, "rice": 168878, "egg": 173424,
       "milk": 171265, "bread": 172688, "lettuce": 169249, "cabbage": 169979,
       "carrot": 170393, "pepper": 170427, "broccoli": 170379,
       "banana": 173944, "apple": 171688, "oil": 171413, "beef": 173053,
       "zucchini": 169291, "raw_egg": 171287, "tofu": 172476, "potato": 170026, "coffee": 171891}
NAMES = {"chicken": "去皮鸡胸肉", "salmon": "三文鱼", "rice": "白米饭", "egg": "水煮鸡蛋",
         "milk": "全脂牛奶", "bread": "全麦吐司", "lettuce": "生菜", "cabbage": "白菜",
         "carrot": "胡萝卜", "pepper": "青椒", "broccoli": "西兰花", "banana": "香蕉",
         "apple": "苹果", "oil": "橄榄油", "beef": "瘦牛肉（特定去外脂部位代表值）",
         "zucchini": "西葫芦", "raw_egg": "鸡蛋液", "tofu": "常规豆腐", "potato": "土豆", "coffee": "浓缩咖啡"}


def reference(key):
    row = next(r for r in DATA["foods"] if r["fdc_id"] == IDS[key])
    raw = row["per_100g"]
    return {"key": key, "name": NAMES[key], "weight_basis": row["state_and_weighing"],
            "per_100g": {"kcal": raw["energy_kcal"], "protein_g": raw["protein_g"], "fat_g": raw["fat_g"], "carbs_g": raw["carbohydrate_g"]},
            "source": {"title": f"USDA SR Legacy 2018 CSV · FDC {row['fdc_id']}",
                       "url": DATA["source"]["official_csv_zip"], "kind": "official_composition_reference",
                       "fdc_id": row["fdc_id"], "description": row["description_usda"],
                       "dataset_sha256": DATA["source"]["csv_sha256"]},
            "assumptions": ["通用食物成分代表值，不是用户实际品牌标签；品种、部位及加工含水量会造成误差。",
                            "碳水按该USDA条目的总碳水口径；热量直接采用来源值，不强行改成4/4/9。"]}


def personal_product(products, alias):
    rows = [r for r in products if r["data"].get("identity_confirmed") and
            alias in [r["data"].get("name"), *r["data"].get("aliases", [])] and
            r["data"].get("source_kind") in ("label_photo", "user_label")]
    if len(rows) != 1:
        return None
    row, data = rows[0], rows[0]["data"]
    if any(data.get(k) is None for k in ("energy", "protein_g", "fat_g", "carbs_g")):
        return None
    multiplier = 1 if data.get("basis") == "per_100g" else 100 / data["serving_size"] if data.get("basis") == "per_serving" and data.get("serving_size") and data.get("serving_unit") == "g" else None
    if multiplier is None:
        return None
    return {"key": "personal_" + alias, "name": data["name"], "weight_basis": "包装食品净重；每份标签先按已确认每份克数归一，再按建议净重换算",
            "per_100g": {"kcal": data["energy"] / (4.184 if data["energy_unit"] == "kJ" else 1) * multiplier,
                         **{k: data[k] * multiplier for k in KEYS[1:]}},
            "source": {"title": "个人标签库：" + data["name"], "kind": "personal_label", "product_id": row["id"],
                       "product_version": row["version"], "source_images": data.get("source_images", []), "source_note": data["source_note"]},
            "serving_size": data.get("serving_size"), "serving_description": data.get("serving_description", ""),
            "assumptions": ["按该款标签及指定净重换算；若换品牌、口味或标签版本应重新核算。"]}


def item(food, grams, slot, number):
    return {"item_id": f"{slot}-{number}-{food['key']}", "name": food["name"], "quantity": grams, "unit": "g",
            "weight_basis": food["weight_basis"], "nutrition": {k: round(food["per_100g"][k] * grams / 100, 4) for k in KEYS},
            "per_100g": dict(food["per_100g"]), "source": deepcopy(food["source"]), "assumptions": list(food["assumptions"])}


def total(items):
    return {k: round(sum(row["nutrition"][k] for row in items), 4) for k in KEYS}


def portion_text(row):
    return f"{row['name']}{row['quantity']:g}g（{row['weight_basis']}）"


def compare(actual, target):
    policy = diet_policy.get_policy()["quantification"]
    tolerances = {"kcal": max(policy["min_energy_tolerance_kcal"], target["kcal"] * policy["energy_tolerance_ratio"]), "protein_g": policy["protein_tolerance_g"], "fat_g": policy["fat_tolerance_g"], "carbs_g": policy["carbs_tolerance_g"]}
    difference = {k: round(actual[k] - target[k], 4) for k in KEYS}
    return {"targets": dict(target), "actual": dict(actual), "difference": difference,
            "tolerances": tolerances, "within_tolerance": all(abs(difference[k]) <= tolerances[k] for k in KEYS),
            "note": "容差是食谱规划的实用校验范围，不是精确营养处方；实际食品和称量仍有误差。"}


def _empty(reason):
    return {"quantification_version": VERSION, "quantification_status": "needs_review", "valid_for_use": False,
            "plan_scope": "full_day_reference", "recipes": [], "daily_nutrition": None,
            "target_comparison": None, "quantification_note": reason}


def _build_one(target, preferences, history, products, references, training=False):
    """Find a practical three-meal menu; never assign a budget as food nutrition."""
    target = target.get("daily") or {}
    if any(not isinstance(target.get(k), (int, float)) or target[k] <= 0 for k in KEYS):
        return _empty("参考目标不完整，不能发布声称全天够量的菜单。")
    if not 1600 <= target["kcal"] <= 3600:
        return _empty("当前参考量超出这份成人模板的份量校验范围，需人工复核后再给具体菜单。")
    likes = diet_history.confirmed_likes(preferences)
    if any(r["data"].get("confirmed") and r["data"].get("kind") in ("allergy", "constraint", "dislike") for r in preferences):
        return _empty("已记录忌口，暂不自动生成未经核对的量化菜单。")
    # Explicit preferences precede observations. Unquantified mixed dishes remain examples only.
    bread = reference("bread")
    cereal = personal_product(products or [], "燕麦")
    if cereal and not any(name in likes["carbs"] for name in ("土司", "吐司", "全麦吐司", "全麦面包")):
        bread = cereal
    dairy = personal_product(products or [], "酸奶") or reference("milk")
    dairy_grams = 150  # Plus the separately quantified 170g milk in proposed latte.
    # These methods/staple combinations must exist in the supplied reference view.
    chicken_ref = next((r for r in references.get("items", []) if any(m.get("certainty") == "clear" and "西葫芦炒" in m.get("name", "") for m in r.get("methods", [])) and any(f.get("name") == "鸡胸肉" and f.get("certainty") == "clear" for f in r.get("foods", []))), None)
    fish_ref = next((r for r in references.get("items", []) if any(m.get("certainty") == "clear" and "汤锅" in m.get("name", "") for m in r.get("methods", [])) and {"三文鱼", "深绿叶菜", "白米饭"} <= {f.get("name") for f in r.get("foods", []) if f.get("certainty") == "clear"}), None)
    sandwich_ref = next((r for r in references.get("items", []) if r.get("kind") == "actual_meal_reference" and "牛肉" in r["title"] and "三明治" in r["title"]), None)
    if not chicken_ref or not fish_ref or not sandwich_ref:
        return _empty("可核算成分已有，但尚未找到这组菜式/做法/主食的用户参考依据；保持待复核，不用陌生模板顶替。")
    evening, lean, rice, oil = (reference(k) for k in ("salmon", "chicken", "rice", "oil"))
    whey = personal_product(products or [], "蛋白粉") if training else None
    if training and (not whey or not whey.get("serving_size")):
        return _empty("训练日练后粉的具体产品和每份标签尚不齐，不能把历史某次勺数套作每日用量。")
    whey_grams = whey["serving_size"] if whey else 0
    # 500g vegetables + 270g edible fruit are portions in this proposal, never inferred intake.
    # A familiar beef sandwich is a proposed weighed recipe, not a decomposition of an old photo.
    breakfast_protein = reference("beef") if "牛肉" in likes["protein"] else reference("egg")
    fixed = [(breakfast_protein, 100), (dairy, dairy_grams), (reference("banana"), 120),
             (reference("apple"), 150), (reference("zucchini"), 300),
             (reference("raw_egg"), 100), (reference("lettuce"), 200),
             (reference("milk"), 170), (reference("coffee"), 30)]
    if whey:
        fixed.append((whey, whey_grams))
    candidates = []
    scale = target["kcal"] / 2400
    for bread_g in range(70, 131, 10):
        for evening_g in range(140, 241, 10):
            selected = fixed + [(bread, bread_g), (evening, evening_g)]
            base = {k: sum(food["per_100g"][k] * grams / 100 for food, grams in selected) for k in KEYS}
            rice_g = round((target["carbs_g"] - base["carbs_g"]) / rice["per_100g"]["carbs_g"] * 100 / 5) * 5
            lean_g = round((target["protein_g"] - base["protein_g"] - rice["per_100g"]["protein_g"] * rice_g / 100) / lean["per_100g"]["protein_g"] * 100 / 5) * 5
            oil_g = round(target["fat_g"] - base["fat_g"] - rice["per_100g"]["fat_g"] * rice_g / 100 - lean["per_100g"]["fat_g"] * lean_g / 100)
            # Do not force impossible targets with enormous meat/rice portions or negative oil.
            if not (100 <= lean_g <= 300 and 250 <= rice_g <= 650 and 5 <= oil_g <= 25):
                continue
            values = {k: round(base[k] + sum(f["per_100g"][k] * g / 100 for f, g in ((lean, lean_g), (rice, rice_g), (oil, oil_g))), 4) for k in KEYS}
            comparison = compare(values, target)
            if not comparison["within_tolerance"]:
                continue
            # Prefer manageable portions and modest cooking oil; small target deviations are normal.
            cost = abs(values["kcal"] - target["kcal"]) / 100 + abs(lean_g - 240 * scale) / 100 + abs(evening_g - 180) / 100 + abs(bread_g - 100) / 100 + abs(oil_g - 15) / 20
            candidates.append((cost, bread_g, evening_g, rice_g, lean_g, oil_g))
    if not candidates:
        return _empty("在当前食物及合理份量范围内无法完成目标校验；暂不声称该菜单能够达标，需补充可选食物或人工调整。")
    _, bread_g, evening_g, rice_g, lean_g, oil_g = min(candidates)
    lunch_rice = round(rice_g * .55 / 5) * 5
    lunch_oil = round(oil_g / 2)
    slots = [
        ("早餐", [(bread, bread_g), (breakfast_protein, 100), (dairy, dairy_grams / 2), (reference("lettuce"), 50)] + ([] if training else [(reference("banana"), 120)])),
        ("午餐", [(lean, lean_g), (rice, lunch_rice), (reference("zucchini"), 300), (reference("raw_egg"), 100), (oil, lunch_oil)]),
        ("下午咖啡 / 水果", [(reference("apple"), 150), (reference("milk"), 170), (reference("coffee"), 30)]),
        *(([("练前餐", [(reference("banana"), 120)]), ("练后", [(whey, whey_grams)])]) if training else []),
        ("晚餐", [(evening, evening_g), (rice, rice_g - lunch_rice), (reference("lettuce"), 150), (oil, oil_g - lunch_oil), (dairy, dairy_grams / 2)]),
    ]
    recipes = []
    for name, ingredients in slots:
        items = [item(food, grams, name, index) for index, (food, grams) in enumerate(ingredients) if grams > 0]
        nutrition = total(items)
        recipes.append({"meal_type": name, "items": items, "foods": [portion_text(i) for i in items],
                        "nutrition": nutrition, "contributes_to_daily_total": True, "optional": False,
                        "selection_basis": "confirmed_preferences_and_sourced_portions",
                        "display_condition": "训练日" if name in ("练前餐", "练后") else "",
                        "preparation": "肉鱼和蔬菜按所标生可食重称量；米饭按熟重，炒蛋按入锅前去壳蛋液称重。列出的油为这餐全部新增烹调油，酱料/糖/额外油未包含，加入时另计。"})
    titles = {"早餐": "全麦牛肉三明治＋酸奶", "午餐": "煎鸡胸肉＋西葫芦炒蛋＋米饭", "晚餐": "三文鱼叶菜汤锅＋米饭＋酸奶",
              "下午咖啡 / 水果": "无另加糖拿铁＋苹果", "练前餐": "香蕉（从全天水果份量中安排）", "练后": "水冲蛋白粉（建议1标签份）"}
    refs = {"早餐": sandwich_ref, "午餐": chicken_ref, "晚餐": fish_ref}
    core_keys = {"chicken", "salmon", "beef", "rice", "bread", "potato", "raw_egg"}
    for recipe in recipes:
        recipe["dish_title"] = titles[recipe["meal_type"]]
        if recipe["meal_type"] == "早餐" and breakfast_protein["key"] != "beef":
            recipe["dish_title"] = "全麦鸡蛋三明治＋奶类"
        core = [i for i in recipe["items"] if i["item_id"].split("-")[-1] in core_keys]
        recipe["portion_summary"] = "；".join(f"{('瘦牛肉' if i['name'] == NAMES['beef'] else i['name'])}{i['quantity']:g}g（{'熟重' if i['name'] == '白米饭' else '即食重' if i['name'] == '全麦吐司' else '生可食重'}）" for i in core) or "；".join(f"{i['name']}{i['quantity']:g}g" for i in recipe["items"])
        if recipe["meal_type"] in ("午餐", "晚餐"):
            recipe["portion_summary"] += "；蔬菜一份，少油"
        recipe["reference_sources"] = [diet_reference.source_ref(refs[recipe["meal_type"]])] if recipe["meal_type"] in refs else []
        if recipe["meal_type"] == "午餐":
            recipe["preparation"] += "西葫芦炒蛋沿用素材里的组合；此份计划建议把鸡胸煎熟（新方案做法），照片本身只能确认表面褐化、不能确认煎/烤设备，不反改参考索引的判断。"
        if recipe["meal_type"] == "晚餐":
            recipe["preparation"] += "沿用三文鱼叶菜汤锅配米饭；本提案用你明确喜欢的生菜做叶菜，清水汤底，不把素材中未知汤料自动计成零。"
        if recipe["meal_type"] == "下午咖啡 / 水果":
            recipe["preparation"] = "用户已说明拿铁通常不另加糖；本方案建议全脂牛奶170g＋浓缩咖啡30g，品类/份量为可替换计划假设，非实际已喝；奶按每100g来源核算，未把g默认为ml。换奶或容量要再核算。"
        if recipe["meal_type"] == "练后":
            recipe["preparation"] = "本分支建议按已存标签1份配水，剂量是这份菜单的建议，不是把今天1.5勺设为日常固定量；水量按实际记录。"
    actual = total([i for recipe in recipes for i in recipe["items"]])
    check = compare(actual, target)
    macro_energy = round(actual["protein_g"] * 4 + actual["fat_g"] * 9 + actual["carbs_g"] * 4, 4)
    return {"quantification_version": VERSION, "quantification_status": "verified_estimate", "valid_for_use": True,
            "plan_scope": "full_day_reference", "recipes": recipes, "daily_nutrition": actual,
            "target_comparison": check, "energy_consistency": {"source_kcal": actual["kcal"], "macro_4_4_9_kcal": macro_energy,
                "difference_kcal": round(actual["kcal"] - macro_energy, 4), "note": "数据库能量采用条目原值，标签kJ按4.184换算；来源能量系数、膳食纤维及舍入可使4/4/9校验略有差异，不修改原标签凑数。"},
            "quantification_note": "全天食物建议合计已含本分支的水果、奶类及条件性练后粉；已计入建议拿铁的170g全脂牛奶和30g浓缩咖啡，无另加糖。",
            "scope_notice": "这是一整天的参考菜单，不是今天剩余需要吃的量；已经吃过的食物应计入全天，不能在其上再叠加整套。",
            "sources": [dict(DATA["source"], title="USDA SR Legacy 2018 官方原始数据", url=DATA["source"]["official_csv_zip"])],
            "limitations": ["用户确认的喜好优先；来源不足的整道混合菜不硬拆成精准配料，只作今后可选样式。",
                            "各项是指定食物与称重口径的成分估计，不保证实际烹饪或品牌相同；不同生熟重量不能互换。",
                            "2400及三大营养素仍是现有起始参考，需结合后续体重趋势、训练表现与完整记录复核。",
                            "酸奶75g＋75g合计一包150g，可整包放在其中一餐，属于调移不是追加。",
                            "休息日午餐较大，可将部分鸡胸移到下午餐，全天总量不增加；吃不完按实际记录后调整，不强塞。"]}


def _without_breakfast(plan):
    result = deepcopy(plan)
    if not result.get("valid_for_use"):
        return result
    breakfast = next(r for r in result["recipes"] if r["meal_type"] == "早餐")
    afternoon = next(r for r in result["recipes"] if r["meal_type"] == "下午咖啡 / 水果")
    dinner = next(r for r in result["recipes"] if r["meal_type"] == "晚餐")
    for row in breakfast["items"]:
        target = dinner if row["source"]["kind"] == "personal_label" and "发酵乳" in row["name"] or row["name"] == NAMES["milk"] else afternoon
        target["items"].append(row)
    result["recipes"].remove(breakfast)
    afternoon.update(meal_type="下午餐", dish_title="全麦三明治＋水果＋拿铁（早餐移至此时）", portion_summary=breakfast["portion_summary"] + "；另含已核算的无另加糖拿铁", reference_sources=breakfast["reference_sources"])
    for recipe in result["recipes"]:
        recipe["nutrition"] = total(recipe["items"])
        recipe["foods"] = [portion_text(row) for row in recipe["items"]]
    result["daily_nutrition"] = total([row for recipe in result["recipes"] for row in recipe["items"]])
    result["quantification_note"] += " 此分支仅适用于你明确选择不吃早餐：原早餐三明治/水果分到下午，奶类分到晚餐；未丢掉营养，也没有一顿强塞双份主餐。"
    return result


def build(target, preferences, history, products=None, references=None, training_status="unknown"):
    references = references or {"items": []}
    from . import diet_seed_plan
    if diet_seed_plan.should_use(references):
        return diet_seed_plan.build(target, preferences, history, products, references, training_status)
    variants = []
    for training in (False, True):
        base = _build_one(target, preferences, history, products or [], references, training)
        for skipped in (False, True):
            plan = _without_breakfast(base) if skipped else deepcopy(base)
            identifier = ("training" if training else "rest") + ("_no_breakfast" if skipped else "_breakfast")
            label = ("训练日" if training else "休息日") + (" · 不吃早餐" if skipped else " · 吃早餐")
            plan.update(id=identifier, label=label, condition=label + "时适用；不代表已确认当天执行", training_status="training" if training else "rest", skipped_breakfast=skipped)
            variants.append(plan)
    selected = ("training" if training_status == "training" else "rest") + "_breakfast"
    base = deepcopy(next(p for p in variants if p["id"] == selected))
    return {**base, "variants": variants, "active_variant_id": selected if training_status in ("training", "rest") else None,
            "training_status": training_status, "condition_label": base["label"] + "参考；" + ("当天训练状态已明确，早餐未说跳过就不推断没吃。" if training_status != "unknown" else "当天训练状态未确认，请选对应分支。"),
            "reference_materials": {k: references.get(k) for k in ("version", "archive", "archive_count", "actual_reference_count", "archive_index_sha256", "notice")}}
