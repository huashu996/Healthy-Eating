"""Private software skill context, source validation and versioned plan revisions."""
from copy import deepcopy
from datetime import date
import math

from . import db, diet, diet_cycle, diet_day, diet_history, diet_policy, diet_recent, diet_reference, diet_quantified, diet_remaining, food_catalog, diet_tracking, diet_pantry
from .security import digest
from . import diet_publication


def context(target_date):
    from . import diet_rotation
    day = date.fromisoformat(str(target_date)).isoformat()
    with db.connect() as con:
        reports = [db.unpack(r) for r in con.execute("SELECT * FROM reports WHERE module='diet' ORDER BY created_at DESC")]
    meals = db.records("meals", 10000)["items"]
    result = {"task": "collect_context_for_morning_diet_plan", "target_date": day,
            "publication": diet_publication.window(day),
            "skill": {"text": diet_policy.SKILL_PATH.read_text(encoding="utf-8")}, "policy": diet_policy.get_policy(),
            "profile": db.records("facts", 1000)["items"], "health_values": diet_tracking.health_state()[0], "preferences": db.records("diet_preferences", 1000)["items"],
            "targets": diet.calorie_target(target_date=day), "training_plan": diet_day.training_plan_for_date(day),
            "dish_requests": diet_day.dish_requests_for_date(day),
            "pantry_constraints": diet_pantry.for_date(day),
            "taste_library": diet_reference.collect(meals, reports),
            "nutrition_library": db.records("food_products", 1000)["items"],
            "food_history": diet_history.summarize(meals, reports, day, "Asia/Shanghai"),
            "recent_three_days": diet_recent.summarize_three_days(day, reports, meals, diet.calorie_target()),
            "rotation_context": diet_rotation.context(day, meals, reports),
            "execution": {"local_generator": "deterministic constrained candidate selection + nutrient sum", "external_model_called": False,
                          "agent_steps": "主聊天读取此上下文提出/审核候选；软件未自动调用外部模型，独立复核结果须另存来源。"}}

    from . import diet_target_review
    result["target_review"] = diet_target_review.status()
    current = diet.overview()
    snapshot = intake_snapshot(current)
    result["intake_snapshot"] = snapshot
    result["intake_snapshot_sha256"] = diet_remaining.intake_snapshot_fingerprint(snapshot)
    from . import diet_targets
    ref_rows = diet_targets.records() + result["profile"] + result["preferences"] + result["nutrition_library"] + meals
    ref_rows += db.records("body_checkins", 1000)["items"] + db.records("diet_days",1000)["items"]
    ref_rows += result["food_history"].get("analysis_refs", []) + result["recent_three_days"].get("analysis_refs", [])
    result["context_input_refs"] = sorted({r["id"]: {"id": r["id"], "version": r["version"]} for r in ref_rows}.values(), key=lambda r:r["id"])
    result["expected_report_id"] = current["daily_plan"]["id"] if current["daily_plan"] else None
    result["context_hash"] = digest(db.encode(result).encode())
    return result


def validate_menu(menu, target, pantry_constraints=None):
    """Independently recompute each item, each meal and day; reject budget-only data."""
    errors = []
    if pantry_constraints is None and menu.get("reference_date"):
        pantry_constraints = diet_pantry.for_date(menu["reference_date"])
    pantry_validation = diet_pantry.validate(menu, pantry_constraints)
    for plan in [menu] + list(menu.get("variants") or []):
        if not plan.get("valid_for_use"):
            continue
        all_items = []
        for recipe in plan.get("recipes", []):
            items = recipe.get("items", [])
            if not items: errors.append("量化餐缺少食物明细")
            for row in items:
                q = row.get("quantity")
                if not isinstance(q, (int, float)) or isinstance(q, bool) or not math.isfinite(q) or q <= 0 or row.get("unit") != "g":
                    errors.append("食物份量无效"); continue
                if not row.get("source") or not row.get("weight_basis"): errors.append("缺来源或生熟口径")
                source = row.get("source", {})
                expected = None
                if source.get("kind") == "official_composition_reference":
                    match = next((f for f in diet_quantified.DATA["foods"] if f["fdc_id"] == source.get("fdc_id")), None)
                    allowed_names = ({match["name_zh"], *match.get("aliases", [])} | {diet_quantified.NAMES[k] for k,identifier in diet_quantified.IDS.items() if identifier == source.get("fdc_id")}) if match else set()
                    if match and (row["name"] not in allowed_names or row["weight_basis"] != match["state_and_weighing"]):
                        errors.append("食物名称或生熟称量口径与来源不符")
                    if match:
                        for proxy in match.get("proxy_uses", []):
                            if proxy["name"] in row["name"] and proxy["caveat"] not in row.get("assumptions", []):
                                errors.append("食材代理估算必须保留来源限定，不能当成该品种专测")
                    if match and source.get("dataset_sha256") == diet_quantified.DATA["source"]["csv_sha256"] and source.get("url") == diet_quantified.DATA["source"]["official_csv_zip"]:
                        raw = match["per_100g"]
                        expected = {"kcal": raw["energy_kcal"], "protein_g": raw["protein_g"], "fat_g": raw["fat_g"], "carbs_g": raw["carbohydrate_g"]}
                elif source.get("kind") == "user_adopted_estimate":
                    from . import diet_user_reference
                    expected = diet_user_reference.validate_item(row)
                elif source.get("kind") in ("personal_label", "catalog_reference"):
                    saved = food_catalog.product_version(source.get("product_id"), source.get("product_version"))
                    food = diet_quantified.personal_product([saved], saved["data"]["name"])
                    expected = food["per_100g"] if food else None
                    data = saved["data"]
                    if row["name"] not in [data["name"], *data.get("aliases", [])]: errors.append("产品名与固定标签版本不符")
                    if source.get("kind") == "catalog_reference" and data.get("source_kind") == "generic_reference" and data.get("identity_confirmed") and data.get("basis") == "per_100g" and all(data.get(k) is not None for k in ("energy","protein_g","fat_g","carbs_g")):
                        expected = {"kcal": data["energy"] / (4.184 if data["energy_unit"] == "kJ" else 1), **{k:data[k] for k in diet_quantified.KEYS[1:]}}
                if not expected or any(abs(row.get("per_100g", {}).get(k, -999) - expected[k]) > .000001 for k in diet_quantified.KEYS):
                    errors.append("营养值与已存来源版本不符")
                for key in diet_quantified.KEYS:
                    value = row.get("per_100g", {}).get(key)
                    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or abs(value * q / 100 - row.get("nutrition", {}).get(key, -1)) > .0002:
                        errors.append("食物换算不一致")
            all_items += items
            if any(abs(recipe.get("nutrition", {}).get(k, -1) - diet_quantified.total(items)[k]) > .001 for k in diet_quantified.KEYS): errors.append("餐合计不一致")
        total = diet_quantified.total(all_items)
        if any(abs(plan.get("daily_nutrition", {}).get(k, -1) - total[k]) > .001 for k in diet_quantified.KEYS): errors.append("全天合计不一致")
        if not diet_quantified.compare(total, target)["within_tolerance"]: errors.append("全天目标超出规划容差")
    if errors: raise ValueError("；".join(sorted(set(errors))))
    return {"status": "passed", "method": "per_item_per_meal_daily_recalculation", "policy_hash": diet_policy.get_policy()["policy_hash"], "pantry_validation": pantry_validation}


def intake_snapshot(overview):
    current = overview["today"]
    refs = [{"meal_id": e["meal"]["id"], "meal_version": e["meal"]["version"],
             "analysis_id": (e.get("analysis") or {}).get("id"), "analysis_version": (e.get("analysis") or {}).get("version")}
            for e in overview["entries"] if e["diet_date"] == current["date"] and e["meal"]["data"]["execution"] in ("done", "partial")]
    return {"date": current["date"], "meals_count": current["meals_count"], "totals": deepcopy(current["totals"]),
            "snapshot_scope": "recorded_actual", "input_refs": sorted(refs, key=lambda r: r["meal_id"])}


def publish_reference(target_date, expected_report_id, reason, idempotency_key, independent_review=None):
    """Publish a clearly dated future reference preview; never modify intake."""
    request_hash = digest(db.encode({"operation": "publish_reference", "target_date": str(target_date), "expected_report_id": expected_report_id, "reason": reason, "independent_review": independent_review}).encode())
    prior = _prior(idempotency_key, request_hash)
    if prior: return prior
    current_day = diet_day.current_diet_day().isoformat()
    result = diet_cycle.build(str(target_date), "Asia/Shanghai", force=True)
    result["next_meal"]["numeric_validation"] = validate_menu(result["next_meal"], result["reference_targets"]["daily"])
    if not result["next_meal"].get("valid_for_use"):
        raise ValueError("量化菜单未完成，不能发布为可执行方案")
    result.update(target_date=current_day, reference_date=str(target_date), revision_of=expected_report_id, revision_reason=reason,
                  plan_mode="test_preview", publication_trigger="explicit_test_request", scores_settled=False)
    diet_publication.label_menu(result["next_meal"], "test_preview")
    result["next_meal"].update(reference_date=str(target_date), independent_review=independent_review or {"status": "not_recorded"})
    return _save_revision(result, expected_report_id, idempotency_key, request_hash)


def revise_remaining(expected_report_id, skipped_meals, remaining_meals, training_status, reason, idempotency_key, now=None):
    request_hash = digest(db.encode({"operation": "remaining", "expected_report_id": expected_report_id, "skipped_meals": skipped_meals, "remaining_meals": remaining_meals, "training_status": training_status, "reason": reason, "now": now}).encode())
    prior_result = _prior(idempotency_key, request_hash)
    if prior_result: return prior_result
    overview = diet.overview()
    prior = overview.get("daily_plan")
    if not prior or prior["id"] != expected_report_id: raise db.Conflict("当前方案已变化，请重新读取")
    day = overview["today"]["date"]
    # Build a fresh same-day menu; a preview for tomorrow cannot supply today's training state.
    fresh = diet_cycle.build(day, "Asia/Shanghai", force=True)
    menu = fresh["next_meal"]
    variants = menu.get("variants", [])
    chosen = next((v for v in variants if v.get("training_status") == training_status and not v.get("skipped_breakfast")), menu)
    fresh["next_meal"] = chosen
    proposed = diet_remaining.proposed_remaining(fresh, intake_snapshot(overview), skipped_meals=skipped_meals,
        remaining_meals=remaining_meals, training_status=training_status, now=now or db.now())
    fresh.update(revision_of=prior["id"], revision_reason=reason)
    fresh["next_meal"] = proposed
    fresh["next_meal"]["reference_date"] = day
    fresh["next_meal"]["policy"] = diet_policy.get_policy()
    fresh.update(plan_mode="formal", publication_trigger="explicit_recalculate_remaining", scores_settled=False)
    fresh["next_meal"].update(plan_mode="formal", publication_notice="按用户本次明确指令重做剩余饮食；普通漏餐或上下文更新不会触发此操作。")
    return _save_revision(fresh, expected_report_id, idempotency_key, request_hash)


def _prior(key, request_hash):
    from .external_api import existing
    with db.connect() as con:
        return existing(con, key, request_hash)


def _save_revision(result, expected_report_id, key, signature, expected_context_hash=None):
    from .external_api import existing, save_report
    if len(key) < 8: raise ValueError("幂等键至少8字符")
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        prior = existing(con, key, signature)
        if prior: return prior
        reports = [db.unpack(r) for r in con.execute("SELECT * FROM reports WHERE module='diet' ORDER BY created_at DESC")]
        current = diet_cycle.latest(reports, diet_day.current_diet_day(), "Asia/Shanghai")
        if not current or current["id"] != expected_report_id: raise db.Conflict("当前方案已变化，请重新读取")
        if expected_context_hash and context(result["reference_date"])["context_hash"] != expected_context_hash:
            raise db.Conflict("候选核验后上下文已变化，请重新计算")
        if result.get("plan_mode") == "formal" and result["next_meal"].get("plan_scope") == "full_day_reference":
            diet_publication.require_formal_window(result["reference_date"])
            from . import diet_target_review
            diet_target_review.require_review()
            if diet_publication.successful_formal(reports, result["reference_date"]):
                raise db.Conflict("目标日期已有正式成功菜单；新信息只保存，不自动反复生成")
        if result["next_meal"].get("plan_scope") == "remaining_today":
            fresh_snapshot = intake_snapshot(diet.overview())
            if diet_remaining.intake_snapshot_fingerprint(fresh_snapshot) != result["next_meal"].get("intake_snapshot_sha256"):
                raise db.Conflict("核算期间实际摄入已变化，请重算")
        return save_report(con, result, result["target_date"], key, signature)

# The parent agent can submit new dish candidates without changing the local
# generator. Metadata is retained, while all executable food/nutrient fields
# have a strict schema and are independently tied to stored source versions.
from typing import Literal
from pydantic import Field
from . import schemas

class CandidateNutrients(schemas.Strict):
    kcal: float = Field(ge=0, le=10000)
    protein_g: float = Field(ge=0, le=10000)
    fat_g: float = Field(ge=0, le=10000)
    carbs_g: float = Field(ge=0, le=10000)

class CandidateItem(schemas.Strict):
    item_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0, le=1500)
    unit: Literal['g']
    weight_basis: str = Field(min_length=1, max_length=1500)
    nutrition: CandidateNutrients
    per_100g: CandidateNutrients
    source: dict
    assumptions: list[str] = Field(default_factory=list, max_length=30)

class CandidateWrite(schemas.Strict):
    target_date: date
    plan_mode: Literal['formal', 'test_preview'] = 'formal'
    expected_report_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=250)
    policy_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    context_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    intake_snapshot_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    context_input_refs: list[dict] = Field(max_length=2000)
    next_meal: dict
    independent_review: dict | None = None


def publish_candidate(value):
    """Validated agent writeback: source-backed arbitrary dishes, append-only."""
    value = CandidateWrite.model_validate(value)
    payload = value.model_dump(mode='json')
    request_hash = digest(db.encode(payload).encode())
    prior = _prior(value.idempotency_key, request_hash)
    if prior: return prior
    if value.plan_mode == 'formal':
        diet_publication.require_formal_window(value.target_date)
        from . import diet_target_review
        diet_target_review.require_review()
    policy = diet_policy.get_policy()
    if value.policy_hash != policy['policy_hash']: raise db.Conflict('规则版本已变化，请重新导出上下文')
    current = diet.overview()
    if not current['daily_plan'] or current['daily_plan']['id'] != value.expected_report_id:
        raise db.Conflict('当前方案已变化，请重新读取')
    snapshot = intake_snapshot(current)
    if value.intake_snapshot_sha256 != diet_remaining.intake_snapshot_fingerprint(snapshot):
        raise db.Conflict('实际摄入已变化，请重新导出上下文')
    ctx = context(value.target_date)
    if value.context_hash != ctx['context_hash']: raise db.Conflict('规划上下文或参考材料已变化，请重新导出')
    expected_refs = ctx['context_input_refs']
    if sorted(value.context_input_refs, key=lambda r: r['id']) != expected_refs:
        raise db.Conflict('个人资料、偏好、标签或餐食版本已变化')
    if value.target_date < diet_day.current_diet_day(): raise ValueError('新全天建议不可替换为过去日期')
    menu = deepcopy(value.next_meal)
    if menu.get('plan_mode') == 'test_preview' and value.plan_mode == 'formal':
        raise ValueError('测试预览不能直接提升为正式菜单，请读取早间最新上下文重新生成')
    if menu.get('plan_scope') != 'full_day_reference' or menu.get('quantification_status') != 'verified_estimate' or menu.get('valid_for_use') is not True:
        raise ValueError('候选必须明确为已完成核算的全天参考；剩余计划使用独立重算入口')
    if menu.get('reference_date') != value.target_date.isoformat(): raise ValueError('方案用途日期不一致')
    status = ctx['training_plan']['training_status']
    if menu.get('training_status', 'unknown') != status:
        raise ValueError('候选训练状态必须对应目标日已存状态；未知不能猜')
    if status == 'unknown' and menu.get('active_variant_id'):
        raise ValueError('目标日训练未知，不能强制选定训练分支')
    requested = ctx.get('dish_requests', {}).get('request_refs', [])
    fulfilled = menu.get('fulfilled_dish_requests', [])
    order = lambda refs: sorted(refs, key=lambda r:(r['id'], r['version'], r['dish']))
    if order(fulfilled) != order(requested): raise ValueError('目标日点菜必须逐项明确履行或保持待审核，不能静默忽略')
    for request in requested:
        if not any(request['dish'].casefold() in r.get('dish_title','').casefold() for r in menu.get('recipes', [])):
            raise ValueError('点菜请求未对应到具体菜式，需人工核对')
    known_references = {r['id'] for r in ctx['taste_library']['items']}
    for recipe in menu.get('recipes', []):
        if any(r.get('reference_id') not in known_references for r in recipe.get('reference_sources', [])):
            raise ValueError('菜式参考来源不在当前素材/实际记录/选入seed中')
    preferences = ctx['preferences']
    values = ctx['health_values']
    if any(r['data'].get('confirmed') and r['data'].get('kind') in ('allergy', 'constraint', 'dislike') for r in preferences) or str(values.get('忌口','')).strip() not in ('','无','没有','无忌口') or values.get('特殊健康情况','无') not in ('','无'):
        raise ValueError('有忌口或特殊健康情况时须先核对安全适用性，本入口不自动放行')
    for plan in [menu] + list(menu.get('variants') or []):
        if not plan.get('valid_for_use'): continue
        if not plan.get('recipes') or len(plan['recipes']) > 10: raise ValueError('餐次明细缺失或超出规划范围')
        for recipe in plan['recipes']:
            if not recipe.get('dish_title') or not recipe.get('portion_summary') or not recipe.get('preparation'): raise ValueError('菜式、核心份量与做法必须明确')
            if not 1 <= len(recipe.get('items',[])) <= 30: raise ValueError('缺少食物成分明细')
            for row in recipe['items']: CandidateItem.model_validate(row)
            if recipe.get('nutrition', {}).get('kcal', 0) > 1400: raise ValueError('单餐超出当前菜单执行上限，需重新分配而非巨大补餐')
            if recipe.get('unquantified_items'): raise ValueError('有未核算食物，不能按完整全天发布')
    from . import diet_rotation
    menu['rotation_validation'] = diet_rotation.validate(menu, ctx['rotation_context'])
    menu['numeric_validation'] = validate_menu(menu, ctx['targets']['daily'], ctx.get('pantry_constraints', {}))
    menu['pantry_constraints'] = ctx.get('pantry_constraints', {})
    menu.update(policy=policy, training_plan=ctx['training_plan'], food_history=ctx['food_history'],
                recent_three_days=ctx['recent_three_days'], independent_review=value.independent_review or {'status':'not_recorded'},
                intake_basis=snapshot, intake_snapshot_sha256=value.intake_snapshot_sha256,
                scope_notice='此为目标日期的一整天参考菜单，不是今天剩余应吃的量，不能叠加到已吃摄入。')
    diet_publication.label_menu(menu, value.plan_mode)
    result = diet_cycle.build(value.target_date.isoformat(),'Asia/Shanghai',force=True,
                              plan_mode=value.plan_mode, generate_menu=False)
    result.update(target_date=diet_day.current_diet_day().isoformat(), reference_date=value.target_date.isoformat(),
                  revision_of=value.expected_report_id, revision_reason=value.reason, next_meal=menu,
                  plan_mode=value.plan_mode, scores_settled=False,
                  publication_trigger='explicit_test_request' if value.plan_mode == 'test_preview' else 'morning_0700',
                  generated_at=db.now())
    return _save_revision(result,value.expected_report_id,value.idempotency_key,request_hash, expected_context_hash=value.context_hash)


def validate_current_plan(data):
    """CLI validation must not accept a caller-supplied obsolete target."""
    menu = data['next_meal']
    day = menu.get('reference_date') or data.get('reference_date') or data.get('target_date')
    if not day:
        raise ValueError('校验菜单必须注明目标日期')
    current = diet.calorie_target(target_date=day)
    supplied = data['reference_targets']
    if supplied.get('daily') != current.get('daily') or supplied.get('target_override') != current.get('target_override'):
        raise db.Conflict('参考目标已变化，请读取目标日最新上下文重新生成')
    result = validate_menu(menu, current['daily'])
    from . import diet_rotation
    result['rotation_validation'] = diet_rotation.validate(menu, context(day)['rotation_context'])
    return result
