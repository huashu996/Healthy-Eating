"""Explicit, audited correction of a saved day score; never regenerate a menu."""
from copy import deepcopy
from datetime import date
import json
from . import db, diet, diet_tracking, diet_day
from .security import digest


def revise(payload):
    required = {'date', 'expected_report_id', 'expected_report_version', 'idempotency_key', 'source_id', 'reason'}
    estimate = payload.get('score_mode') == 'midpoint_estimate'
    if set(payload) != required | ({'score_mode'} if estimate else set()) or not payload['source_id'] or len(payload['reason']) < 10 or len(payload['idempotency_key']) < 8:
        raise ValueError('需要日期、明确授权来源、原因、版本及幂等键')
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
    meals = db.records('meals', 10000)['items']
    revised = diet_tracking.review_days(selected, selected, reports, meals, diet.active_target())[0]
    if estimate:
        from . import diet_score_estimate
        revised.update(diet_score_estimate.build(revised, source_id=payload['source_id'], reason=payload['reason'], created_at=db.now()))
    elif revised.get('score') is None:
        raise ValueError('该日仍无足够可评证据：' + '；'.join(revised['score_readiness']['missing']))
    revised['settled_at'] = previous.get('settled_at') or db.now()
    revised['corrected_at'] = db.now()
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
