"""Explicit, date-scoped inventory. Never a preference or consumed meal."""
from copy import deepcopy
import csv

from . import db, diet_day, diet_quantified, food_catalog
from .schemas import PantryConstraint


def for_date(target_date, records=None):
    day = diet_day._date(target_date).isoformat()
    rows = db.records("diet_days", 10000)["items"] if records is None else records
    current = {}
    for row in rows:
        if row["id"] not in current or row["version"] > current[row["id"]]["version"]:
            current[row["id"]] = row
    matches = [row for row in current.values() if not row.get("deleted_at") and row["data"].get("date") == day]
    row = max(matches, key=lambda item: (item.get("updated_at", ""), item.get("version", 0), item.get("id", "")), default=None)
    items = [PantryConstraint.model_validate(item).model_dump(mode="json")
             for item in (row["data"].get("pantry_constraints", []) if row else [])]
    refs = [{"id": row["id"], "version": row["version"], "category": item["category"],
             "allowed_foods": item["allowed_foods"]} for item in items]
    return {"date": day, "items": deepcopy(items), "constraint_refs": refs,
            "input_refs": [{"id": row["id"], "version": row["version"]}] if row else [],
            "is_plan": True, "is_consumption": False, "is_persistent_preference": False,
            "quantity_availability": "not_specified", "unspecified_categories": "unrestricted_by_this_record"}


def validate(menu, pantry):
    """Classify source foods, not caller labels, and check every executable branch."""
    if not pantry or not pantry.get("items"):
        return {"status": "not_applicable", "constraint_refs": []}
    if menu.get("applied_pantry_constraint_refs", []) != pantry["constraint_refs"]:
        raise ValueError("目标日库存限制已变化或未明确应用，请按当前库存重新核算")
    allowed = {food_catalog.normalize(name) for item in pantry["items"] if item["category"] == "vegetables" for name in item["allowed_foods"]}
    with diet_quantified.SOURCE_PATH.with_name("usda_food_selected_raw.csv").open(newline="", encoding="utf-8") as stream:
        categories = {int(row["fdc_id"]): int(row["food_category_id"]) for row in csv.DictReader(stream)}
    checked = []
    for plan in [menu] + list(menu.get("variants") or []):
        if not plan.get("valid_for_use"):
            continue
        for recipe in plan.get("recipes", []):
            for item in recipe.get("items", []):
                source = item.get("source", {})
                kind = source.get("kind")
                if kind == "official_composition_reference":
                    identifier = source.get("fdc_id")
                    if identifier not in categories:
                        raise ValueError("库存核验缺少官方食物分类，不能忽略未知食材")
                    if categories[identifier] != 11:
                        continue
                    food = next((food for food in diet_quantified.DATA["foods"] if food["fdc_id"] == identifier), None)
                    names = {food_catalog.normalize(name) for name in ([food["name_zh"], *food.get("aliases", [])] if food else [])}
                elif kind == "catalog_reference":
                    # Fixed, verified seasoning references are not fresh-vegetable inventory.
                    verified = {
                        "生抽（通用酱油估算）": "https://www.ars.usda.gov/ARSUserFiles/80400535/Data/SR/SR28/reports/sr28fg16.pdf#page=746",
                        "食盐": "https://www.ars.usda.gov/ARSUserFiles/80400535/Data/SR/SR28/reports/sr28fg02.pdf#page=22",
                        "黑胡椒粉": "https://www.ars.usda.gov/ARSUserFiles/80400535/Data/SR/SR28/reports/sr28fg02.pdf#page=110",
                    }
                    product = food_catalog.product_version(source.get("product_id"), source.get("product_version"))["data"]
                    # Explicit, version-pinned classification from ingredient evidence.
                    if product.get("food_category") == "processed_meat" and product.get("identity_confirmed") and "鸡肉" in product.get("ingredients", ""):
                        continue
                    url = verified.get(product.get("name"))
                    if url and item.get("name") == product["name"] and source.get("url") == url and url in product.get("source_note", ""):
                        continue
                    raise ValueError("库存约束下的新增通用食材须有可核验食物分类，当前来源保持待审核")
                elif kind == "personal_label":
                    product = food_catalog.product_version(source.get("product_id"), source.get("product_version"))["data"]
                    names = {food_catalog.normalize(name) for name in [product["name"], *product.get("aliases", [])]}
                    vegetable_words = ("菜", "椒", "茄", "葱", "瓜", "萝卜", "蘑菇", "笋", "芹")
                    if not any(word in product["name"] + product.get("ingredients", "") for word in vegetable_words):
                        continue
                else:
                    raise ValueError("库存核验缺少可识别食材来源")
                if not names.intersection(allowed):
                    raise ValueError("目标日蔬菜库存不含：" + item["name"])
                checked.append({"item_id": item["item_id"], "name": item["name"], "quantity": item["quantity"]})
    return {"status": "passed", "constraint_refs": deepcopy(pantry["constraint_refs"]), "checked_vegetables": checked}
