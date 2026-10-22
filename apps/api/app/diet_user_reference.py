"""Narrow opt-in for a user's explicitly adopted estimate, never a label."""
from . import db, food_catalog, schemas

KIND = "user_adopted_estimate"


def resolve(source):
    if source.get("kind") != KIND or source.get("source_kind") != "user_report":
        raise ValueError("个人选用估算必须保留user_report真实来源")
    preference = db.get_record(source.get("preference_id"), "diet_preferences")
    if preference["version"] != source.get("preference_version"):
        raise db.Conflict("个人选用估算依据已变化")
    data = preference["data"]
    adoption = data.get("adopted_nutrition_estimate")
    if not data.get("confirmed") or data.get("kind") != "observed" or not adoption:
        raise ValueError("没有个人明确选用此营养估算的专项依据")
    adoption = schemas.AdoptedNutritionEstimate.model_validate(adoption).model_dump()
    if any(source.get(k) != adoption[k] for k in ("product_id", "product_version", "application_scope", "source_id")):
        raise ValueError("估算产品版本、个人选用来源或适用范围不匹配")
    row = food_catalog.product_version(adoption["product_id"], adoption["product_version"])
    product = row["data"]
    if (product.get("source_kind") != "user_report" or product.get("identity_confirmed") is not True
            or product.get("basis") != "per_100g"
            or any(product.get(k) is None for k in ("energy", "protein_g", "fat_g", "carbs_g"))):
        raise ValueError("只有身份明确、每100g完整且固定版本的已选估算可以用于菜单")
    if source.get("source_note") != product["source_note"]:
        raise ValueError("不得改写或提升个人估算的原始来源性质")
    return row, adoption


def validate_item(item):
    row, adoption = resolve(item.get("source", {}))
    product = row["data"]
    if item.get("name") not in [product["name"], *product.get("aliases", [])]:
        raise ValueError("个人估算食材名称不匹配")
    if item.get("weight_basis") != adoption["weight_basis"]:
        raise ValueError("个人估算只适用于已批准的自做生可食重，不得套熟重或外食")
    if not {product["source_note"], adoption["uncertainty_note"]} <= set(item.get("assumptions", [])):
        raise ValueError("个人估算必须保留来源与不确定性说明")
    return {"kcal": product["energy"] / (4.184 if product["energy_unit"] == "kJ" else 1),
            **{k: product[k] for k in ("protein_g", "fat_g", "carbs_g")}}
