"""Read-only, versioned meal observations. Frequency never implies a preference."""
from datetime import date, timedelta
import re
import unicodedata

from .diet_day import meal_diet_date

VERSION = "observed-foods-14d-v2"
GROUP_LABELS = {"蛋白质": "protein", "油脂": "fats", "碳水": "carbs", "蔬菜": "fiber"}
LABEL = re.compile(r"(蛋白质|油脂|碳水|蔬菜)\s*[:：]")
GENERIC_TITLE = re.compile(r"^(?:早餐|午餐|晚餐|加餐|练前餐|练后餐|餐食|饮食|食物)(?:照片|记录)?$")

# This small offline vocabulary describes observations, not nutrient amounts.
# Exact ingredient names only: e.g. 鱼香肉丝 is not fish; 水果酸奶 is not fruit.
PATTERN_VERSION = "food-group-observations-7-14d-v1"
FOOD_GROUP_LABELS = {
    "vegetables": "蔬菜", "fruit": "水果", "fish": "鱼类", "seafood": "鱼虾贝等水产品",
    "omega3_sources": "明确的Omega-3食物来源", "whole_grains_tubers": "全谷薯类",
    "dairy": "奶类", "soy": "大豆及豆制品",
}
GROUP_FOODS = {
    "vegetables": set("蔬菜 青菜 绿叶菜 生菜 菠菜 白菜 大白菜 小白菜 青椒 彩椒 西兰花 花菜 菜花 胡萝卜 西红柿 番茄 黄瓜 冬瓜 丝瓜 苦瓜 茄子 芹菜 油菜 油麦菜 小油菜 空心菜 芥蓝 韭菜 卷心菜 包菜 紫甘蓝 娃娃菜 豆芽 绿豆芽 黄豆芽 莴笋 芦笋 竹笋 白萝卜 萝卜 菌菇 蘑菇 香菇 金针菇 木耳 南瓜 洋葱".split()),
    "fruit": set("水果 鲜果 新鲜水果 苹果 香蕉 橙子 橙 橘子 橘 柑橘 猕猴桃 奇异果 蓝莓 草莓 树莓 莓果 梨 桃 水蜜桃 西瓜 哈密瓜 蜜瓜 葡萄 柚子 西柚 芒果 菠萝 凤梨 樱桃 车厘子 李子 杏 火龙果 鲜枣 冬枣 木瓜 荔枝 桂圆".split()),
    "fish": set("鱼 鱼肉 鲈鱼 鳕鱼 草鱼 鲫鱼 鲤鱼 青鱼 鲢鱼 鳙鱼 罗非鱼 多宝鱼 黄鱼 黄花鱼 带鱼 秋刀鱼 三文鱼 鲑鱼 沙丁鱼 鲭鱼 青花鱼 鲱鱼 金枪鱼 虹鳟 鳟鱼 鳗鱼".split()),
    "seafood": set("鱼虾 水产品 海鲜 虾 虾仁 大虾 对虾 基围虾 白虾 蟹 蟹肉 贝类 蛤蜊 牡蛎 生蚝 扇贝 贻贝 青口 鱿鱼 墨鱼 章鱼 八爪鱼".split()),
    "omega3_sources": set("三文鱼 鲑鱼 沙丁鱼 鲭鱼 青花鱼 鲱鱼 虹鳟 鳟鱼 鳗鱼 核桃 核桃仁 亚麻籽 亚麻籽油 奇亚籽 菜籽油 大豆油".split()),
    "whole_grains_tubers": set("燕麦 燕麦片 原味燕麦片 糙米 糙米饭 全麦面包 全麦吐司 全麦土司 全麦面 全麦面条 荞麦 荞麦米 小米 小米饭 玉米 玉米粒 红薯 紫薯 地瓜 马铃薯 土豆 山药 芋头 薯类".split()),
    "dairy": set("牛奶 纯牛奶 鲜牛奶 低脂牛奶 脱脂牛奶 全脂牛奶 酸奶 原味酸奶 无糖酸奶 希腊酸奶 奶酪 乳酪 奶粉".split()),
    "soy": set("大豆 黄豆 黑豆 毛豆 豆腐 嫩豆腐 北豆腐 南豆腐 老豆腐 豆干 豆腐干 豆浆 无糖豆浆 豆皮 豆腐皮 腐竹".split()),
}
GROUP_FOODS["seafood"] |= GROUP_FOODS["fish"]
# Audited, explicit current analysis names. These aliases record presence only;
# their quantities and mixed ingredients are never inferred or decomposed here.
GROUP_FOODS["vegetables"] |= {"生菜及混合叶菜", "生菜及混合绿叶菜"}
GROUP_FOODS["dairy"] |= {"全脂牛奶及奶泡", "原味风味发酵乳150g", "0蔗糖风味发酵乳150g"}
GROUP_FOODS["whole_grains_tubers"] |= {"全麦小麦谷物", "97%全麦小麦谷物", "全麦小麦谷物（用户别名“燕麦”）40g"}
GROUP_FOODS = {group: {unicodedata.normalize("NFKC", name) for name in names} for group, names in GROUP_FOODS.items()}
PREPARATION_PREFIXES = ("清蒸", "水煮", "白灼", "清炒", "蒜蓉", "凉拌", "炝炒", "烤", "蒸", "煮", "炒", "煎")
PATTERN_GUIDANCE = (
    {"id": "cns-fish-2022", "title": "中国居民膳食指南2022：适量吃鱼、禽、蛋、瘦肉", "date": "2022-05-04",
     "url": "https://dg.cnsoc.org/article/04/3tyM8WoTTUmc_oFHMymk3Q.html",
     "summary": "一般成人可参考每周吃鱼2次或300–500克；这里统计出现餐数，无法核实克重或是否达标。鱼类建议不限定深海鱼。"},
    {"id": "nhc-food-pattern-2025", "title": "国家卫生健康委：健康饮食、合理膳食核心信息", "date": "2025-05-16",
     "url": "https://www.nhc.gov.cn/sps/c100088/202505/6b7a718abd4848e8a3e98fc561a8858b.shtml",
     "summary": "成人每日新鲜蔬菜至少300克、深色约占一半，水果200–350克。蔬果不能相互替代。水产品包括鱼虾贝类，与鱼类单项统计口径不同。"},
    {"id": "nhc-supplements-2026", "title": "国家卫生健康委2026年5月25日发布会（卫健委全文转载）", "date": "2026-05-25",
     "url": "https://wjw.chifeng.gov.cn/zzllms/zzllms_lbt/202605/t20260526_2770547.html",
     "summary": "复合维生素等膳食补充剂不能替代新鲜蔬果；少数营养素无法重现完整食物的作用。"},
    {"id": "nih-omega3", "title": "NIH ODS：Omega-3脂肪酸资料", "date": None, "checked_on": "2026-10-12",
     "url": "https://ods.od.nih.gov/factsheets/Omega3FattyAcids-HealthProfessional/",
     "summary": "鱼类Omega-3含量因种类等因素而异，核桃、亚麻籽、奇亚籽等提供ALA。食物出现次数不能诊断Omega-3缺乏，植物ALA也不等同于EPA/DHA。"},
)


def food_groups_for(name):
    """Recognize a whole, explicit name; do not split or search mixed-dish names."""
    key = unicodedata.normalize("NFKC", str(name)).strip()
    variants = {key}
    for prefix in PREPARATION_PREFIXES:
        if key.startswith(prefix):
            variants.add(key[len(prefix):].strip())
    return {group for group, names in GROUP_FOODS.items() if names & variants}


def _pattern_summary(events, recent):
    groups = {}
    recent_key = recent.isoformat()
    for key, label in FOOD_GROUP_LABELS.items():
        sources = []
        for event in events:
            foods = [food for food in event["foods"] if key in food["groups"]]
            if foods:
                sources.append({**event["source"], "foods": [{"name": f["name"], "evidence": f["evidence"]} for f in foods]})
        sources.sort(key=lambda s: (s["date"], s["meal_id"]), reverse=True)
        recent_sources = [s for s in sources if s["date"] >= recent_key]
        groups[key] = {"label": label, "count_7d": len(recent_sources), "count_14d": len(sources),
                       "observed_days_7d": len({s["date"] for s in recent_sources}),
                       "observed_days_14d": len({s["date"] for s in sources}), "sources": sources,
                       "status": "observed" if sources else "not_seen_in_records"}
    unknown = [e for e in events if e["unknown"]]
    observed_7d = [e for e in events if e["source"]["date"] >= recent_key]
    observations = [f"{g['label']}：近7天在{g['count_7d']}餐记录中见到，近14天在{g['count_14d']}餐见到。" for g in groups.values()]
    notice = ("仅统计已吃且当前分析明确识别的食物，同一餐同一类只记一次；不是份数、克重或达标判断。"
              "混合菜未拆解、名称未收录和不确定食物保留未知；未记录不等于没吃，少见不等于实际营养缺乏。"
              "鱼类包含在水产品中，两项不可相加；Omega-3食物来源只是有限名单，植物ALA不等于鱼类EPA/DHA。")
    return {"version": PATTERN_VERSION, "groups": groups, "observed_days_7d": len({e["source"]["date"] for e in observed_7d}),
            "unknown_meals_7d": sum(e["source"]["date"] >= recent_key for e in unknown),
            "unknown_meals_14d": len(unknown), "notice": notice, "observations": observations,
            "guidance": [dict(source) for source in PATTERN_GUIDANCE]}


def pattern_additions(history, preferences=None):
    """Food-first optional actions; no diagnoses or supplement prescriptions."""
    patterns = history.get("diet_patterns") or {}
    groups = patterns.get("groups") or {}
    if not groups or not history.get("meals_7d"):
        return ["近7天可用饮食记录还不够，先保持规律三餐、搭配蔬果；补齐实际吃过的食物后再看结构，不因漏记额外进食或购买补剂。",
                "即使每天服用多维，蔬果仍要保留；少放烹调油，照常吃主食和蛋白质食物，不挨饿补偿。"]
    preferences = preferences or []
    restricted = any(r.get("data", {}).get("confirmed") and r["data"].get("kind") in ("allergy", "constraint", "dislike") for r in preferences)
    if restricted:
        return ["近7–14天的类别次数只反映已记录食物；漏记、复合菜和未明确识别的食物仍有未知，不能据此判断营养缺乏或需要补剂。",
                "已有明确忌口或不喜欢的食物，先核对限制再调整搭配，不自动推荐可能冲突的食材；维持正常三餐，不挨饿补偿。",
                "多维不能替代蔬果；在已确认可以食用的范围内保持食物多样、烹调少油。"]
    likes = confirmed_likes(preferences)
    liked_names = [name for values in likes.values() for name in values]

    def choose(group, fallback):
        return next((name for name in liked_names if group in food_groups_for(name)), fallback)

    notes = []
    recorded_days = patterns.get("observed_days_7d", 0)
    for key, fallback, action in (("vegetables", "适合自己的蔬菜", "在下顿原有饭菜中搭配"),
                                  ("fruit", "适合自己的新鲜水果", "在今天合适的一餐或原有加餐中安排")):
        group = groups[key]
        if group["observed_days_7d"] < recorded_days:
            seen = "未见" if not group["count_7d"] else f"只在{group['observed_days_7d']}个已记录日见到"
            notes.append(f"近7天记录{seen}{group['label']}；若没有漏记，可{action}{choose(key, fallback)}，结合当天实际份量，不用额外叠加一餐。")
    fish = groups["fish"]
    if fish["count_7d"] < 2:
        seen = "未见" if not fish["count_7d"] else f"只见{fish['count_7d']}餐"
        source = choose("fish", "自己能吃且愿意吃的鱼")
        notes.append(f"近7天记录{seen}鱼类；若没有漏记且无相关忌口，本周可用{source}替换一餐原有肉类，清蒸或少油烹调。鱼不必限定深海鱼，记录未见不能判断Omega-3缺乏，也不能据此决定需要补剂。")
    notes.append("即使每天服用多维，蔬果仍要保留；炒菜少油，主食和蛋白质照正常目标吃，不跳餐或挨饿补偿。")
    return notes[:4]


def food_key(name):
    return " ".join(str(name).split()).casefold()


def confirmed_likes(preferences):
    """Read explicit groups only; support imported grouped text without rewriting it."""
    groups = {key: [] for key in GROUP_LABELS.values()}
    for row in preferences:
        data = row["data"]
        if data.get("kind") != "like" or not data.get("confirmed"):
            continue
        fields = data.get("food_likes") or {}
        legacy = fields.get("previous", "") or (data.get("rule", "") if not fields else "")
        # Examples or prose are not a machine-readable statement of food preferences.
        matches = [] if re.search(r"例如|比如|示例|举例", legacy) else list(LABEL.finditer(legacy))
        old = {}
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(legacy)
            old[GROUP_LABELS[match[1]]] = legacy[match.end():end].strip()
        for key in groups:
            # An explicit populated current field takes precedence over imported text.
            value = str(fields.get(key) or old.get(key, ""))
            for food in re.split(r"[、,，;；\n\s]+", value):
                if food and food not in groups[key]:
                    groups[key].append(food)
    return groups


def summarize(meals, reports, target_date, timezone):
    """Observe 14 completed diet dates; retain saved and legacy date attribution."""
    from .diet import current_analysis
    end = date.fromisoformat(target_date) - timedelta(days=1)
    from .diet_policy import get_policy
    recent_window, full_window = get_policy()["habit_windows_days"]
    start, recent = end - timedelta(days=full_window - 1), end - timedelta(days=recent_window - 1)
    # records() already returns current rows. Also guard duplicate IDs/revisions in callers.
    current = {}
    for row in meals:
        if row["id"] not in current or row["version"] > current[row["id"]]["version"]:
            current[row["id"]] = row
    ordered_reports = sorted(reports, key=lambda r: (r.get("created_at", ""), r.get("version", 0), r["id"]), reverse=True)
    candidates, observed, refs, analyses, pattern_events = {}, [], [], {}, []
    for meal in current.values():
        data = meal["data"]
        if meal.get("deleted_at") or data.get("execution") not in ("done", "partial") or data.get("eaten_fraction", 1) <= 0:
            continue
        day = meal_diet_date(data)
        if not start <= day <= end:
            continue
        report = current_analysis(meal, ordered_reports)
        result = report["data"] if report else {}
        observed.append(day)
        refs.append({"id": meal["id"], "version": meal["version"]})
        if report:
            analyses[report["id"]] = {"id": report["id"], "version": report["version"]}
        explicit_foods = result.get("foods") or []
        categorized = []
        has_unknown = not explicit_foods
        for food in explicit_foods:
            name = str(food.get("name") or "").strip()
            recognized = food_groups_for(name) if food.get("certainty") == "clear" else set()
            has_unknown |= not recognized
            if recognized:
                categorized.append({"name": name, "evidence": food.get("evidence", ""), "groups": recognized})
        pattern_events.append({"source": {"meal_id": meal["id"], "meal_version": meal["version"],
                                         "date": day.isoformat(), "meal_type": data["meal_type"],
                                         "analysis_id": report["id"] if report else None,
                                         "analysis_version": report["version"] if report else None},
                               "foods": categorized, "unknown": has_unknown})
        title = str(result.get("meal_title") or data.get("title") or "").strip()
        items = ([] if not title or GENERIC_TITLE.fullmatch(title) else
                 [("meal", title, "当前餐食分析标题" if result.get("meal_title") else "当前餐食记录标题")])
        items += [("food", f["name"].strip(), f.get("evidence", "")) for f in result.get("foods", [])
                  if f.get("certainty") == "clear" and f.get("name", "").strip()]
        seen = set()
        for kind, name, evidence in items:
            key = (kind, food_key(name))
            if key in seen:
                continue
            seen.add(key)
            item = candidates.setdefault(key, {"name": name, "kind": kind, "sources": []})
            item["sources"].append({"meal_id": meal["id"], "meal_version": meal["version"],
                                    "date": day.isoformat(), "meal_type": data["meal_type"],
                                    "analysis_id": report["id"] if report else None,
                                    "analysis_version": report["version"] if report else None,
                                    "evidence": evidence})
    for item in candidates.values():
        sources = sorted(item["sources"], key=lambda s: (s["date"], s["meal_id"]), reverse=True)
        item.update(sources=sources, count_14d=len(sources),
                    count_7d=sum(s["date"] >= recent.isoformat() for s in sources),
                    observed_days_14d=len({s["date"] for s in sources}),
                    last_eaten_on=sources[0]["date"], meal_types=sorted({s["meal_type"] for s in sources}),
                    evidence_strength="repeated_records" if len(sources) > 1 else "single_observation")
    days = len(set(observed))
    notice = (f"近14天有{days}天、{len(observed)}餐实际已吃记录（近7天{sum(d >= recent for d in observed)}餐）。"
              + ("还在积累记录，先参考已见过的搭配，不能说已摸清完整食谱。" if days < 7 else
                 "继续结合接下来一至两周的记录校正；这些记录仍不代表完整食谱。")
              + "出现次数仅是观察，不等于喜欢；未记录不等于没吃或不喜欢，单次出现只作备选。")
    patterns = _pattern_summary(pattern_events, recent)
    return {"version": VERSION, "window_start": start.isoformat(), "window_end": end.isoformat(),
            "window_days": 14, "recent_window_start": recent.isoformat(), "recent_window_days": 7,
            "observed_days": days, "meal_count": len(observed), "meals_7d": sum(d >= recent for d in observed),
            "analyzed_meals": len(analyses), "status": "empty" if not observed else "collecting" if days < 7 else "observed",
            "notice": notice, "candidates": sorted(candidates.values(), key=rank, reverse=True),
            "diet_patterns": patterns, "food_groups": patterns["groups"],
            "input_refs": sorted(refs, key=lambda r: r["id"]), "analysis_refs": sorted(analyses.values(), key=lambda r: r["id"])}


def rank(candidate):
    # More than one date is stronger than many uploads from one date; never call this liking.
    return (candidate["observed_days_14d"], candidate["count_14d"], candidate["count_7d"], candidate["last_eaten_on"], candidate["name"])


def meal_candidate(history, meal_type):
    slots = ("加餐", "练前餐", "练后餐") if meal_type == "加餐 / 练前餐" else (meal_type,)
    options = [c for c in history.get("candidates", []) if c["kind"] == "meal" and set(c["meal_types"]) & set(slots)]
    return max(options, key=rank, default=None)


def familiar_options(options, history):
    """Exact names only. A mixed dish containing a token is not a separate ingredient."""
    names = {food_key(c["name"]): c for c in history.get("candidates", []) if c["kind"] == "food"}
    known = [food for food in options if food_key(food) in names]
    return sorted(known, key=lambda food: rank(names[food_key(food)]), reverse=True) or options
