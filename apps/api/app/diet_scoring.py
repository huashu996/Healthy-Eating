"""Conservative, local diet-reasonableness reference; not a validated health index.

Guidelines inform the domains. Weights and coarse point bands are product choices.
User-attested complete diaries retain all 100 points; photo estimates are not penalties.
"""
from math import isfinite, isclose
from decimal import Decimal
from copy import deepcopy
from datetime import date, datetime

VERSION = "diet-quality-v8-continuous-tolerance"
V7_VERSION = "diet-quality-v7-target-bands"
LEGACY_VERSION = "diet-quality-v6-alcohol-dose"
V7_METHOD = ("饮食目标执行与结构参考（固定100分）：热量25、蛋白质20、脂肪15、碳水10、蔬菜/水果/全谷杂豆各10。"
          "四项营养均与该日目标比较：90%–110%（含边界）满分，其余75%–130%（含边界）得该项60%，之外0分。"
          "按用户完整记录约定，未出现的食物类别按未吃计；照片中可见食物由AI结合叙述估量，未称重不扣分。"
          "七项直接相加，再按纯酒精每3克扣1分、最高扣30分；不剔除维度、不归一。"
          "偏离个人目标的扣分不等于医学上的有害或不足；原适用性和数据复核仍保留。"
          "这是软件启发式参考，不是临床验证的健康指数；估算量不等于实测，也不能诊断营养缺乏。")

SOURCES = [
    {"id":"cdc-ethanol-density", "title":"CDC/NIOSH：Ethanol density", "url":"https://www.cdc.gov/niosh/docs/2003-154/pdfs/1400.pdf", "summary":"20°C乙醇密度0.789 g/mL；纯酒精克数=饮用毫升×ABV百分数÷100×密度。"},
    {"id":"niaaa-standard-drink", "title":"NIAAA：What is a standard drink", "url":"https://www.niaaa.nih.gov/alcohols-effects-health/what-standard-drink", "summary":"酒类容积和酒精度共同决定纯酒精量；美国一标准杯约14克，不是安全阈值。"},
    {"id":"who-alcohol", "title":"WHO：Alcohol", "url":"https://www.who.int/news-room/fact-sheets/detail/alcohol", "summary":"酒精消费存在健康风险，不能由宏量达标抵消；本软件扣分并非WHO评分公式。"},
    {"id": "canada-dri", "title": "Health Canada：成人宏量营养素参考", "url": "https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/dietary-reference-intakes/tables/reference-values-macronutrients.html",
     "summary": "一般成人蛋白RDA为0.8克/公斤，蛋白供能参考10–35%、脂肪20–35%；未设蛋白UL不等于已证实任意高摄入长期安全。"},
    {"id": "nih-ods-exercise", "title": "NIH ODS：运动营养", "url": "https://ods.od.nih.gov/factsheets/ExerciseAndAthleticPerformance-HealthProfessional/",
     "summary": "运动者蛋白通常1.2–2.0克/公斤/日、脂肪20–35%供能；限制能量或高强度时部分运动者可能需要更多蛋白，2.0不是毒性上限。"},
    {"id": "cns-vegetables-fruit-2022", "title": "中国居民膳食指南2022：蔬菜水果", "url": "https://www.cnsoc.org/yyzvideo/552200206.html",
     "summary": "一般成人蔬菜至少300克，水果200–350克；不能只凭出现食物名称认定份量达标。"},
    {"id": "cns-grains-2022", "title": "中国居民膳食指南2022：食物多样", "url": "https://www.cnsoc.org/activitykit2/6522002010.html",
     "summary": "全谷物和杂豆50–150克；比较时须统一原料干重口径，食物多样性不能只按菜名猜测。"},
    {"id": "who-healthy-diet", "title": "WHO：健康饮食", "url": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet",
     "summary": "能量平衡、脂肪质量、天然食物纤维和多样性均重要；一般成人天然膳食纤维至少25克/日。"},
    {"id": "nih-supplements", "title": "NIH ODS：膳食补充剂", "url": "https://ods.od.nih.gov/factsheets/WYNTK-Consumer/",
     "summary": "补充剂不能代替多样的完整食物；营养标签可计入宏量营养，但不能补作蔬果全谷的食物份量。"},
]
V7_RULES = {
    "energy": {"maximum": 25, "full_reference_ratio": [0.90, 1.10], "partial_reference_ratio": [0.75, 1.30], "partial_points": 15},
    "protein": {"maximum": 20, "full_reference_ratio": [0.90, 1.10], "partial_reference_ratio": [0.75, 1.30], "partial_points": 12,
                "training_reference_g_per_kg": [1.2, 2.0], "general_reference_g_per_kg": [0.8, 2.0], "max_energy_fraction": 0.35},
    "fat": {"maximum": 15, "full_reference_ratio": [0.90, 1.10], "partial_reference_ratio": [0.75, 1.30], "partial_points": 9,
            "review_energy_fraction": [0.15, 0.40]},
    "carbs": {"maximum": 10, "full_reference_ratio": [0.90, 1.10], "partial_reference_ratio": [0.75, 1.30], "partial_points": 6},
    "structure": {"vegetables_raw_edible_g": 300, "fruit_edible_g": 200, "whole_grains_mixed_beans_dry_g": 50,
                  "each_maximum": 10, "formula": "min(10, 10 * estimated_intake_g / reference_g)", "component_decimals": 1},
    "severe_domain_cap": 79,
    "unweighed_food_penalty": 0,
    "alcohol": {"density_g_per_ml": 0.789, "grams_per_point": 3, "maximum_deduction": 30, "decimals": 1,
                "formula": "min(30, total_ethanol_g / 3)", "rounding": "round daily deduction once to 1 decimal; final score to nearest integer",
                "abv_defaults_percent": {"beer": 5, "wine": 12, "spirits": 40, "whisky": 40, "baijiu": 52, "huangjiu": 15},
                "notice": "软件启发式权重，不是医学风险百分比；不设安全饮酒量，封顶不是风险封顶。"},
    "normalization": "none; fixed seven-domain total of 100 minus recorded risks",
    "diary_policy": "user_attested_complete_records; unreported food absent; observed food requires measured or photo-estimated amount; empty day remains unrecorded",
    "protein_individual_review_g_per_kg": 3,
    "macro_energy_consistency_tolerance": {"relative": .25, "absolute_kcal": 150},
    "uncertainty": "四项营养区间跨越明显偏离目标分档或原健康复核边界时提示复核；食物组用有依据的照片估量中点连续计分，不以未称重或估算身份扣分。",
    "known_quality_review": "有完整证据时，天然纤维低于25克、饱和脂肪超过10%供能或钠超过2000毫克，则暂停综合分并列出参考提示；不是疾病判断。",
    "notice": "四项目标分档、权重、明显偏离封顶是用户选择的软件规则，不是指南给出的评分公式或医学安全界线；热量不冒充实测消耗。",
}
RULES = deepcopy(V7_RULES)
RULES["carbs"]["maximum"] = 15
for _key in ("energy", "protein", "fat", "carbs"):
    RULES[_key].update(full_reference_ratio=[.95, 1.05], zero_reference_ratio=[.60, 1.40],
                       full_deviation=.05, zero_deviation=.40,
                       formula="maximum * max(0, min(1, (0.40 - abs(intake / target - 1)) / 0.35))")
    del RULES[_key]["partial_reference_ratio"]
    del RULES[_key]["partial_points"]
del RULES["severe_domain_cap"]
RULES["rounding"] = "retain component precision; round only display values and final integer total"
RULES["structure"].update(full_reference_ratio=1, zero_reference_ratio=0,
                          formula="maximum * max(0, min(1, intake / reference))",
                          maxima={"vegetables_raw_edible_g": 10, "fruit_edible_g": 10, "whole_grains_mixed_beans_dry_g": 5},
                          excess_penalty=False, component_decimals="display_only")
del RULES["structure"]["each_maximum"]
RULES["uncertainty"] = "营养区间跨零分边界或原适用性复核边界时保留复核；合格估算层按该版本中点连续计分。"
RULES["notice"] = "目标容差、连续扣分及权重是用户选择的软件规则，不是医学安全界线；无79分额外封顶。"
METHOD = ("饮食目标执行与结构参考（固定100分）：热量25、蛋白质20、脂肪15、碳水15、蔬菜10、水果10、全谷杂豆5。"
          "四项营养偏离该日目标不超过5%满分；超过5%后连续线性扣分，偏差达到40%该项0分。"
          "蔬菜/水果/全谷杂豆保留300/200/50克推荐参考，少多少比例就扣该项多少比例，吃够或超过满分，没吃0分。"
          "七项直接相加，再按纯酒精每3克扣1分、最高扣30分；不剔除维度、不归一、不另设79分封顶。"
          "未称重不扣分；原适用性和资料保护保留。软件启发式参考，不是临床验证的健康指数。")


def rules_for_version(version):
    if version == VERSION:
        return RULES
    if version == V7_VERSION:
        return V7_RULES
    raise ValueError("Unsupported scoring calculation version")


def version_for_date(diet_date):
    """Select by diet date, never run time; saved readback uses its own version."""
    from . import diet_policy
    selected = date.fromisoformat(str(diet_date))
    policy = diet_policy.get_policy()["scoring_evidence"]
    if policy["version"] == V7_VERSION:
        return V7_VERSION
    if policy["version"] != VERSION:
        raise ValueError("Unsupported scoring policy version")
    effective = date.fromisoformat(policy["effective_diet_date"])
    return VERSION if selected >= effective else V7_VERSION


def food_maximum(key, *, version=VERSION):
    rules = rules_for_version(version)["structure"]
    return rules["each_maximum"] if version == V7_VERSION else rules["maxima"][key]


def food_points(intake, key, *, version=VERSION):
    rules = rules_for_version(version)
    reference = rules["structure"][key]
    if version == V7_VERSION:
        return round(min(10, 10 * intake / reference), 1)
    ratio = max(Decimal(0), min(Decimal(1), Decimal(str(intake)) / Decimal(str(reference))))
    return float(Decimal(food_maximum(key, version=version)) * ratio)


def continuous_points(deviation, maximum):
    # Decimal boundaries avoid introducing a second, display-rounded threshold.
    for boundary in (Decimal(".05"), Decimal(".40")):
        if isclose(float(deviation), float(boundary), rel_tol=1e-12, abs_tol=1e-12):
            deviation = boundary
    factor = max(Decimal(0), min(Decimal(1), (Decimal(".40") - deviation) / Decimal(".35")))
    return float(Decimal(maximum) * factor)

MACROS = ("kcal", "protein_g", "fat_g", "carbs_g")
CORE_FOODS = ("vegetables_raw_edible_g", "fruit_edible_g", "whole_grains_mixed_beans_dry_g")
OPTIONAL = ("fiber_g", "saturated_fat_g", "sodium_mg")
LABELS = dict(zip(CORE_FOODS, ("蔬菜", "水果", "全谷物及杂豆")))
TARGET_PARTS = (("energy", "kcal", "热量目标", "kcal"), ("protein", "protein_g", "蛋白质目标", "g"),
                ("fat", "fat_g", "脂肪目标", "g"), ("carbs", "carbs_g", "碳水目标", "g"))


def target_points(amount, target, key, *, version=VERSION):
    """Inclusive decimal bands, with only machine-scale summation noise snapped.

    Meal totals are floats upstream. The 1e-12 relative/1e-9 absolute tolerance
    prevents a sum such as 1979.9999999999998 from missing a 1980 boundary.
    It is not an additional nutritional tolerance or display rounding.
    """
    value, reference = Decimal(str(amount)), Decimal(str(target))
    rule = rules_for_version(version)[key]
    if version == VERSION:
        return continuous_points(abs(value / reference - 1), rule["maximum"])
    low, high = (Decimal(str(v)) * reference for v in rule["full_reference_ratio"])
    partial_low, partial_high = (Decimal(str(v)) * reference for v in rule["partial_reference_ratio"])
    def within(lower, upper):
        return ((lower <= value or isclose(float(value), float(lower), rel_tol=1e-12, abs_tol=1e-9))
                and (value <= upper or isclose(float(value), float(upper), rel_tol=1e-12, abs_tol=1e-9)))
    return rule["maximum"] if within(low, high) else rule["partial_points"] if within(partial_low, partial_high) else 0


def saved_version_supported(snapshot):
    """Known complete v6 snapshots remain historical evidence, never recomputed.

    A version label alone cannot pass a legacy record as a usable snapshot.
    Meal/analysis identity and readiness validation remain with the read models.
    """
    if snapshot.get("score_version") in (VERSION, V7_VERSION):
        return True
    if (snapshot.get("score_version") != LEGACY_VERSION or not isinstance(snapshot.get("score_method"), str)
            or not snapshot["score_method"].strip()):
        return False
    rules = snapshot.get("score_rules")
    required_rules = {
        "energy": {"maximum": 25, "full_reference_ratio": [.85, 1.15], "partial_reference_ratio": [.75, 1.3], "partial_points": 15},
        "protein": {"maximum": 25, "training_reference_g_per_kg": [1.2, 2.0], "general_reference_g_per_kg": [.8, 2.0], "max_energy_fraction": .35},
        "fat": {"maximum": 20, "full_energy_fraction": [.2, .35], "partial_energy_fraction": [.15, .4], "partial_points": 10},
        "structure": {"vegetables_raw_edible_g": 300, "fruit_edible_g": 200, "whole_grains_mixed_beans_dry_g": 50, "each_maximum": 10},
        "alcohol": {"density_g_per_ml": .789, "grams_per_point": 3, "maximum_deduction": 30},
    }
    if not isinstance(rules, dict) or any(not isinstance(rules.get(key), dict)
            or any(rules[key].get(field) != value for field, value in required.items())
            for key, required in required_rules.items()):
        return False
    expected = {"energy": 25, "protein": 25, "fat": 20, **{key: 10 for key in CORE_FOODS}}
    parts = snapshot.get("components")
    if not isinstance(parts, list) or any(not isinstance(p, dict) for p in parts):
        return False
    if any(not number(p.get("maximum")) or not isinstance(p.get("reason"), str) or not p["reason"].strip()
            or p.get("status") != "assessed" for p in parts):
        return False
    if any(not number(p.get("points")) or p["points"] > p["maximum"] for p in parts if p["maximum"] > 0):
        return False
    risks = [p for p in parts if p["maximum"] == 0]
    if len(risks) > 1 or any(p.get("key") != "alcohol" or not number(-p.get("points", 1))
                            or not -30 <= p["points"] <= 0 for p in risks if isinstance(p.get("points"), (int, float))):
        return False
    if any(isinstance(p.get("points"), bool) or not isinstance(p.get("points"), (int, float)) for p in risks):
        return False
    actual = {p.get("key"): p.get("maximum") for p in parts if p.get("maximum", 0) > 0}
    return (actual == expected and len([p for p in parts if p.get("maximum", 0) > 0]) == len(expected)
            and snapshot.get("score_maximum") == 100 and snapshot.get("score_scope") == "recorded_full")


def historical_override_supported(snapshot):
    """Project only a non-sensitive marker after checking source correction audit."""
    audit = snapshot.get("score_policy_override")
    if (snapshot.get("score_version") != VERSION or not isinstance(audit, dict)
            or audit.get("kind") != "explicit_historical_revision" or audit.get("score_version") != VERSION
            or audit.get("previous_score_version") not in (VERSION, V7_VERSION, LEGACY_VERSION)
            or not isinstance(audit.get("source_id"), str) or not audit["source_id"].strip()
            or not isinstance(audit.get("reason"), str) or len(audit["reason"].strip()) < 10
            or audit.get("original_target") != snapshot.get("target")
            or audit.get("original_context") != snapshot.get("score_context")
            or not isinstance(snapshot.get("target"), dict)
            or any(not number(snapshot["target"].get(k), positive=True) for k in MACROS)):
        return False
    try:
        return datetime.fromisoformat(audit["created_at"].replace("Z", "+00:00")).utcoffset() is not None
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def number(value, *, positive=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and isfinite(value) and (value > 0 if positive else value >= 0))


def valid_range(value):
    return (isinstance(value, dict) and number(value.get("low")) and number(value.get("high"))
            and value["low"] <= value["high"])


def midpoint(value):
    return (value["low"] + value["high"]) / 2


def alcohol_dose(serving, fraction=1):
    """Resolve explicit label/user ABV first; retain common-type estimate otherwise."""
    if not isinstance(serving, dict) or not number(fraction, positive=True) or fraction > 1:
        return None
    volume = serving.get("volume_ml")
    abv = serving.get("abv_percent")
    assumed = abv is None
    if assumed:
        abv = RULES["alcohol"]["abv_defaults_percent"].get(serving.get("beverage_type"))
    if not number(volume) or volume > 20000 or not number(abv) or abv > 100 or not str(serving.get("basis") or "").strip():
        return None
    if not assumed and not str(serving.get("abv_basis") or "").strip():
        return None
    actual_ml = volume * fraction
    return {"name": serving.get("name", "酒"), "volume_ml": actual_ml, "abv_percent": abv,
            "ethanol_g": actual_ml * abv / 100 * RULES["alcohol"]["density_g_per_ml"],
            "basis": serving["basis"], "abv_source": "estimated" if assumed else serving.get("abv_source", "estimated"),
            "abv_basis": f"按{serving.get('beverage_type')}常见酒精度{abv:g}%估算，非瓶身核验" if assumed else serving["abv_basis"],
            "eaten_fraction": fraction}


def alcohol_penalty(ethanol_g):
    if not number(ethanol_g):
        raise ValueError("纯酒精量须为非负有限克数")
    return round(min(RULES["alcohol"]["maximum_deduction"], ethanol_g / RULES["alcohol"]["grams_per_point"]), 1)


def aggregate_quality(entries):
    """Each entry is the current analysis and the actual fraction of that meal.

    Explicit zero needs whole-meal coverage just as a positive amount does.
    No guessing from food names, descriptions, plans, or supplementation.
    """
    totals = {key: None for key in (*CORE_FOODS, *OPTIONAL)}
    evidence, distinct_foods, all_diversity_known = [], set(), bool(entries)
    observations = {key: [] for key in CORE_FOODS}
    alcohol, alcohol_doses, alcohol_missing = [], [], []
    # Classify only explicit, clear ingredient identifications, never free text or uncertain guesses.
    lexicon = {
      "vegetables_raw_edible_g": ("生菜", "叶菜", "番茄", "西红柿", "洋葱", "白菜", "娃娃菜", "西葫芦", "菠菜", "西兰花", "胡萝卜", "辣椒"),
      "fruit_edible_g": ("苹果", "香蕉", "蓝莓", "草莓", "莓果", "桑葚", "黑莓", "橙子", "猕猴桃", "梨", "葡萄"),
      "whole_grains_mixed_beans_dry_g": ("全麦", "全谷", "燕麦", "糙米", "红豆", "绿豆", "杂豆"),
    }
    unresolved = []
    partial_meal_groups = []
    for analysis, fraction in entries:
        present = set()
        if not number(fraction, positive=True) or fraction > 1:
            unresolved.extend(CORE_FOODS)
            continue
        for food in analysis.get("foods") or []:
            if not isinstance(food, dict):
                continue
            name = str(food.get("name") or "")
            for key, words in lexicon.items():
                if any(w in name for w in words) and not any(w in name for w in ("果汁", "果干", "味", "粉", "酱", "酒")):
                    present.add(key)
                    observations[key].append({"name": name, "basis": food.get("evidence", "需核对餐图"), "source_ids": analysis.get("source_ids", [])})
            if food.get("certainty") == "clear" and food.get("evidence") and any(w in name for w in ("威士忌", "啤酒", "葡萄酒", "白酒", "黄酒", "伏特加")) and "无酒精" not in name:
                alcohol.append({"name": name, "basis": food["evidence"], "source_ids": analysis.get("source_ids", [])})
        quality = analysis.get("quality_evidence") or {}
        servings = quality.get("alcohol_servings") or []
        observed_alcohol = [f for f in analysis.get("foods") or [] if isinstance(f, dict) and f.get("certainty") == "clear"
            and any(w in str(f.get("name", "")) for w in ("威士忌", "啤酒", "葡萄酒", "白酒", "黄酒", "伏特加")) and "无酒精" not in str(f.get("name", ""))]
        if observed_alcohol and not servings:
            alcohol_missing.append("已识别饮酒，需由AI补齐饮用毫升与酒精度估计及依据，不按未知当0")
        for serving in servings:
            dose = alcohol_dose(serving, fraction)
            if dose is None:
                alcohol_missing.append("饮酒毫升或酒精度数据无效，需核对")
            else:
                alcohol_doses.append(dose)

        eligible = (quality.get("covers_entire_meal") is True and quality.get("supplements_excluded") is True
                    and quality.get("confidence") in ("measured", "label_based", "estimated")
                    and bool(str(quality.get("basis") or "").strip()))
        if (quality.get("covers_entire_meal") is False
                and quality.get("confidence") in ("measured", "label_based", "estimated")
                and str(quality.get("basis") or "").strip()
                and analysis.get("source_ids")):
            for key in CORE_FOODS:
                if key in present or quality.get(key) is not None:
                    partial_meal_groups.append({"key": key, "source_ids": analysis["source_ids"],
                                                "basis": quality["basis"]})
        if eligible:
            evidence.append({"basis": quality["basis"], "confidence": quality["confidence"], "eaten_fraction": fraction})
        foods = quality.get("distinct_foods") if eligible else None
        if not isinstance(foods, list) or not foods:
            all_diversity_known = False
        else:
            distinct_foods.update(str(name).strip().casefold() for name in foods if str(name).strip())
        for key in totals:
            value = quality.get(key)
            if not (eligible and valid_range(value)):
                if key not in CORE_FOODS:
                    continue
                if key in present or value is not None:
                    unresolved.append(key)
                    continue
                value = {"low": 0, "high": 0}  # Explicit complete-diary convention, absent food group.
            total = totals[key] or {"low": 0, "high": 0, "coverage": 0}
            for side in ("low", "high"):
                total[side] += value[side] * fraction
            total["coverage"] += 1
            totals[key] = total
    return {"totals": totals, "partial_meal_groups": partial_meal_groups, "unresolved_portions": sorted(set(unresolved)), "evidence": evidence, "observations": observations, "recorded_alcohol": alcohol, "alcohol_doses": alcohol_doses, "alcohol_missing": alcohol_missing,
            "ethanol_g": sum(d["ethanol_g"] for d in alcohol_doses),
            "distinct_foods": sorted(distinct_foods) if all_diversity_known else None}


def score(totals, target, meals, analyzed, finished, *, context=None, quality=None, version=None, diet_date=None):
    selected = version_for_date(diet_date) if diet_date is not None else VERSION
    if version is not None:
        if diet_date is not None and version != selected:
            raise ValueError("Scoring version does not match the diet date policy")
        selected = version
    rules = rules_for_version(selected)
    legacy = selected == V7_VERSION
    context, quality = context or {}, quality or {}
    parts, missing, food_missing, limits = [], [], [], [
        "单日估算只反映已记录饮食的部分合理性，不能诊断营养缺乏、疾病或长期健康。",
        "能量参考已经包含目标调整；低于参考不额外奖励，也不建议挨饿补偿。",
        "分数不包含全部微量营养素、食物安全和个人疾病管理。",
        "酒精原已计入餐食能量，本评分不重复加热量。按纯酒精量递增扣分是软件权重，不是医学风险换算；少量也非无风险，扣分封顶不表示健康风险封顶。",
    ]
    result = {"score": None, "score_maximum": None, "score_coverage_pct": 0, "score_scope": "unavailable", "components": parts, "score_version": selected, "score_method": V7_METHOD if legacy else METHOD,
              "score_evidence_sources": [dict(s) for s in SOURCES], "score_rules": deepcopy(rules),
              "score_limitations": limits, "score_readiness": {"status": "insufficient_data", "missing": missing},
              "score_quality_evidence": quality, "score_context": dict(context)}

    def done(state, status="insufficient_data"):
        result["state"] = state
        result["score_readiness"]["status"] = status
        return result

    def part(key, name, maximum, points, reason, intake=None, target=None, unit=None):
        row = {"key": key, "name": name, "maximum": maximum, "points": points, "reason": reason,
               "status": "unknown" if points is None else "assessed"}
        if intake is not None:
            row["intake"] = round(intake, 1)
        if target is not None:
            row["target"] = target
        if unit:
            row["unit"] = unit
        parts.append(row)

    if not meals:
        missing.append("没有实际已吃记录")
        return done("未记录", "unrecorded")
    if not isinstance(target, dict) or any(not number(target.get(k), positive=True) for k in MACROS):
        missing.append("该饮食日完整且适用的参考目标")
        return done("待参考量")
    if analyzed != meals or any(not valid_range(totals.get(k)) or totals[k].get("coverage") != meals for k in MACROS):
        missing.append("所有实际餐食的完整热量、蛋白质、脂肪和碳水分析")
        return done("待补齐")
    if not finished:
        limits.append("按用户完整记录约定评价：未发送且照片未见的食物按未吃；照片可见食物按识别估量。")
    amount = {k: midpoint(totals[k]) for k in MACROS}
    if not number(amount["kcal"], positive=True):
        missing.append("全天能量为零，无法评估供能比例，需复核记录")
        return done("待复核")
    missing.extend(quality.get("alcohol_missing") or [])
    ethanol_g = quality.get("ethanol_g", 0)
    # Reconciliation only: alcohol calories already in meal kcal, never added again to intake.
    macro_energy = amount["protein_g"] * 4 + amount["fat_g"] * 9 + amount["carbs_g"] * 4 + ethanol_g * 7
    if abs(macro_energy - amount["kcal"]) > max(150, amount["kcal"] * .25):
        missing.append("总能量与三大营养素供能明显不一致，需核对标签/份量，不能直接合成分数")
    if any(totals[k]["low"] != totals[k]["high"] for k in MACROS):
        limits.append("营养含估算区间；分项使用区间中点，整数分不代表测量精度，实际可能跨分档。")
    for key, nutrient, label, unit in TARGET_PARTS:
        low, high = totals[nutrient]["low"] / target[nutrient], totals[nutrient]["high"] / target[nutrient]
        lower, upper = rules[key]["partial_reference_ratio" if legacy else "zero_reference_ratio"]
        if (low < lower <= high and not isclose(low, lower, rel_tol=1e-12, abs_tol=1e-12)
                or low <= upper < high and not isclose(high, upper, rel_tol=1e-12, abs_tol=1e-12)):
            missing.append(label + ("估算范围跨越明显偏离目标分档，需收窄估算依据" if legacy else "估算范围跨越连续评分零分界线，需保留区间复核"))
        rule = rules[key]
        explanation = (f"目标90%–110%（含边界）给{rule['maximum']}分，其余75%–130%（含边界）给{rule['partial_points']}分，之外0分。" if legacy else
                       f"目标95%–105%（含边界）给{rule['maximum']}分，偏差5%至40%线性扣分，偏差40%及以上0分。")
        part(key, label, rule["maximum"], target_points(amount[nutrient], target[nutrient], key, version=selected),
             f"{label}：约{amount[nutrient]:g}{'千卡' if unit == 'kcal' else '克'}，该日目标{target[nutrient]:g}{'千卡' if unit == 'kcal' else '克'}；"
             + explanation + "只评价目标执行，偏离不等于医学上的有害或不足。",
             amount[nutrient], target[nutrient], unit)
    # Retain existing applicability/health review independently of target points.
    # A review can pause the total, but never deduct an in-band macro component.
    weight = context.get("weight_kg")
    if context.get("applicable") is not True or not number(weight, positive=True) or not isinstance(context.get("training"), bool):
        missing.append("该日已存档的成人适用性、体重及运动背景；不使用今天的资料回填")
    else:
        lower = 1.2 if context["training"] else .8
        per_kg, protein_energy = amount["protein_g"] / weight, amount["protein_g"] * 4 / amount["kcal"]
        if totals["protein_g"]["low"] / weight < lower * .75 <= totals["protein_g"]["high"] / weight:
            missing.append("蛋白估算范围跨越原适用性偏低复核界线，需收窄估算依据")
        if totals["protein_g"]["low"] / weight <= 3 < totals["protein_g"]["high"] / weight:
            missing.append("蛋白估算范围跨越个别复核界线，需收窄估算依据")
        if totals["kcal"]["low"] > 0:
            protein_share_low = totals["protein_g"]["low"] * 4 / totals["kcal"]["high"]
            protein_share_high = totals["protein_g"]["high"] * 4 / totals["kcal"]["low"]
            if protein_share_low <= .35 < protein_share_high:
                missing.append("蛋白供能估算范围跨越一般参考上界，需结合背景复核")
        if protein_energy > .35 or per_kg > 3:
            missing.append("蛋白摄入超出当前一般参考的适用范围，需结合训练/健康背景复核；不据此诊断有害，目标分不替代医学评价")
        if per_kg > 2:
            limits.append("蛋白超过一般1.2–2.0克/公斤运动参考；限制能量/高强度可能需要更多，不能据此判有害，需结合背景复核。")
    fat_fraction = amount["fat_g"] * 9 / amount["kcal"]
    if totals["kcal"]["low"] <= 0:
        missing.append("能量估算下限为零，不能可靠计算脂肪供能范围")
    else:
        fat_low = totals["fat_g"]["low"] * 9 / totals["kcal"]["high"]
        fat_high = totals["fat_g"]["high"] * 9 / totals["kcal"]["low"]
        if fat_low < .15 <= fat_high or fat_low <= .40 < fat_high:
            missing.append("脂肪供能估算范围跨越原复核界线，需复核份量/用油")
    limits.append(f"脂肪约占已记录能量{fat_fraction * 100:.1f}%；供能比例保留作背景，脂肪分按该日克数目标评分，不能据总脂肪判断脂肪质量。")
    evidence_totals = quality.get("totals") or {}
    for key in CORE_FOODS:
        value, reference = evidence_totals.get(key), rules["structure"][key]
        maximum = food_maximum(key, version=selected)
        if not valid_range(value) or value.get("coverage") != meals:
            observed = (quality.get("observations") or {}).get(key) or []
            if observed or key in quality.get("unresolved_portions", []):
                # Estimation belongs to dot's image review, not a name-to-grams heuristic.
                missing.append(LABELS[key] + "需由AI完成已发照片的份量估算；不因未称重扣分")
                part(key, LABELS[key], maximum, None, "已出现的食物需按照片估量后计算，不给未量化罚分。")
                continue
            # This user's explicit complete-diary convention covers absent food categories,
            # not unknown micronutrients or wholly empty days (handled above).
            value = {"low": 0, "high": 0, "coverage": meals}
        intake = midpoint(value)
        points = food_points(intake, key, version=selected)
        basis = "可食原重" if key == "vegetables_raw_edible_g" else "可食部重" if key == "fruit_edible_g" else "原料干重，熟重须有换算依据"
        explanation = ("按摄入÷参考×10计算，最多10分。" if legacy else
                       f"按摄入÷参考×{maximum}计分，少多少比例就扣该项多少比例；吃够或超过得{maximum}分，没吃0分。推荐量不变。")
        part(key, LABELS[key], maximum, points,
             f"约{intake:.0f}克（{basis}），参考{reference}克；" + explanation + "只评价本日记录，不诊断人体缺乏。",
             intake, reference, "g")
        if value["low"] != value["high"]:
            limits.append(LABELS[key] + "使用有来源的估算区间中点，份量并非精确实测。")
    for key, label in (("fiber_g", "天然食物纤维"), ("saturated_fat_g", "饱和脂肪"), ("sodium_mg", "钠")):
        value = evidence_totals.get(key)
        if not valid_range(value) or value.get("coverage") != meals:
            limits.append(label + "数据不足，未计分或作达标判断。")
        else:
            observed = midpoint(value)
            detail = (f"，一般成人可参考至少25克/日" if key == "fiber_g" else
                      f"，约占能量{observed * 9 / amount['kcal'] * 100:.1f}%，WHO一般参考不超过10%" if key == "saturated_fat_g" else "，WHO一般参考低于2000毫克/日")
            limits.append(f"{label}已知估算约{observed:.0f}{'毫克' if key == 'sodium_mg' else '克'}{detail}；此版保留观察，不用未知质量伪造分数。")
            if (key == "fiber_g" and observed < 25 or key == "saturated_fat_g" and observed * 9 / amount["kcal"] > .10
                    or key == "sodium_mg" and observed > 2000):
                missing.append(label + "有完整记录且超出一般参考，需复核整体结构；暂停总分，不能被宏量/食物组高分抵消")
    names = quality.get("distinct_foods")
    limits.append(f"有依据且去重的全天食材约{len(names)}种；多样性仅作观察，未重复加分。" if names else "食材种类数据不足，未从菜名猜测多样性或计分。")
    if missing:
        missing.extend(food_missing)
        return done("待补评分依据")
    missing.extend(food_missing)
    total = sum(p["points"] for p in parts)
    result.update(score_maximum=100, score_coverage_pct=100,
                  score_scope="recorded_full", score_raw_points=total, score_assessed_maximum=100)
    if quality.get("alcohol_doses"):
        penalty = alcohol_penalty(ethanol_g)
        total = max(0, total - penalty)
        doses = "、".join(f"{d['name']}{d['volume_ml']:g}ml×{d['abv_percent']:g}%" for d in quality["alcohol_doses"])
        reason = (f"{doses}，纯酒精约{ethanol_g:.2f}g，扣{penalty:g}分；"
                  "饮用ml×酒精度÷100×0.789，合计每3g扣1分、最高30分。软件权重非医学风险，少量也非无风险。")
        if any(d["abv_source"] == "estimated" for d in quality["alcohol_doses"]):
            reason += "酒精度含估计。"
        part("alcohol", "酒精摄入", 0, -penalty, reason, ethanol_g, None, "g纯酒精")
        result["alcohol_penalty"] = {"ethanol_g": round(ethanol_g, 4), "points": penalty, "formula": RULES["alcohol"]["formula"]}

    # An extreme deviation from a personal macro target retains the existing 79 cap.
    if legacy and any(p["points"] == 0 for p in parts if p["key"] in ("energy", "protein", "fat", "carbs")):
        total = min(total, rules["severe_domain_cap"])
        limits.append("四项营养之一明显偏离该日目标，软件将总分最高限制为79，其他项目不能抵消至绿色；这是目标执行规则，不是医学风险判断。")
    result["score"] = round(total)
    return done("已评已记录饮食", "ready")
