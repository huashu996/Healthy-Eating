from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
Module = Literal["diet"]

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=30000, allow_inf_nan=False)

class SettingsPatch(Strict):
    version: int
    timezone: str = "Asia/Shanghai"
    timezone_confirmed: bool = True
    locale: str = "zh-CN"
    reduced_motion: bool = False
    schedule_enabled: bool = False
    daily_time: str = "07:00"
    evening_enabled: bool = False
    evening_time: str = "07:00"
    weekly_enabled: bool = False
    public_sources_enabled: bool = False
    agent_enabled: bool = False
    onboarding_done: bool = True

    @field_validator("timezone")
    @classmethod
    def tz(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError):
            raise ValueError("请选择有效的 IANA 时区")
        return value

    @field_validator("daily_time", "evening_time")
    @classmethod
    def clock(cls, value):
        datetime.strptime(value, "%H:%M")
        return value

class Fact(Strict):
    category: Literal["health"]
    key: str = Field(min_length=1, max_length=100)
    value: str | float | bool
    unit: str = ""
    source: str = "用户填写"
    observed_at: str | None = ""
    sensitivity: Literal["normal", "sensitive"] = "sensitive"
    project_id: str | None = None

    @model_validator(mode="after")
    def metrics(self):
        limits = {"身高": (50, 260, "cm"), "体重": (10, 500, "kg"), "体脂率": (1, 75, "%"), "年龄": (1, 120, "岁")}
        if self.category == "health" and self.key in limits and self.value != "":
            low, high, unit = limits[self.key]
            try:
                valid = low <= float(self.value) <= high
            except (TypeError, ValueError):
                valid = False
            if not valid or self.unit != unit:
                raise ValueError("请核对身体指标范围与单位；未自动修正")
        return self

class FoodProductUse(Strict):
    product_id: str = Field(min_length=1, max_length=100)
    product_version: int = Field(ge=1)
    quantity: float | None = Field(default=None, gt=0, le=10000)
    unit: Literal["g", "ml", "serving"]
    quantity_evidence: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def portion_evidence(self):
        if self.quantity is not None and not self.quantity_evidence.strip():
            raise ValueError("换算份量必须有用户或标签依据")
        return self


class Meal(Strict):
    eaten_at: datetime
    diet_date: date | None = None
    received_at: datetime | None = None
    meal_type: Literal["早餐", "午餐", "晚餐", "练前餐", "练后餐", "加餐"]
    title: str = Field(min_length=1, max_length=200)
    notes: str = ""
    assets: list[str] = Field(default_factory=list, max_length=6)
    status: Literal["pending", "confirmed"] = "pending"
    execution: Literal["planned", "done", "partial", "skipped", "replaced"] = "done"
    portion_low_g: float | None = Field(default=None, ge=0, le=10000)
    portion_high_g: float | None = Field(default=None, ge=0, le=10000)
    oil_g: float | None = Field(default=None, ge=0, le=500)
    eaten_fraction: float = Field(default=1, ge=0, le=1)
    cooking: str = ""
    ingredients: str = ""
    food_group: Literal["unknown", "grains", "vegetables", "fruit", "protein", "dairy", "mixed"] = "unknown"
    kcal_per_100g: float | None = Field(default=None, ge=0, le=1000)
    nutrition_source: str = ""
    nutrition_version: str = ""
    product_refs: list[FoodProductUse] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def ranges(self):
        if self.received_at is not None and self.received_at.tzinfo is None:
            raise ValueError("接收时间必须含时区")
        if self.eaten_at.tzinfo is None:
            raise ValueError("餐食时间必须含时区")
        if self.portion_low_g is not None and self.portion_high_g is not None and self.portion_low_g > self.portion_high_g:
            raise ValueError("份量下限不能大于上限")
        if self.kcal_per_100g is not None and not self.nutrition_source:
            raise ValueError("营养数据必须填写来源")
        return self

class FoodLikes(Strict):
    protein: str = Field(default="", max_length=200)
    fats: str = Field(default="", max_length=200)
    carbs: str = Field(default="", max_length=200)
    fiber: str = Field(default="", max_length=200)
    previous: str = Field(default="", max_length=1000)

class AdoptedNutritionEstimate(Strict):
    """One expressly selected, source-pinned raw home-cooking estimate."""
    product_id: str = Field(min_length=1, max_length=100)
    product_version: int = Field(ge=1)
    source_id: str = Field(min_length=1, max_length=1000)
    application_scope: Literal["home_cooked_raw_ingredient"]
    weight_basis: str = Field(min_length=1, max_length=1000)
    uncertainty_note: str = Field(min_length=1, max_length=2000)

class Preference(Strict):
    rule: str = Field(min_length=1, max_length=2000)
    scope: str = "日常"
    kind: Literal["observed", "like", "try", "dislike", "allergy", "constraint"] = "observed"
    confirmed: bool = False
    support_ids: list[str] = Field(default_factory=list, max_length=30)
    counterexamples: str = ""
    feedback: str = ""
    food_likes: FoodLikes | None = None
    adopted_nutrition_estimate: AdoptedNutritionEstimate | None = None

    @model_validator(mode="after")
    def allergy(self):
        if self.kind in ("allergy", "constraint") and not self.confirmed:
            raise ValueError("过敏与禁忌必须由用户明确确认")
        if self.adopted_nutrition_estimate and (not self.confirmed or self.kind != "observed"):
            raise ValueError("个人选用营养估算须有已确认的专项依据，不从喜好自动推定")
        return self

class Mutation(Strict):
    schema_version: Literal["1.0"] = "1.0"
    version: int | None = None
    data: dict

class AgentOutput(Strict):
    schema_version: Literal["1.0"]
    summary: str = Field(max_length=10000)
    items: list[str] = Field(max_length=20)
    source_ids: list[str] = Field(max_length=100)
    limitations: list[str] = Field(max_length=20)

class Feedback(Strict):
    recommendation_ref: str = Field(min_length=1, max_length=100)
    execution: Literal["done", "partial", "skipped", "replaced"]
    notes: str = Field(default="", max_length=2000)

class ContextRef(Strict):
    id: str
    version: int = Field(ge=1)

class MealAnalysisInput(Strict):
    meal_id: str | None = None
    context_refs: list[ContextRef] = Field(default_factory=list, max_length=30)

class VisibleFood(Strict):
    name: str = Field(max_length=100)
    evidence: str = Field(max_length=300)
    certainty: Literal["clear", "uncertain"]

class NextMeal(Strict):
    title: str = Field(max_length=150)
    foods: list[str] = Field(max_length=8)
    reason: str = Field(max_length=1200)
    caveat: str = Field(max_length=600)
    today_summary: str = Field(default="", max_length=1200)
    additions: list[str] = Field(default_factory=list, max_length=6)

class NutritionRange(Strict):
    low: float = Field(ge=0, le=10000)
    high: float = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def ordered(self):
        if self.low > self.high:
            raise ValueError("营养估算下限不得大于上限")
        return self

class AlcoholServing(Strict):
    """Beverage volume before meal eaten_fraction scaling; ABV is percent, not fraction."""
    name: str = Field(min_length=1, max_length=100)
    beverage_type: Literal["beer", "wine", "spirits", "whisky", "baijiu", "huangjiu", "other"]
    volume_ml: float = Field(ge=0, le=20000, allow_inf_nan=False)
    abv_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    basis: str = Field(min_length=1, max_length=1000)
    abv_basis: str = Field(default="", max_length=500)
    abv_source: Literal["label", "user", "estimated"] = "estimated"

    @model_validator(mode="after")
    def explicit_abv_evidence(self):
        if not self.name.strip() or not self.basis.strip():
            raise ValueError("饮酒份量必须有来源或估量说明")
        if self.abv_percent is not None and not self.abv_basis.strip():
            raise ValueError("明确酒精度必须保存来源；百分数40表示40%")
        if self.abv_percent is None and (self.beverage_type == "other" or self.abv_source != "estimated"):
            raise ValueError("未知酒类需先估计酒精度并说明依据")
        return self


class MealQualityEvidence(Strict):
    """Whole-serving food amounts, scaled by eaten_fraction once; null is unknown."""
    basis: str = Field(min_length=1, max_length=2000)
    confidence: Literal["measured", "label_based", "estimated"]
    covers_entire_meal: bool = False
    supplements_excluded: bool = False
    vegetables_raw_edible_g: NutritionRange | None = None
    fruit_edible_g: NutritionRange | None = None
    whole_grains_mixed_beans_dry_g: NutritionRange | None = None
    fiber_g: NutritionRange | None = None
    saturated_fat_g: NutritionRange | None = None
    sodium_mg: NutritionRange | None = None
    distinct_foods: list[str] | None = Field(default=None, max_length=100)
    alcohol_servings: list[AlcoholServing] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def evidence_is_explicit(self):
        self.basis = self.basis.strip()
        if not self.basis:
            raise ValueError("食物结构估算必须有明确来源与称重/换算口径")
        if self.distinct_foods is not None:
            names = [name.strip() for name in self.distinct_foods]
            if any(not name or len(name) > 100 for name in names):
                raise ValueError("食材多样性须列出明确的食材名称")
            self.distinct_foods = list(dict.fromkeys(names))
        return self


class PhotoNutrition(Strict):
    kcal: NutritionRange | None
    protein_g: NutritionRange | None
    fat_g: NutritionRange | None
    carbs_g: NutritionRange | None
    basis: str = Field(max_length=1000)
    label_values: list["LabelNutrient"] = Field(default_factory=list, max_length=4)

class LabelNutrient(Strict):
    nutrient: Literal["kcal", "protein_g", "fat_g", "carbs_g"]
    value: float = Field(ge=0, le=10000)
    unit: Literal["kcal", "kJ", "g"]
    basis: Literal["meal_total", "per_serving", "per_100g"]
    quantity: float | None = Field(default=None, gt=0, le=10000)
    evidence: str = Field(min_length=1, max_length=500)
    quantity_evidence: str = Field(default="", max_length=500)
    covers_entire_meal: bool = False

    @model_validator(mode="after")
    def label_units(self):
        if (self.nutrient == "kcal" and self.unit == "g") or (self.nutrient != "kcal" and self.unit != "g"):
            raise ValueError("标签营养单位不匹配")
        if self.basis != "meal_total" and self.quantity is not None and not self.quantity_evidence.strip():
            raise ValueError("每份或每百克换算需要实际份量依据")
        return self

class ActivityAssessment(Strict):
    factor: float = Field(ge=1.4, le=2.5)
    basis: str = Field(min_length=1, max_length=1000)

class MultimodalFoodDecision(Strict):
    name: str = Field(min_length=1, max_length=100)
    sources: list[Literal["image", "text", "voice", "label"]] = Field(min_length=1)
    disposition: Literal["included", "excluded"]
    basis: str = Field(min_length=1, max_length=1000)

class MultimodalMealEvidence(Strict):
    full_image_reviewed: bool
    text_is_exhaustive: bool = False
    decisions: list[MultimodalFoodDecision] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_food_decisions(self):
        names = [d.name.strip() for d in self.decisions]
        if any(not n for n in names) or len(names) != len(set(names)):
            raise ValueError("多模态同一食物须合并，不能重复计入")
        if not self.full_image_reviewed and any("image" in d.sources for d in self.decisions):
            raise ValueError("有图片证据须先完成整图检查")
        return self

class MealVisionOutput(AgentOutput):
    multimodal_evidence: MultimodalMealEvidence | None = None
    meal_title: str = Field(max_length=200)
    visible_text: str = Field(max_length=3000)
    foods: list[VisibleFood] = Field(max_length=20)
    next_meal: NextMeal | None = None
    nutrition: PhotoNutrition
    activity_assessment: ActivityAssessment | None = None
    quality_evidence: MealQualityEvidence | None = None

    @model_validator(mode="after")
    def multimodal_coverage(self):
        if self.multimodal_evidence is not None:
            decided = {d.name.strip() for d in self.multimodal_evidence.decisions}
            visible = {f.name.strip() for f in self.foods}
            if not visible.issubset(decided):
                raise ValueError("整图识别食物须说明计入或排除原因，不能因文字未列而遗漏")
        return self

class HealthUpload(Strict):
    title: str = Field(default="体测资料", max_length=200)
    assets: list[str] = Field(min_length=1, max_length=6)
    notes: str = Field(default="", max_length=2000)

class BodyCheckin(Strict):
    source: str = Field(default="", max_length=1000)
    source_id: str = Field(default="", max_length=1000)
    measured_on: date
    weight_kg: float = Field(ge=10, le=500)
    body_fat_pct: float | None = Field(default=None, ge=1, le=75)

class DishRequest(Strict):
    dish: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=1000)
    source_id: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def explicit_request(self):
        self.dish, self.source = self.dish.strip(), self.source.strip()
        if not self.dish or not self.source:
            raise ValueError("按日点菜必须包含菜名和明确来源")
        return self


class PantryConstraint(Strict):
    category: Literal["vegetables"]
    allowed_foods: list[str] = Field(min_length=1, max_length=50)
    source: str = Field(min_length=1, max_length=2000)
    source_id: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def explicit_inventory(self):
        self.source = self.source.strip()
        self.allowed_foods = [name.strip() for name in self.allowed_foods]
        if not self.source or any(not name or len(name) > 200 for name in self.allowed_foods):
            raise ValueError("按日库存须包含食材名称和明确来源")
        if len(set(name.casefold() for name in self.allowed_foods)) != len(self.allowed_foods):
            raise ValueError("按日库存食材不可重复")
        return self


class DietDay(Strict):
    date: date
    exercise: str = Field(default="", max_length=2000)
    finished: bool = False
    training_status: Literal["unknown", "training", "rest"] = "unknown"
    training_source: str = Field(default="", max_length=1000)
    training_source_id: str = Field(default="", max_length=1000)
    dish_requests: list[DishRequest] = Field(default_factory=list, max_length=10)
    pantry_constraints: list[PantryConstraint] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def training_plan_source(self):
        # This is a dated plan, never evidence that exercise was completed.
        if self.training_status != "unknown" and not self.training_source.strip():
            raise ValueError("训练日或休息日计划必须记录明确来源")
        names = [request.dish.casefold() for request in self.dish_requests]
        if len(names) != len(set(names)):
            raise ValueError("同一饮食日点菜不可重复列出同一道菜")
        categories = [constraint.category for constraint in self.pantry_constraints]
        if len(categories) != len(set(categories)):
            raise ValueError("同一饮食日每类库存限制只保存一项")
        return self

class ExtractedFact(Strict):
    key: Literal["年龄", "生理性别", "身高", "体重", "体脂率", "目标", "活动量", "忌口"]
    value: str = Field(max_length=500)
    unit: str = Field(max_length=20)
    evidence: str = Field(max_length=500)

    @model_validator(mode="after")
    def checked_units(self):
        self.unit = {"千克": "kg", "公斤": "kg", "厘米": "cm", "百分比": "%", "年": "岁"}.get(self.unit, self.unit)
        Fact(category="health", key=self.key, value=self.value, unit=self.unit)
        if self.key == "生理性别" and self.value not in ("男", "女"):
            raise ValueError("仅接受报告明确写出的生理性别")
        return self

class HealthVisionOutput(AgentOutput):
    facts: list[ExtractedFact] = Field(max_length=12)

MODELS = {"facts": Fact,"meals": Meal,"diet_preferences": Preference,"feedback": Feedback,"health_uploads": HealthUpload,"body_checkins": BodyCheckin,"diet_days": DietDay}
MODULES = {k: "diet" for k in MODELS}
