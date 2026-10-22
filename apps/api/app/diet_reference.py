"""One read-only candidate view: reference-only archive plus current actual meals."""
import hashlib
import json

from . import config, diet_day, diet_seed, diet_taste


def archive_index():
    path = config.DATA / "reference_materials" / "index.json"
    if not path.is_file():
        return {"schema_version": "1.0", "items": [], "archive": None}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != "history_reference":
        raise ValueError("参考素材类型不符，不能当摄入记录")
    return data


def collect(meals, reports, archive=None):
    from .diet import current_analysis
    archive = archive_index() if archive is None else archive
    static = []
    for row in archive.get("items", []):
        if not row.get("reference_only") or row.get("eligible_for_meal_totals") or row.get("eligible_for_consumption_frequency"):
            continue
        static.append({**row, "kind": "history_reference", "date": None, "nutrition": None})
    latest = {}
    for meal in meals:
        if meal["id"] not in latest or meal["version"] > latest[meal["id"]]["version"]:
            latest[meal["id"]] = meal
    actual = []
    ordered = sorted(reports, key=lambda r: (r.get("created_at", ""), r.get("version", 0)), reverse=True)
    for row in latest.values():
        data = row["data"]
        if row.get("deleted_at") or data.get("reference_only") or data.get("is_reference") or data.get("execution") not in ("done", "partial") or data.get("eaten_fraction", 1) <= 0:
            continue
        report = current_analysis(row, ordered)
        analysis = report["data"] if report else {}
        actual.append({"id": "meal-reference:" + row["id"], "kind": "actual_meal_reference",
                       "title": analysis.get("meal_title") or data["title"], "foods": analysis.get("foods", []),
                       "methods": [], "staples": [], "combination_pattern": "已有实际餐食的整餐样式，未自动拆解做法",
                       "date": diet_day.meal_diet_date(row).isoformat(), "eaten_at": data.get("eaten_at"), "status": data.get("status"), "meal_id": row["id"], "meal_version": row["version"],
                       "analysis_id": report["id"] if report else None, "analysis_version": report["version"] if report else None,
                       "assets": data.get("assets", []), "reference_only": False, "explicit_current_preference": None})
    seed = diet_seed.collect()
    candidates = actual + static + seed["items"]
    return {"taste_candidates": diet_taste.aggregate(candidates), "seed": {k: v for k, v in seed.items() if k != "items"}, "version": "food-reference-view-v1", "archive": archive.get("archive"), "items": actual + static + seed["items"],
            "archive_count": len(static), "actual_reference_count": len(actual),
            "notice": "素材照片仅供菜式、做法及主食搭配参考，不计摄入、日期或真实频次。已吃记录按当前餐/分析版本动态引用，不重复入餐；出现不等于喜欢。",
            "archive_index_sha256": hashlib.sha256(json.dumps(archive, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def find(context, identifier):
    return next((row for row in context.get("items", []) if row["id"] == identifier), None)


def source_ref(row):
    if not row:
        return None
    return {"reference_id": row["id"], "kind": row["kind"], "title": row["title"],
            "meal_id": row.get("meal_id"), "meal_version": row.get("meal_version"),
            "analysis_id": row.get("analysis_id"), "analysis_version": row.get("analysis_version"),
            "source": row.get("source"), "methods": row.get("methods", []), "staples": row.get("staples", []),
            "use": ("可选入门菜式；不代表使用者吃过或喜欢，份量另算。" if row["kind"] == "starter_recipe_seed" else "只借鉴已出现的组合与已核实做法；下列份量是新建议，不是照片原份量。")}
