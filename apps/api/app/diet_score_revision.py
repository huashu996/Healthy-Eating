"""Explicit, audited correction of a saved day score; never regenerate a menu."""
from copy import deepcopy
from datetime import date
import json
from . import db, diet, diet_tracking, diet_day, diet_scoring, diet_score_estimate, diet_policy
from .security import digest


def prepare_historical_override(previous, actual, *, source_id, reason, created_at):
    """Regrade frozen evidence only; reject stale inputs rather than reinterpret food."""
    for key in ('totals', 'input_refs', 'analysis_refs', 'target', 'score_context'):
        if actual.get(key) != previous.get(key):
            raise db.Conflict('历史统一评分的原始依据已变化：' + key)
    revised = deepcopy(previous)
    for key in ('estimated_score', 'estimated_components', 'estimate_notice', 'estimate_audit',
                'score_raw_points', 'score_assessed_maximum', 'alcohol_penalty'):
        revised.pop(key, None)
    revised.update(diet_scoring.score(previous['totals'], previous['target'], previous['meals'],
        previous['analyzed'], previous['finished'], context=deepcopy(previous['score_context']),
        quality=deepcopy(previous['score_quality_evidence']), version=diet_scoring.VERSION))
    previous_estimated = diet_score_estimate.valid(previous)
    revised['score_policy_override'] = {'kind': 'explicit_historical_revision',
        'score_version': diet_scoring.VERSION, 'previous_score_version': previous['score_version'],
        'source_id': source_id, 'reason': reason, 'created_at': created_at,
        'previous_estimated': previous_estimated,
        'original_target': deepcopy(previous['target']), 'original_context': deepcopy(previous['score_context'])}
    if previous_estimated and revised.get('score') is not None:
        # A new formula is not better measurement: keep the existing uncertainty label.
        revised['score_policy_override']['recalculated_readiness'] = deepcopy(revised['score_readiness'])
        revised['score_policy_override']['retained_estimate_audit'] = deepcopy(previous['estimate_audit'])
        revised.update(score=None, score_maximum=None, score_coverage_pct=0,
                       score_scope='unavailable', state='已结算（估算）',
                       score_readiness={'status': 'estimate_retained', 'missing': []})
        revised['components'] = [p for p in revised['components'] if p['key'] != 'alcohol']
        for key in ('score_raw_points', 'score_assessed_maximum', 'alcohol_penalty'):
            revised.pop(key, None)
    return revised


def revise(payload):
    required = {'date', 'expected_report_id', 'expected_report_version', 'idempotency_key', 'source_id', 'reason'}
    estimate = payload.get('score_mode') == 'midpoint_estimate'
    override = payload.get('score_version_override')
    optional = ({'score_mode'} if estimate else set()) | ({'score_version_override'} if override else set())
    if set(payload) != required | optional or not payload['source_id'] or len(payload['reason']) < 10 or len(payload['idempotency_key']) < 8:
        raise ValueError('需要日期、明确授权来源、原因、版本及幂等键')
    if override is not None:
        permission = diet_policy.get_policy().get('historical_scoring_revision', {})
        if override != diet_scoring.VERSION or permission.get('score_version') != override or payload['source_id'] != permission.get('source_id'):
            raise ValueError('历史版本覆盖需要当前明确授权来源和指定评分版本')
    selected = date.fromisoformat(payload['date'])
    if selected >= diet_day.current_diet_day():
        raise ValueError('仅允许用户明确要求更正已结束饮食日的评分')
    signature = digest(db.encode(payload).encode())
    with db.connect(track_mirror=False) as con:
        audits = con.execute("SELECT * FROM audit_events WHERE action='diet.score_revision' AND target=?", (payload['expected_report_id'],)).fetchall()
        for row in audits:
            saved = json.loads(row['safe_metadata'])
            if saved.get('idempotency_key') == payload['idempotency_key']:
                if saved['signature'] != signature: raise db.Conflict('幂等键内容冲突')
                return {**saved['result'], 'reused': True}
        reports = [db.unpack(r) for r in con.execute("SELECT * FROM reports WHERE module='diet' AND mode='live' ORDER BY created_at DESC,id DESC")]
    report = next((r for r in reports if r['id'] == payload['expected_report_id']), None)
    if not report or report['version'] != payload['expected_report_version']:
        raise db.Conflict('报告版本已变化')
    data = deepcopy(report['data'])
    if not data.get('scores_settled') or data.get('plan_mode') == 'test_preview':
        raise ValueError('只能更正已经结算的非测试记录')
    previous = next((d for d in data.get('review_days', []) if d['date'] == payload['date']), None)
    if not previous:
        raise ValueError('此入口只更正用户指定的已有结算日，不重算其他历史分数')
    revision_options = {}
    if override:
        previously_scored = (diet_scoring.number(previous.get('score')) and previous['score'] <= 100
                             or diet_score_estimate.valid(previous))
        reference, context = previous.get('target'), previous.get('score_context')
        if (not previously_scored or not diet_scoring.saved_version_supported(previous)
                or not isinstance(reference, dict) or any(not diet_scoring.number(reference.get(k), positive=True) for k in diet_scoring.MACROS)
                or not isinstance(context, dict)):
            raise ValueError('版本统一仅适用于已有有效评分、完整原日目标与适用性背景的存档')
        revision_options = {'score_version_override': override,
            'scoring_reference_override': {'daily': deepcopy(reference), 'scoring_context': deepcopy(context)}}
    meals = db.records('meals', 10000)['items']
    revised = diet_tracking.review_days(selected, selected, reports, meals, diet.active_target(), **revision_options)[0]
    corrected_at = db.now()
    if override:
        revised = prepare_historical_override(previous, revised, source_id=payload['source_id'],
                                              reason=payload['reason'], created_at=corrected_at)
    if estimate:
        revised.update(diet_score_estimate.build(revised, source_id=payload['source_id'], reason=payload['reason'], created_at=db.now()))
    elif revised.get('score') is None:
        raise ValueError('该日仍无足够可评证据：' + '；'.join(revised['score_readiness']['missing']))
    revised['settled_at'] = previous.get('settled_at') or db.now()
    revised['corrected_at'] = corrected_at
    revised['correction_source_id'] = payload['source_id']
    revised['foods'] = previous.get('foods', [])
    data['review_days'] = [revised if d['date'] == payload['date'] else d for d in data['review_days']]
    if data.get('previous_day', {}).get('date') == payload['date']:
        data['previous_day'] = deepcopy(revised)
    data.setdefault('score_revisions', []).append({'at': revised['corrected_at'], 'date': payload['date'],
        'source_id': payload['source_id'], 'reason': payload['reason'], 'previous': previous})
    version = report['version'] + 1
    result = {'report_id': report['id'], 'version': version, 'date': payload['date'],
              'score': revised['score'], 'score_maximum': revised['score_maximum'], 'score_scope': revised['score_scope'], 'reused': False}
    if estimate:
        result.update(estimated_score=revised['estimated_score'], score_status='estimated')
    with db.connect(track_mirror=False) as con:
        con.execute('BEGIN IMMEDIATE')
        for table, refs in (('records', revised['input_refs']), ('reports', revised['analysis_refs'])):
            for ref in refs:
                current = con.execute(f'SELECT version FROM {table} WHERE id=?', (ref['id'],)).fetchone()
                if not current or current['version'] != ref['version']: raise db.Conflict('计算期间原始记录已变化')
        current_meals = [db.unpack(r) for r in con.execute("SELECT * FROM records WHERE kind='meals' AND deleted_at IS NULL AND mode='live'")]
        actual_ids = sorted(m['id'] for m in current_meals if diet_day.meal_diet_date(m) == selected and m['data']['execution'] not in ('planned','skipped','replaced'))
        expected_ids = sorted(m['id'] for m in meals if diet_day.meal_diet_date(m) == selected and m['data']['execution'] not in ('planned','skipped','replaced'))
        if actual_ids != expected_ids: raise db.Conflict('计算期间餐食清单已变化')
        changed = con.execute('UPDATE reports SET data=?,version=? WHERE id=? AND version=?',
                             (db.encode(data), version, report['id'], report['version']))
        if changed.rowcount != 1: raise db.Conflict('报告被并发更新')
        db.audit(con, 'diet.score_revision', report['id'], {'signature': signature, 'idempotency_key': payload['idempotency_key'],
            'source_id': payload['source_id'], 'reason': payload['reason'], 'result': result})
        from . import diet_mirror
        diet_mirror.mark_dirty(con)  # Coordinator deploys compatible viewer before authorized sync.
    return result
