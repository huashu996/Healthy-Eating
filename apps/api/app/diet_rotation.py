"""Read-only, provenance-bound review of recent meal/menu repetition.

Actual meals and prior *suggestions* are distinct evidence. This is a review
requirement, never a food ban, nutritional diagnosis or inferred preference.
Call ``context`` with current records again at submission time; a content hash
is tamper evidence, not a substitute for reloading authoritative records.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import re
import unicodedata

from . import diet_day, diet_publication

VERSION = "recent-main-protein-rotation-v1"
REVIEW_VERSION = "explicit-rotation-review-v1"
WINDOW_DAYS = 3
REASON_BASES = {
    "explicit_today_request": r"今天|今日|当天|这次|本次|点菜|明确要求|明确想吃|today|requested|explicit request",
    "pantry": r"库存|现有|家里|剩余|已有|现成|用完|保质|解冻|保存|pantry|available|stock|fridge",
    "practical_meal_prep": r"备餐|预制|分装|批量|时间|方便|省时|复热|同锅|meal prep|batch|practical|time",
    "reasoned_rotation": r"三日|三天|近.{0,6}记录|轮换|对比|比较|替换|改用|不同|备选|轮流|隔天|隔日|rotation|alternative|recent|compare|previous|different",
}
REASON_TYPES = frozenset(REASON_BASES)
NOTICE = ("前三个饮食日仅使用已记录的实际餐食（含待确认估算）；历史正式菜单另列为建议，不能当已吃。"
          "主蛋白或菜式重复需逐项说明选择理由，不是禁食清单；米饭、咖啡、奶、乳清、简单谷物酸奶水果及调味品不作每日硬性轮换。"
          "不同鱼种仅共享鱼类提示，不等同重复同一食材；缺记录不是没吃，出现次数不是喜好。")

# Deliberately lexical: preparations/cuts collapse, species do not. Never let
# 牛奶/鸡蛋/鱼香/虾酱 become beef/chicken/fish/shrimp meat.
PROTEINS = (
    ("salmon", "三文鱼", "fish", r"三文鱼|鲑鱼|\bsalmon\b"),
    ("beef", "牛肉", "meat", r"牛肉|牛排|牛腩|牛柳|肥牛|牛里脊|牛腱|牛肋|牛腿|牛霖|\bbeef\b"),
    ("chicken", "鸡肉", "poultry", r"鸡肉|鸡胸|鸡腿|鸡翅|鸡排|鸡丁|整鸡|白切鸡|辣子鸡|烧鸡|烤鸡|炖鸡|煎鸡|\bchicken\b"),
    ("pork", "猪肉", "meat", r"猪肉|猪排|猪里脊|猪肝|五花肉|排骨|鱼香肉丝|京酱肉丝|回锅肉|\bpork\b"),
    ("shrimp", "虾", "seafood", r"虾|\bshrimp\b|\bprawn\b"),
    ("duck", "鸭肉", "poultry", r"鸭肉|鸭胸|鸭腿|烤鸭|卤鸭|\bduck\b"),
    ("lamb", "羊肉", "meat", r"羊肉|羊排|羊腿|\blamb\b|\bmutton\b"),
    ("egg", "鸡蛋", "egg", r"鸡蛋|炒蛋|煎蛋|蒸蛋|水煮蛋|蛋液|蛋白液|\beggs?\b"),
    ("tofu", "豆腐", "soy", r"豆腐|豆干|豆皮|腐竹|\btofu\b"),
    ("fish:cod", "鳕鱼", "fish", r"鳕鱼|\bcod\b"),
    ("fish:sea_bass", "鲈鱼", "fish", r"鲈鱼|\bsea bass\b"),
    ("fish:carp", "草鱼", "fish", r"草鱼|\bgrass carp\b"),
    ("fish:bighead_carp", "鳙鱼", "fish", r"鳙鱼|胖头鱼|大头鱼|\bbighead carp\b"),
    ("fish:tilapia", "罗非鱼", "fish", r"罗非鱼|\btilapia\b"),
    ("fish:tuna", "金枪鱼", "fish", r"金枪鱼|吞拿鱼|\btuna\b"),
    ("fish:mackerel", "鲭鱼", "fish", r"鲭鱼|青花鱼|\bmackerel\b"),
    ("fish:sardine", "沙丁鱼", "fish", r"沙丁鱼|\bsardines?\b"),
    ("fish:hairtail", "带鱼", "fish", r"带鱼|\bhairtail\b"),
    ("fish:yellow_croaker", "黄鱼", "fish", r"黄鱼|黄花鱼|\byellow croaker\b"),
    ("fish:trout", "鳟鱼", "fish", r"虹鳟|鳟鱼|\btrout\b"),
    ("fish:crucian_carp", "鲫鱼", "fish", r"鲫鱼|\bcrucian carp\b"),
    ("fish:common_carp", "鲤鱼", "fish", r"鲤鱼|\bcommon carp\b"),
    ("fish:silver_carp", "鲢鱼", "fish", r"鲢鱼|\bsilver carp\b"),
    ("fish:turbot", "多宝鱼", "fish", r"多宝鱼|\bturbot\b"),
    ("fish:eel", "鳗鱼", "fish", r"鳗鱼|鳝鱼|\beel\b"),
    ("fish:pomfret", "鲳鱼", "fish", r"鲳鱼|\bpomfret\b"),
    ("fish:herring", "鲱鱼", "fish", r"鲱鱼|\bherring\b"),
    ("crab", "蟹", "seafood", r"蟹|\bcrab\b"),
    ("squid", "鱿鱼", "seafood", r"鱿鱼|墨鱼|\bsquid\b|\bcuttlefish\b"),
    ("octopus", "章鱼", "seafood", r"章鱼|八爪鱼|\boctopus\b"),
    ("scallop", "扇贝", "seafood", r"扇贝|\bscallops?\b"),
    ("oyster", "牡蛎", "seafood", r"牡蛎|生蚝|\boysters?\b"),
    ("clam", "蛤蜊", "seafood", r"蛤蜊|花蛤|\bclams?\b"),
    ("mussel", "贻贝", "seafood", r"贻贝|青口|\bmussels?\b"),
)
ALIASES = {"鲑鱼": "三文鱼", "salmon": "三文鱼", "西红柿": "番茄", "马铃薯": "土豆",
           "洋芋": "土豆", "青花菜": "西兰花", "吞拿鱼": "金枪鱼", "青花鱼": "鲭鱼"}
GENERIC_DISH = re.compile(r"^(?:测试餐|餐食|饮食|食物|早餐|午餐|晚餐|加餐|练前餐|练后餐|下午餐|家常菜|蔬菜|水果|奶类)(?:照片|记录)?$")
SIMPLE_FOODS = re.compile(r"米饭|白米|糙米|米粥|吐司|面包|燕麦|谷物|麦片|酸奶|发酵乳|牛奶|奶泡|拿铁|咖啡|乳清|蛋白粉|水果|苹果|香蕉|莓|柑橘|橙|猕猴桃|葡萄|\brice\b|\bmilk\b|\byogurt\b|\byoghurt\b|\bcoffee\b|\bwhey\b|\boats?\b|\bcereal\b|\bfruit\b")
SEASONING = re.compile(r"^(?:.*(?:调味|酱油|食盐|胡椒|辣椒粉|香辛料)|(?:烹调|食用|橄榄|花生|菜籽|大豆|芝麻)?油|盐|糖|醋|姜|葱|蒜|葱姜蒜|辣椒|剁椒|鸡精|鸡粉|鱼露|海鲜酱|虾酱|虾皮|虾米|蚝油|牛油|黄油|\b(?:salt|oil|sugar|pepper|butter|sauce)\b)$")


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _text(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip().casefold()


def _canonical(value):
    value = _text(value)
    for alias, name in ALIASES.items():
        value = value.replace(alias, name)
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"\d+(?:\.\d+)?\s*(?:kg|mg|g|克|千克|毫升|ml|份)", "", value)
    return re.sub(r"[\s·:：、,，;；。/\-]+", "", value).strip()


def _names(values):
    if isinstance(values, str):
        return [values]
    return [row if isinstance(row, str) else row.get("name", "") for row in values or []
            if isinstance(row, str) or isinstance(row, dict) and row.get("certainty") != "uncertain"]


def proteins_for(name):
    """Auditable protein identity, preserving known seafood species specificity."""
    text = _text(name)
    if SEASONING.fullmatch(text):
        return []
    text = re.sub(r"鱼露|海鲜酱|虾酱|虾皮|虾米|蚝油|鸡精|鸡粉|牛奶|奶酪|牛油|黄油|鸡汤块|chicken stock|chicken broth", "", text)
    found = [{"key": key, "label": label, "family": family, "classification": "other_fish" if family == "fish" and key != "salmon" else key}
             for key, label, family, pattern in PROTEINS if re.search(pattern, text)]
    # Unknown species remain unknown. Fish-head flesh is fish, not salmon.
    if not any(row["family"] == "fish" for row in found) and re.search(r"鱼头|鱼肉|鱼片|鱼块|鱼丸|鱼饼|深海鱼|淡水鱼|清蒸鱼|水煮鱼|烤鱼|酸菜鱼|^鱼$|\bfish\b", text):
        found.append({"key": "other_fish", "label": "其他/未明确鱼种", "family": "fish", "classification": "other_fish"})
    if not any(row["family"] in ("fish", "seafood") for row in found) and re.search(r"海鲜|贝类|水产品|\bseafood\b", text):
        found.append({"key": "other_seafood", "label": "未明确种类的海鲜", "family": "seafood", "classification": "other_seafood"})
    return sorted(found, key=lambda row: row["key"])


def _features(title, names):
    proteins = {}
    for name in names:
        for protein in proteins_for(name):
            proteins[protein["key"]] = protein
    dishes = set()
    for part in re.split(r"[+＋、,，;；\n]", str(title or "")):
        normalized = _canonical(part)
        if not normalized or GENERIC_DISH.fullmatch(normalized) or SEASONING.fullmatch(normalized):
            continue
        # Simple recurrent staples/drinks/fruit are allowed. A mixed main dish
        # such as a beef sandwich or chicken rice is still assessed.
        if SIMPLE_FOODS.search(normalized) and not proteins_for(normalized):
            continue
        dishes.add(normalized)
    return {"proteins": [proteins[key] for key in sorted(proteins)],
            "protein_keys": sorted(proteins), "dish_keys": sorted(dishes)}


def _ref(row):
    return {"id": row["id"], "version": row["version"]}


def _refs(rows):
    return sorted({_hash(_ref(row)): _ref(row) for row in rows}.values(), key=lambda row: (str(row["id"]), row["version"]))


def _stamp(value):
    try:
        return diet_day.aware_datetime(value).timestamp()
    except (ValueError, TypeError, AttributeError, OverflowError):
        return float("-inf")


def _row_order(row):
    return (_stamp(row.get("created_at")), _stamp(row.get("updated_at")), row.get("version", 0), str(row.get("id", "")))


def _current(rows):
    latest = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("id") or not isinstance(row.get("version"), int) or isinstance(row["version"], bool):
            raise ValueError("轮换证据必须有记录ID和整数版本")
        old = latest.get(row["id"])
        if old is not None and row["version"] == old["version"] and _hash(row) != _hash(old):
            raise ValueError("同一记录ID与版本出现冲突内容")
        if old is None or (row["version"], _row_order(row)) > (old["version"], _row_order(old)):
            latest[row["id"]] = row
    return sorted((row for row in latest.values() if not row.get("deleted_at")), key=_row_order, reverse=True)


def _candidate_rows(menu):
    groups, menu_snapshot = {}, []
    plans = [("root", menu)] + [(f"variant:{index}:{plan.get('id', '')}", plan) for index, plan in enumerate(menu.get("variants") or [])]
    for location, plan in plans:
        recipes = plan.get("recipes") or []
        # Include every supplied recipe, even when validity is not yet granted.
        # Invalid variants cannot smuggle unreviewed ingredients into a review.
        menu_snapshot.append({"location": location, "recipes": deepcopy(recipes)})
        for index, recipe in enumerate(recipes):
            if recipe.get("contributes_to_daily_total") is False:
                continue
            title = recipe.get("dish_title") or recipe.get("title") or ""
            names = _names(recipe.get("items")) or _names(recipe.get("foods"))
            # Title catches an explicitly named main ingredient even when the
            # quantified ingredient list is incomplete; numeric checks remain separate.
            features = _features(title, names + [title])
            if not features["protein_keys"] and not features["dish_keys"]:
                continue
            identity = {key: features[key] for key in ("protein_keys", "dish_keys")}
            key = _hash(identity)
            if key not in groups:
                groups[key] = {"id": "candidate:" + key[:24], "title": title, **features, "locations": []}
            groups[key]["locations"].append({"plan": location, "recipe_index": index, "meal_type": recipe.get("meal_type")})
    return sorted(groups.values(), key=lambda row: row["id"]), _hash({"reference_date": menu.get("reference_date"), "plans": menu_snapshot})


def context(target_date, meals, reports):
    """Snapshot target-3 through target-1, without DB access or mutation."""
    if isinstance(target_date, datetime):
        raise ValueError("目标饮食日必须为日期")
    target = date.fromisoformat(str(target_date))
    start, end = target - timedelta(days=WINDOW_DAYS), target - timedelta(days=1)
    current_meals, current_reports = _current(meals), _current(reports)
    actual, prior, meal_rows, analyses, suggestion_rows = [], [], [], [], []
    for row in current_meals:
        data = row["data"]
        if (data.get("execution") not in ("done", "partial") or data.get("eaten_fraction", 1) <= 0
                or data.get("reference_only") or data.get("is_reference")):
            continue
        day = diet_day.meal_diet_date(row)
        if not start <= day <= end:
            continue
        analysis = next((report for report in current_reports if report.get("data", {}).get("meal_id") == row["id"]
                         and any(ref.get("id") == row["id"] and ref.get("version") == row["version"]
                                 for ref in report["data"].get("input_refs", []) if isinstance(ref, dict))), None)
        result = analysis["data"] if analysis else {}
        title = result.get("meal_title") or data.get("title", "")
        # Uncertain analysis foods are not turned into known ingredients by
        # searching their narrative title. Without analysis, explicit meal text
        # remains recorded evidence, including pending estimates.
        names = _names(result.get("foods")) if result.get("foods") else [title, data.get("ingredients", "")]
        features = _features(title, names)
        actual.append({"kind": "actual_meal", "date": day.isoformat(), "title": title,
                       "status": data.get("status", "pending"), "execution": data["execution"],
                       "eaten_fraction": data.get("eaten_fraction", 1), "is_consumption": True,
                       "is_confirmed": data.get("status") == "confirmed", "meal_ref": _ref(row),
                       "analysis_ref": _ref(analysis) if analysis else None,
                       "meal_sha256": _hash(row), "analysis_sha256": _hash(analysis) if analysis else None,
                       "recognition": "matching_analysis" if analysis else "recorded_text_only", **features})
        meal_rows.append(row)
        if analysis:
            analyses.append(analysis)
    for offset in range(WINDOW_DAYS):
        day = (start + timedelta(days=offset)).isoformat()
        report = diet_publication.successful_formal(current_reports, day)
        if not report:
            continue
        # success helper selects current reports in deterministic newest order.
        menu = report["data"]["next_meal"]
        candidates, menu_hash = _candidate_rows(menu)
        prior.append({"kind": "prior_formal_suggestion", "date": day, "report_ref": _ref(report),
                      "report_sha256": _hash(report), "candidate_hash": menu_hash, "candidates": candidates,
                      "is_consumption": False, "advisory_only": True})
        suggestion_rows.append(report)
    result = {"version": VERSION, "target_date": target.isoformat(), "timezone": diet_day.TIMEZONE,
              "window_start": start.isoformat(), "window_end": end.isoformat(), "window_days": WINDOW_DAYS,
              "actual_meals": sorted(actual, key=lambda row: (row["date"], row["meal_ref"]["id"])),
              "prior_suggestions": prior, "input_refs": _refs(meal_rows), "analysis_refs": _refs(analyses),
              "suggestion_refs": _refs(suggestion_rows), "notice": NOTICE}
    result["context_hash"] = _hash(result)
    return result


def _check_context(value):
    if not isinstance(value, dict) or value.get("version") != VERSION:
        raise ValueError("缺少当前版本轮换上下文")
    if value.get("context_hash") != _hash({key: val for key, val in value.items() if key != "context_hash"}):
        raise ValueError("轮换上下文内容或哈希已变化")


def evaluate(menu, context):
    """Recompute overlaps; neither accept a supplied overlap list nor mutate."""
    _check_context(context)
    if menu.get("reference_date") and menu["reference_date"] != context["target_date"]:
        raise ValueError("菜单日期与轮换上下文不一致")
    candidates, candidate_hash = _candidate_rows(menu)
    overlaps, family_advisories = [], []
    historical = list(context["actual_meals"])
    for suggestion in context["prior_suggestions"]:
        historical.extend({**candidate, "kind": suggestion["kind"], "date": suggestion["date"],
                           "report_ref": suggestion["report_ref"], "is_consumption": False}
                          for candidate in suggestion["candidates"])
    for candidate in candidates:
        sources, protein_keys, dish_keys = [], set(), set()
        for entry in historical:
            same_proteins = set(candidate["protein_keys"]) & set(entry["protein_keys"])
            same_dishes = set(candidate["dish_keys"]) & set(entry["dish_keys"])
            source = {key: deepcopy(entry[key]) for key in ("kind", "date", "title", "meal_ref", "analysis_ref", "report_ref", "status", "is_confirmed") if key in entry}
            source["is_consumption"] = entry["kind"] == "actual_meal"
            source["advisory_only"] = entry["kind"] != "actual_meal"
            if same_proteins or same_dishes:
                sources.append({**source, "protein_keys": sorted(same_proteins), "dish_keys": sorted(same_dishes)})
                protein_keys.update(same_proteins)
                dish_keys.update(same_dishes)
            elif any(row["family"] == "fish" for row in candidate["proteins"]) and any(row["family"] == "fish" for row in entry["proteins"]):
                family_advisories.append({"candidate_id": candidate["id"], "family": "fish", "source": source,
                                          "requires_decision": False, "notice": "同属鱼类，但鱼种不同或未明确，不当作相同主食材。"})
        if sources:
            overlaps.append({"id": "overlap:" + _hash({"candidate_id": candidate["id"], "sources": sources})[:24],
                             "candidate_id": candidate["id"], "title": candidate["title"],
                             "protein_keys": sorted(protein_keys), "dish_keys": sorted(dish_keys),
                             "protein_labels": [row["label"] for row in candidate["proteins"] if row["key"] in protein_keys],
                             "locations": deepcopy(candidate["locations"]), "sources": sources,
                             "has_actual_overlap": any(source["is_consumption"] for source in sources),
                             "has_prior_suggestion_overlap": any(source["advisory_only"] for source in sources),
                             "requires_decision": True})
    return {"version": VERSION, "status": "needs_review" if overlaps else "no_overlap",
            "context_hash": context["context_hash"], "candidate_hash": candidate_hash,
            "candidates": candidates, "overlaps": overlaps, "family_advisories": family_advisories,
            "is_food_ban": False, "notice": NOTICE}


def _concrete(value, minimum, label):
    if not isinstance(value, str) or len(value.strip()) < minimum or len(value) > 4000:
        raise ValueError(label + "需具体且非空")
    return value.strip()


def validate(menu, context):
    """Fail closed on missing/stale/omitted reviews, including hidden variants.

    Human supplied reasons cannot be fact-checked by string validation. Require
    exact overlap IDs, ingredient/dish-specific reasons and a traceable source;
    the caller remains responsible for verifying the cited request/pantry facts.
    """
    assessment = evaluate(menu, context)
    review_data = menu.get("rotation_review")
    if not isinstance(review_data, dict) or review_data.get("version") != REVIEW_VERSION or review_data.get("status") != "reviewed":
        raise ValueError("发布菜单前需要明确的近期重复审核")
    if any(review_data.get(key) != assessment[key] for key in ("context_hash", "candidate_hash")):
        raise ValueError("轮换审核已过期：上下文或候选菜单已变化")
    _concrete(review_data.get("selection_reason"), 8, "本次选菜理由")
    _concrete(review_data.get("source_id"), 1, "审核来源")
    decisions = review_data.get("decisions")
    if not isinstance(decisions, list) or any(not isinstance(row, dict) for row in decisions):
        raise ValueError("重复审核必须逐项列出决定")
    expected = {row["id"]: row for row in assessment["overlaps"]}
    supplied = [row.get("overlap_id") for row in decisions]
    if any(not isinstance(identifier, str) for identifier in supplied):
        raise ValueError("重复审核项目ID必须为字符串")
    if len(supplied) != len(set(supplied)) or set(supplied) != set(expected):
        raise ValueError("重复审核存在遗漏、重复或伪造项目，须覆盖所有重算重叠")
    for decision in decisions:
        overlap = expected[decision["overlap_id"]]
        if decision.get("reason_type") not in REASON_TYPES:
            raise ValueError("重复保留理由须为今日明确点菜、库存、实际备餐或有解释的轮换")
        reason = _concrete(decision.get("reason"), 12, "重复食材选择理由")
        _concrete(decision.get("evidence"), 8, "具体依据")
        if not re.search(REASON_BASES[decision["reason_type"]], _text(reason)):
            raise ValueError("重复理由须解释对应的今日要求、库存、备餐或轮换依据，泛泛营养优点不够")
        # A generic nutrition claim cannot pass merely by attaching an ID.
        anchors = overlap["protein_labels"] + overlap["dish_keys"] + [overlap["title"]]
        if not any(_canonical(anchor) and _canonical(anchor) in _canonical(reason) for anchor in anchors):
            raise ValueError("重复理由须明确点名对应主蛋白或菜式")
    return {**assessment, "status": "passed", "review": deepcopy(review_data)}


def review(menu, context, decisions, selection_reason, source_id):
    """Stamp only explicit supplied reasons; returns a dict without mutation."""
    assessment = evaluate(menu, context)
    result = {"version": REVIEW_VERSION, "status": "reviewed", "context_hash": assessment["context_hash"],
              "candidate_hash": assessment["candidate_hash"], "selection_reason": selection_reason,
              "source_id": source_id, "decisions": deepcopy(decisions)}
    validate({**menu, "rotation_review": result}, context)
    return result
