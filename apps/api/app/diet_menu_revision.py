"""Explicit same-day dish replacement, with complete prior-menu audit.

This changes one existing formal report. It never runs settlement, creates a
second formal plan, changes original generation time, or edits actual intake.
"""
from collections import Counter
from copy import deepcopy
from datetime import date
import json

from pydantic import Field
from . import db, diet_day, diet_planning, diet_policy, diet_quantified, schemas
from .security import digest


class MenuRevision(schemas.Strict):
    target_date: date
    expected_report_id: str = Field(min_length=1, max_length=100)
    expected_report_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=250)
    source_id: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=2000)
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    intake_snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    next_meal: dict
    independent_review: dict


def branch_keys(menu):
    return [(v.get("id"), v.get("training_status"), v.get("skipped_breakfast"))
            for v in menu.get("variants", [])]


def inventory(plan):
    return Counter((item["name"], item["quantity"], item["weight_basis"],
                    db.encode(item["source"]))
                   for recipe in plan.get("recipes", []) for item in recipe.get("items", []))


def validate_replacement(menu, before, ctx, day):
    from . import diet_rotation
    if (menu.get("reference_date") != day or menu.get("plan_scope") != "full_day_reference"
            or menu.get("plan_mode") != "formal" or menu.get("valid_for_use") is not True
            or menu.get("quantification_status") != "verified_estimate"):
        raise ValueError("换菜必须保持同日正式全天参考，并完成重新核算")
    if branch_keys(menu) != branch_keys(before) or not menu.get("variants"):
        raise ValueError("换菜必须保留全部训练与早餐分支，不得遗漏或冒选状态")
    if menu.get("training_status") != ctx["training_plan"]["training_status"]:
        raise ValueError("换菜不能假定当天训练状态")
    if menu["training_status"] == "unknown" and menu.get("active_variant_id"):
        raise ValueError("训练未知不能选定分支")
    if menu.get('active_variant_id'):
        selected = next((v for v in menu['variants'] if v.get('id') == menu['active_variant_id']), None)
        if (not selected or selected.get('training_status') != menu['training_status']
                or selected.get('recipes') != menu.get('recipes')):
            raise ValueError('当前展示菜单必须与已选有效分支及训练状态一致')
    required = ctx.get("dish_requests", {}).get("request_refs", [])
    order = lambda rows: sorted(rows, key=lambda r: (r["id"], r["version"], r["dish"]))
    if order(menu.get("fulfilled_dish_requests", [])) != order(required):
        raise ValueError("换菜仍须明确处理当天点菜，不得继承过期要求")
    known_refs = {r["id"] for r in ctx["taste_library"]["items"]}
    values = ctx.get("health_values", {})
    if (any(p["data"].get("confirmed") and p["data"].get("kind") in ("allergy", "constraint", "dislike")
            for p in ctx.get("preferences", []))
            or str(values.get("忌口", "")).strip() not in ("", "无", "没有", "无忌口")
            or values.get("特殊健康情况", "无") not in ("", "无")):
        raise ValueError("有忌口或特殊健康情况时须先核对安全适用性")
    old_names = {item['name'] for recipe in before['recipes'] for item in recipe['items']}
    new_names = {item['name'] for recipe in menu['recipes'] for item in recipe['items']}
    removed_names = old_names - new_names
    for plan in [menu] + menu["variants"]:
        if plan.get("valid_for_use") is not True or plan.get("reference_date") != day:
            raise ValueError("所有原有分支必须保持有效且属于当天")
        if not 1 <= len(plan.get("recipes", [])) <= 10:
            raise ValueError("分支缺少可执行餐次")
        for request in required:
            if not any(request["dish"].casefold() in r.get("dish_title", "").casefold() for r in plan["recipes"]):
                raise ValueError("有分支遗漏当天点菜")
        for recipe in plan["recipes"]:
            if not all(recipe.get(k) for k in ("dish_title", "portion_summary", "preparation")):
                raise ValueError("换菜须写明菜名、完整份量与做法")
            if not 1 <= len(recipe.get("items", [])) <= 30 or recipe.get("unquantified_items"):
                raise ValueError("所有主食材与油调味都须量化")
            if recipe.get("nutrition", {}).get("kcal", 0) > 1400:
                raise ValueError("单餐超出当前执行上限")
            for item in recipe["items"]:
                diet_planning.CandidateItem.model_validate(item)
            if any(ref.get("reference_id") not in known_refs for ref in recipe.get("reference_sources", [])):
                raise ValueError("换菜来源不在当前菜式参考库")
        if removed_names & {item['name'] for recipe in plan['recipes'] for item in recipe['items']}:
            raise ValueError("有分支仍残留本次已替换的食材")
    if not menu.get("reason_summary") or not menu.get("reasons") or not menu.get("caveat"):
        raise ValueError("换菜需同时更新选择理由和简短操作说明")
    numerical = diet_planning.validate_menu(menu, ctx["targets"]["daily"], ctx.get("pantry_constraints", {}))
    rotation = diet_rotation.validate(menu, ctx["rotation_context"])
    return numerical, rotation


def revise(payload):
    value = MenuRevision.model_validate(payload)
    signature = digest(db.encode(value.model_dump(mode="json")).encode())
    day = value.target_date.isoformat()
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        for row in con.execute("SELECT * FROM audit_events WHERE action='diet.menu_revision' AND target=?", (value.expected_report_id,)):
            audit = json.loads(row["safe_metadata"])
            if audit.get("idempotency_key") == value.idempotency_key:
                if audit["signature"] != signature:
                    raise db.Conflict("换菜幂等键内容冲突")
                return {"report_id": value.expected_report_id, "version": audit["new_version"], "reused": True}
        if day != diet_day.current_diet_day().isoformat():
            raise ValueError("此入口仅修订用户本次指定的当天菜单，不改历史或未来菜单")
        row = con.execute("SELECT * FROM reports WHERE id=? AND module='diet'", (value.expected_report_id,)).fetchone()
        if not row:
            raise db.Conflict("待修改菜单不存在")
        report = db.unpack(row)
        if report["version"] != value.expected_report_version:
            raise db.Conflict("菜单版本已变化")
        data = deepcopy(report["data"])
        before = data.get("next_meal", {})
        if (data.get("plan_mode") != "formal" or before.get("valid_for_use") is not True
                or before.get("reference_date") != day or before.get("plan_scope") != "full_day_reference"):
            raise ValueError("需要当天已存在的有效正式全天菜单")
        ctx = diet_planning.context(day)
        if ctx["expected_report_id"] != report["id"]:
            raise db.Conflict("当前菜单已被其他修订替代")
        policy = diet_policy.get_policy()
        if value.policy_hash != policy["policy_hash"] or value.context_hash != ctx["context_hash"]:
            raise db.Conflict("规则或完整上下文已变化，请重新读取和审核")
        if value.intake_snapshot_sha256 != ctx["intake_snapshot_sha256"]:
            raise db.Conflict("实际摄入已变化，请重新核对换菜")
        if value.independent_review.get("status") != "passed" or not value.independent_review.get("reviewer"):
            raise ValueError("需保留真正完成的独立换菜复核")
        menu = deepcopy(value.next_meal)
        numerical, rotation = validate_replacement(menu, before, ctx, day)
        for plan in [menu] + menu["variants"]:
            plan["target_comparison"] = diet_quantified.compare(plan["daily_nutrition"], ctx["targets"]["daily"])
        menu.update(numeric_validation=numerical, rotation_validation=rotation,
                    policy=policy, training_plan=ctx["training_plan"], food_history=ctx["food_history"],
                    recent_three_days=ctx["recent_three_days"], pantry_constraints=ctx["pantry_constraints"],
                    intake_basis=ctx["intake_snapshot"], intake_snapshot_sha256=ctx["intake_snapshot_sha256"],
                    independent_review=deepcopy(value.independent_review))
        stamp = db.now()
        version = report["version"] + 1
        menu["last_explicit_revision_at"] = stamp
        data["next_meal"] = menu
        data.setdefault("menu_revisions", []).append({"at": stamp, "source_id": value.source_id,
            "reason": value.reason, "previous": before, "version": version,
            "policy_hash": policy["policy_hash"], "context_hash": ctx["context_hash"],
            "context_input_refs": ctx["context_input_refs"], "independent_review": deepcopy(value.independent_review)})
        changed = con.execute("UPDATE reports SET data=?,version=? WHERE id=? AND version=?",
                              (db.encode(data), version, report["id"], report["version"]))
        if changed.rowcount != 1:
            raise db.Conflict("换菜写入时版本冲突")
        db.audit(con, "diet.menu_revision", report["id"], {"idempotency_key": value.idempotency_key,
                 "signature": signature, "new_version": version, "source_id": value.source_id})
        return {"report_id": report["id"], "version": version, "daily_nutrition": menu["daily_nutrition"],
                "rotation_validation": rotation, "reused": False}
