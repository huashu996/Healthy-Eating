"""Fifteen-day, evidence-bound target reviews. No scheduler or model invocation."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Literal
from pydantic import Field
from . import db, schemas, diet_day, diet_targets, diet_tracking, diet_policy
from .security import digest

VERSION = 'fortnightly-target-review-v1'
ZONE = ZoneInfo('Asia/Shanghai')

class PolicyWrite(schemas.Strict):
    baseline_date: date
    source_id: str = Field(min_length=1, max_length=250)
    expected_target_id: str
    idempotency_key: str = Field(min_length=8, max_length=250)

class ReviewWrite(schemas.Strict):
    context_hash: str
    expected_target_id: str
    idempotency_key: str = Field(min_length=8, max_length=250)
    decision: Literal['hold', 'adjust']
    reason: str = Field(min_length=10, max_length=4000)
    confidence: Literal['low', 'moderate', 'high']
    daily: diet_targets.DailyTargets | None = None
    # A positive assertion is required for a reduction, never inferred from silence.
    recovery_and_adherence_checked: bool = False
    confounders: list[str] = Field(default_factory=list, max_length=20)
    source_id: str = Field(min_length=1, max_length=250)


def _rows(kind):
    return [r for r in db.records(kind, 10000)['items'] if r['mode'] == 'live']


def policy():
    rows = _rows('diet_target_review_policy')
    return max(rows, key=lambda r: (r['created_at'], r['id']), default=None)


def history():
    return sorted(_rows('diet_target_reviews'), key=lambda r:(r['data']['review_date'], r['created_at']), reverse=True)


def _insert(con, kind, data):
    identifier, stamp = db.uid(), db.now()
    con.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                (identifier, kind, 'diet', None, 1, db.encode(data), stamp, stamp, 'live'))
    con.execute('INSERT INTO revisions VALUES(?,?,?,?)', (identifier, 1, db.encode(data), stamp))
    db.audit(con, kind+'.saved', identifier, {'version':1})
    return db.get_record(identifier, kind, con)


def _receipt(con, key, signature):
    import json
    row = con.execute('SELECT value FROM runtime WHERE key=?', (key,)).fetchone()
    if row:
        value = json.loads(row['value'])
        if value['signature'] != signature:
            raise db.Conflict('同一复核幂等键内容冲突')
        return db.get_record(value['id'], con=con)


def _save_receipt(con, key, signature, row):
    con.execute('INSERT INTO runtime VALUES(?,?)', (key, db.encode({'signature':signature,'id':row['id']})))


def enable(value):
    value = PolicyWrite.model_validate(value)
    payload = value.model_dump(mode='json'); signature = digest(db.encode(payload).encode())
    key = 'diet:review:enable:'+value.idempotency_key
    with db.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        prior = _receipt(con, key, signature)
        if prior: return prior
        if policy(): raise db.Conflict('复核策略已启用，不重置原有周期')
        target = diet_targets.selected(value.baseline_date)
        if not target or target['id'] != value.expected_target_id:
            raise db.Conflict('目标已变化，请重新读取')
        if value.baseline_date != diet_day.now_beijing().date():
            raise ValueError('基线须为实际启用的北京时间日期')
        row = _insert(con, 'diet_target_review_policy', {
            'version':VERSION, **payload, 'timezone':'Asia/Shanghai', 'interval_days':15,
            'review_time':'07:00', 'baseline_targets':target['data']['daily'],
            'baseline_target_ref':{'id':target['id'],'version':target['version']},
            'managed_by':'existing_parent_0700_workflow', 'external_model_called':False})
        _save_receipt(con,key,signature,row)
        return row


def status():
    p = policy()
    if not p: return {'enabled':False, 'due':False, 'version':VERSION}
    reviews = [r for r in history() if r['data']['policy_id'] == p['id']]
    baseline = date.fromisoformat(p['data']['baseline_date'])
    completed = max((r['data']['cycle_index'] for r in reviews), default=0)
    anchor = date.fromisoformat(reviews[0]['data']['review_date']) if reviews else baseline
    next_day = anchor + timedelta(days=15)
    due_at = datetime.combine(next_day, datetime.min.time(), ZONE).replace(hour=7)
    now = diet_day.now_beijing()
    return {'enabled':True, 'version':VERSION, 'policy_id':p['id'], 'baseline_date':str(baseline),
            'timezone':str(ZONE), 'interval_days':15, 'next_review_at':due_at.isoformat(),
            'due':now>=due_at, 'last_review':{k:reviews[0]['data'].get(k) for k in ('review_date','reviewed_at','decision','reason','confidence','next_review_at')} if reviews else None,
            'cycle_index':completed+1,
            'review_date':now.date().isoformat(), 'history_count':len(reviews)}


def _measurements(start, end):
    points = {'weight':{}, 'body_fat':{}}
    all_rows = _rows('facts') + _rows('body_checkins')
    for row in sorted(all_rows, key=lambda r:(r['updated_at'],r['id'])):
        data = row['data']
        if row['kind']=='facts' and data.get('category')!='health': continue
        measured = data.get('measured_on') if row['kind']=='body_checkins' else data.get('observed_at')
        try: day = date.fromisoformat(measured or '')
        except (ValueError,TypeError): continue
        if day>end: continue
        fields = [('weight',data.get('weight_kg')),('body_fat',data.get('body_fat_pct'))] if row['kind']=='body_checkins' else [('weight' if data.get('key')=='体重' else 'body_fat' if data.get('key')=='体脂率' else 'other',data.get('value'))]
        for kind, value in fields:
            if kind not in points: continue
            try: number = float(value)
            except (TypeError,ValueError): continue
            if not (10<=number<=500 if kind=='weight' else 1<=number<=75): continue
            if (kind=='weight' and day>=start) or kind=='body_fat':
                points[kind][str(day)]={'date':str(day),'value':number,'ref':{'id':row['id'],'version':row['version']}}
    return points


def context():
    s = status()
    if not s['enabled']: return s
    day = date.fromisoformat(s['review_date']); end=day-timedelta(days=1); start=day-timedelta(days=14)
    with db.connect() as con:
        reports=[db.unpack(r) for r in con.execute("SELECT * FROM reports WHERE module='diet' AND mode='live' ORDER BY created_at DESC")]
    meals=[r for r in _rows('meals') if r['data'].get('eaten_fraction',1)>0]
    days=diet_tracking.review_days(start,end,reports,meals,{},calculate=False,timezone=str(ZONE))
    complete=[]
    for entry in days:
        totals=entry['totals']; kcal=totals.get('kcal')
        ok=entry['finished'] and entry['meals']>0 and entry['meals']==entry['analyzed'] and all(totals.get(k) and totals[k]['coverage']==entry['meals'] for k in ('kcal','protein_g','fat_g','carbs_g'))
        ok=bool(ok and kcal['low']>0 and (kcal['high']-kcal['low'])/((kcal['high']+kcal['low'])/2)<=.2)
        entry['adequate_for_review']=ok
        if ok: complete.append(entry)
    points=_measurements(start,end)
    split=str(start+timedelta(days=7)); weeks=[[v for k,v in points['weight'].items() if (k<split)==(i==0)] for i in range(2)]
    means=[sum(v['value'] for v in week)/len(week) if week else None for week in weeks]
    loss=round(means[0]-means[1],4) if all(v is not None for v in means) else None
    bf=max(points['body_fat'].values(),key=lambda r:r['date'],default=None)
    missing=[]
    if any(len(w)<4 for w in weeks): missing.append('每个7日区间至少4个不同日期的体重')
    if len(complete)<10 or any(sum((e['date']<split)==(i==0) for e in complete)<4 for i in range(2)):
        missing.append('14日内至少10日完整实际摄入且每周至少4日，营养范围不过宽')
    if not bf or (day-date.fromisoformat(bf['date'])).days>30: missing.append('30日内有实际测量日期的体脂数据（仅作背景，不根据单次波动调量）')
    target=diet_targets.selected(day)
    if not target: missing.append('当前明确每日目标')
    mean_intake=sum((e['totals']['kcal']['low']+e['totals']['kcal']['high'])/2 for e in complete)/len(complete) if complete else None
    payload={**s,'policy':policy(),'target':target,'window':{'start':str(start),'end':str(end)},
             'weight':{'weeks':weeks,'weekly_means_kg':means,'loss_kg_per_week':loss},
             'body_fat':bf,'intake_days':days,'complete_intake_days':len(complete),'mean_intake_kcal':mean_intake,
             'adequate':not missing,'missing':missing,'policy_hash':diet_policy.get_policy()['policy_hash'],
             'skill_hash':diet_policy.get_policy()['skill_hash'],
             'health_values':diet_tracking.health_state()[0],
             'profile_refs':[{'id':r['id'],'version':r['version']} for r in _rows('facts')],
             'guidance':{'desired_loss_kg_per_week':[.3,.5], 'max_adjustment_kcal':150,
             'threshold_status':'conservative software heuristics, not validated clinical thresholds',
             'body_fat_role':'noisy context only; no single BIA change drives targets',
             'hold_default':True,'agent_review_required':True,'external_model_called':False}}
    payload['context_hash']=digest(db.encode(payload).encode())
    return payload


def commit(value):
    value=ReviewWrite.model_validate(value); payload=value.model_dump(mode='json')
    signature=digest(db.encode(payload).encode()); key='diet:review:commit:'+value.idempotency_key
    with db.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        prior=_receipt(con,key,signature)
        if prior:return prior
        ctx=context()
        if not ctx.get('due'):raise ValueError('尚未到15日复核时间，或本周期已经完成')
        if diet_day.now_beijing().hour < 7:
            raise ValueError('复核只能在北京时间07:00后，避免读取未结束饮食日')
        if ctx['context_hash']!=value.context_hash or not ctx['target'] or ctx['target']['id']!=value.expected_target_id:
            raise db.Conflict('复核依据或目标已变化，请重新读取')
        old=ctx['target']['data']['daily']; new=value.daily.model_dump() if value.daily else None
        new_target=None
        if any(r['data']['effective_from']>ctx['review_date'] for r in diet_targets.records()):
            raise db.Conflict('存在未来目标版本，须先协调目标生效安排')
        if value.decision=='hold':
            if new is not None:raise ValueError('保留目标不得提交新目标')
        else:
            if not ctx['adequate'] or value.confidence=='low' or not new:
                raise ValueError('资料不足或低置信度只允许保留原目标')
            health=ctx.get('health_values',{})
            if health.get('特殊健康情况','无') not in ('','无') or ('年龄' in health and not 19<=float(health['年龄'])<=64):
                raise ValueError('特殊健康或年龄背景需要个别评估，只能保留目标')
            delta=new['kcal']-old['kcal']
            if not 100<=abs(delta)<=150:raise ValueError('每次热量变化仅允许100–150 kcal')
            if new['protein_g']!=old['protein_g'] or new['fat_g']!=old['fat_g']:
                raise ValueError('周期复核保护当前个体化蛋白与脂肪，改变分配需另行明确评估')
            if abs(new['kcal']-(4*new['protein_g']+9*new['fat_g']+4*new['carbs_g']))>.01:
                raise ValueError('三大营养素必须精确匹配热量')
            if new['carbs_g']<130 or new['fat_g']*9/new['kcal']<.2:
                raise ValueError('分配超出保守营养保护边界')
            loss=ctx['weight']['loss_kg_per_week']; actual=ctx['mean_intake_kcal']
            if not value.recovery_and_adherence_checked or value.confounders:
                raise ValueError('须核对饮食执行、恢复与体重干扰因素；存在干扰时保留并个别评估')
            if abs(actual-old['kcal'])>old['kcal']*.1:
                raise ValueError('实际摄入偏离目标或可能漏报时不自动改目标')
            if delta<0:
                if loss is None or loss>=.2:raise ValueError('减重已接近目标速度，不继续削减')
                # Trend-based approximation only; exercise gross MET is never used.
                maintenance=actual+max(0,loss)*7700/7
                baseline=ctx['policy']['data']['baseline_targets']['kcal']
                if new['kcal']<baseline-300 or new['kcal']<maintenance*.8 or maintenance-new['kcal']>500:
                    raise ValueError('累计削减或趋势估算缺口达到保护上限，需个别评估')
            elif loss is None or loss<=.6:
                raise ValueError('趋势未达到过快下降的复核缓冲阈值，保留原目标')
            target_data={**ctx['target']['data'],'daily':new,'effective_from':ctx['review_date'],
                         'source':'15日依据复核：'+value.reason,'source_id':value.source_id,
                         'allow_energy_mismatch':False,'revision_of':ctx['target']['id'],
                         'target_revision':ctx['target']['data'].get('target_revision',0)+1}
            new_target=_insert(con,'diet_targets',target_data)
        row=_insert(con,'diet_target_reviews',{'version':VERSION,**payload,
              'policy_id':ctx['policy_id'],'cycle_index':ctx['cycle_index'],'review_date':ctx['review_date'],
              'scheduled_for':ctx['next_review_at'],'reviewed_at':db.now(),
              'next_review_at':datetime.combine(date.fromisoformat(ctx['review_date'])+timedelta(days=15),datetime.min.time(),ZONE).replace(hour=7).isoformat(),
              'old_target_ref':{'id':ctx['target']['id'],'version':ctx['target']['version']},
              'new_target_ref':{'id':new_target['id'],'version':new_target['version']} if new_target else None,
              'evidence':ctx,'external_model_called':False,'reviewer':'dot_agent'})
        _save_receipt(con,key,signature,row)
        return row


def require_review():
    if status().get('due'):
        raise ValueError('15日目标复核已到期：先读取target-review-context并由dot提交复核；资料不足记录hold后继续07流程')


def register(app):
    @app.get('/api/v1/diet/target-review')
    def get_status():return status()
    @app.get('/api/v1/diet/target-review/context')
    def get_context():return context()
    @app.post('/api/v1/diet/target-review/enable',status_code=201)
    def set_policy(value:PolicyWrite):return enable(value)
    @app.post('/api/v1/diet/target-review/commit',status_code=201)
    def save_review(value:ReviewWrite):return commit(value)
