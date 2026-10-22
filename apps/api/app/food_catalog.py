"""Private label catalogue; explicit aliases, pinned revisions and offline arithmetic."""
import hashlib
import json
from typing import Literal
import unicodedata

from fastapi import Query
from pydantic import Field, model_validator

from . import config, db, schemas
from .security import SafeError, digest


class LabelImage(schemas.Strict):
    id: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class OtherNutrient(schemas.Strict):
    name: str = Field(min_length=1, max_length=100)
    value: float | None = Field(default=None, ge=0, le=100000)
    unit: str = Field(min_length=1, max_length=30)


class FoodProduct(schemas.Strict):
    name: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=100)
    variant: str | None = Field(default=None, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    identity_confirmed: bool = False
    ingredients: str = Field(default="", max_length=3000)
    food_category: Literal["processed_meat", "seasoning", "other"] | None = None
    basis: Literal["per_100g", "per_100ml", "per_serving"]
    serving_size: float | None = Field(default=None, gt=0, le=10000)
    serving_unit: Literal["g", "ml"] | None = None
    serving_description: str = Field(default="", max_length=500)
    serving_evidence: str = Field(default="", max_length=1000)
    energy: float | None = Field(default=None, ge=0, le=10000)
    energy_unit: Literal["kcal", "kJ"] = "kcal"
    protein_g: float | None = Field(default=None, ge=0, le=10000)
    fat_g: float | None = Field(default=None, ge=0, le=10000)
    carbs_g: float | None = Field(default=None, ge=0, le=10000)
    other_nutrients: list[OtherNutrient] = Field(default_factory=list, max_length=40)
    label_text: str = Field(default="", max_length=10000)
    source_kind: Literal["label_photo", "user_label", "user_report", "generic_reference"]
    source_note: str = Field(min_length=1, max_length=3000)
    source_images: list[LabelImage] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def evidence(self):
        if not self.name.strip() or not self.source_note.strip():
            raise ValueError("产品名和来源不能为空")
        if any(not alias.strip() or len(alias) > 200 for alias in self.aliases):
            raise ValueError("别名不能为空或过长")
        if (self.serving_size is None) != (self.serving_unit is None):
            raise ValueError("每份大小与单位须同时给出")
        if self.serving_size is not None and not self.serving_evidence.strip():
            raise ValueError("每份大小需要标签或用户依据")
        if self.source_kind == "label_photo" and not self.source_images:
            raise ValueError("图片标签来源须引用原图")
        if self.basis == "per_serving" and not self.serving_description.strip():
            raise ValueError("每份标签须保留份的定义；未知克重可留空")
        return self


class ProductWrite(schemas.Strict):
    idempotency_key: str = Field(min_length=8, max_length=250)
    version: int | None = Field(default=None, ge=1)
    data: FoodProduct


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text or "").split()).casefold()


def product_version(identifier, version=None, con=None):
    if con is None:
        with db.connect() as connection:
            return product_version(identifier, version, connection)
    current = db.get_record(identifier, "food_products", con)
    if version is None or version == current["version"]:
        return current
    row = con.execute("SELECT * FROM revisions WHERE record_id=? AND version=?", (identifier, version)).fetchone()
    if not row:
        raise KeyError(identifier)
    revision = db.unpack(row)
    return {**current, "version": revision["version"], "data": revision["data"], "updated_at": revision["created_at"]}


def validate_meal_refs(refs, con=None):
    for ref in refs:
        product_version(ref["product_id"], ref["product_version"], con)


def save(value, identifier=None):
    data = value.data.model_dump(mode="json")
    fingerprint = digest(db.encode({"id": identifier, "version": value.version, "data": data}).encode())
    key = "food-product:request:" + hashlib.sha256(value.idempotency_key.encode()).hexdigest()
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        prior = con.execute("SELECT value FROM runtime WHERE key=?", (key,)).fetchone()
        if prior:
            receipt = json.loads(prior["value"])
            if receipt["fingerprint"] != fingerprint:
                raise db.Conflict("食品库幂等键已用于不同内容")
            return product_version(receipt["id"], receipt["version"], con)
        for ref in data["source_images"]:
            asset = con.execute("SELECT * FROM assets WHERE id=? AND module='diet' AND project_id IS NULL", (ref["id"],)).fetchone()
            if not asset or asset["sha256"] != ref["sha256"]:
                raise SafeError("label_image_changed", "食品标签必须引用当前原图及真实hash", 409)
            path = (config.DATA / "assets" / asset["storage_key"]).resolve()
            if not path.is_relative_to((config.DATA / "assets").resolve()) or not path.is_file() or digest(path.read_bytes()) != ref["sha256"]:
                raise SafeError("label_image_changed", "食品标签原图不可用或已变化", 409)
        stamp = db.now()
        if identifier:
            old = db.get_record(identifier, "food_products", con)
            if value.version != old["version"]:
                raise db.Conflict("请按食品当前版本更新，旧标签版本会保留")
            version = old["version"] + 1
            con.execute("UPDATE records SET data=?,version=?,updated_at=? WHERE id=?", (db.encode(data), version, stamp, identifier))
        else:
            if value.version is not None:
                raise SafeError("invalid_version", "新食品不传版本；更新时指定产品ID和当前版本", 422)
            identifier, version = db.uid(), 1
            con.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                        (identifier, "food_products", "diet", None, version, db.encode(data), stamp, stamp, "live"))
        con.execute("INSERT INTO revisions VALUES(?,?,?,?)", (identifier, version, db.encode(data), stamp))
        con.execute("INSERT INTO runtime VALUES(?,?)", (key, db.encode({"fingerprint": fingerprint, "id": identifier, "version": version})))
        db.audit(con, "food_product.saved", identifier, {"version": version})
        return product_version(identifier, version, con)


def lookup(query="", brand=None):
    rows = db.records("food_products", 10000)["items"]
    term, brand_key = normalize(query), normalize(brand)
    matches, suggestions = [], []
    for row in rows:
        data = row["data"]
        if brand_key and normalize(data.get("brand")) != brand_key:
            continue
        terms = [data["name"], *data.get("aliases", [])]
        exact = [name for name in terms if normalize(name) == term]
        if not term or exact:
            matches.append({**row, "match_evidence": {"method": "browse" if not term else "exact_name_or_alias", "terms": exact}})
        elif any(term in normalize(name) for name in terms):
            suggestions.append({**row, "match_evidence": {"method": "partial_text_only", "terms": []}})
    status = ("browse" if not term else "ambiguous" if len(matches) > 1 else
              "resolved" if len(matches) == 1 and matches[0]["data"]["identity_confirmed"] else
              "needs_confirmation" if matches else "not_found")
    return {"status": status, "query": query, "items": matches, "suggestions": suggestions,
            "calculation_policy": {"priority": "confirmed_personal_label_then_sourced_estimate",
                "fallback": "库中未命中时，主聊天可查可靠食物成分资料，结合实际份量与做法估算；保存确切来源、方法、份量/用油假设及不确定性。未查证不能声称查了数据库，也不能默认为某品牌。",
                "display": "主面板可用估算中点；详情保留范围、来源和可修正假设。", "automatic_lookup": False},
            "notice": "仅按已存名称/别名和品牌匹配；照片由主聊天核对。多项命中、尚未确认产品身份或图片与标签不一致时先确认，不能靠频率猜产品；尚未新增摄入。"}


def calculate(use):
    row = product_version(use.product_id, use.product_version)
    data = row["data"]
    quantity, multiplier = use.quantity, None
    if quantity is not None:
        if data["basis"] == "per_100g" and use.unit == "g" or data["basis"] == "per_100ml" and use.unit == "ml":
            multiplier = quantity / 100
        elif use.unit == "serving" and data["basis"] == "per_serving":
            multiplier = quantity
        elif data.get("serving_size") and data.get("serving_evidence"):
            if use.unit == "serving" and ((data["basis"] == "per_100g" and data["serving_unit"] == "g") or (data["basis"] == "per_100ml" and data["serving_unit"] == "ml")):
                multiplier = quantity * data["serving_size"] / 100
            elif data["basis"] == "per_serving" and use.unit == data["serving_unit"]:
                multiplier = quantity / data["serving_size"]
    values = {"kcal": data["energy"] / (4.184 if data["energy_unit"] == "kJ" else 1) if data["energy"] is not None else None,
              **{key: data[key] for key in ("protein_g", "fat_g", "carbs_g")}}
    nutrition = {key: {"low": round(value * multiplier, 4), "high": round(value * multiplier, 4)} if value is not None and multiplier is not None else None for key, value in values.items()}
    missing = [key for key, value in nutrition.items() if value is None]
    return {"product_ref": use.model_dump(mode="json"), "product": {"id": row["id"], "version": row["version"], "name": data["name"], "brand": data["brand"]},
            "status": "needs_quantity" if multiplier is None else "partial" if missing else "calculated",
            "nutrition": {**nutrition, "basis": f"个人食品库 {row['id']} v{row['version']}；{data['basis']}。" + ("按已确认份量换算。" if multiplier is not None else "缺少可换算份量，暂未计算。") + "未标示值保留为空，未自动计入餐食。"},
            "other_nutrients": [{**n, "value": round(n["value"] * multiplier, 4) if n["value"] is not None and multiplier is not None else None} for n in data["other_nutrients"]],
            "multiplier": multiplier, "missing_nutrients": missing, "source_images": data["source_images"],
            "provenance": {"source_kind": data["source_kind"], "source_note": data["source_note"],
                           "is_label_value": data["source_kind"] in ("label_photo", "user_label"),
                           "identity_confirmed": data["identity_confirmed"]},
            "limitations": ["产品匹配与份量需要用户或清晰标签依据；g与ml不互换，勺重/片重未知不猜。", "计算只返回这一产品的贡献，不代表整餐，也不新增或重写摄入。"]}


def register(app):
    @app.get("/api/v1/diet/food-products")
    def search_products(query: str = Query(default="", max_length=200), brand: str | None = Query(default=None, max_length=100)):
        return lookup(query, brand)

    @app.post("/api/v1/diet/food-products", status_code=201)
    def create_product(value: ProductWrite):
        return save(value)

    @app.post("/api/v1/diet/food-products/calculate")
    def calculate_product(value: schemas.FoodProductUse):
        return calculate(value)

    @app.get("/api/v1/diet/food-products/{identifier}/versions")
    def versions(identifier: str):
        product_version(identifier)
        with db.connect() as con:
            return {"items": [db.unpack(r) for r in con.execute("SELECT * FROM revisions WHERE record_id=? ORDER BY version DESC", (identifier,))]}

    @app.get("/api/v1/diet/food-products/{identifier}")
    def get_product(identifier: str, version: int | None = Query(default=None, ge=1)):
        return product_version(identifier, version)

    @app.patch("/api/v1/diet/food-products/{identifier}")
    def update_product(identifier: str, value: ProductWrite):
        return save(value, identifier)
