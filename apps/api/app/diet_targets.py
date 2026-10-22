"""Explicit dated user targets, append-only and separate from formula estimates."""
from datetime import date
from pydantic import Field, model_validator
from . import db, diet_day, schemas
from .security import digest

VERSION = 'user-target-v1'

class DailyTargets(schemas.Strict):
    kcal: float = Field(gt=0, le=10000)
    protein_g: float = Field(gt=0, le=1000)
    fat_g: float = Field(gt=0, le=1000)
    carbs_g: float = Field(gt=0, le=2000)

class TargetOverride(schemas.Strict):
    effective_from: date
    daily: DailyTargets
    source: str = Field(min_length=1, max_length=2000)
    source_id: str = Field(min_length=1, max_length=250)
    allow_energy_mismatch: bool = False
    day_type_policy: str = Field(default="uniform", pattern="^uniform$")
    allocation_note: str = Field(default="训练日与休息日采用同一每日总目标；练前餐和练后补充计入全天预算，仅调整餐次分配。", max_length=1000)

    @model_validator(mode='after')
    def consistent(self):
        macro = 4*self.daily.protein_g + 9*self.daily.fat_g + 4*self.daily.carbs_g
        if abs(macro - self.daily.kcal) > 1 and not self.allow_energy_mismatch:
            raise ValueError('热量与三大营养素换算不一致，须由用户明确保留后标记 allow_energy_mismatch')
        return self

class TargetWrite(schemas.Strict):
    data: TargetOverride
    expected_target_id: str | None
    idempotency_key: str = Field(min_length=8, max_length=250)


def records():
    return db.records('diet_targets', 10000)['items']


def selected(day=None):
    day = str(day or diet_day.current_diet_day())
    rows = [r for r in records() if r.get('mode') == 'live' and r.get('kind') == 'diet_targets' and r['data']['effective_from'] <= day]
    return max(rows, key=lambda r:(r['data']['effective_from'], r['created_at'], r['id']), default=None)


def apply(base, row):
    if row is None:
        return base
    data = row['data']; daily = data['daily']
    macro = round(4*daily['protein_g'] + 9*daily['fat_g'] + 4*daily['carbs_g'], 4)
    delta = round(daily['kcal'] - macro, 4)
    note = '采用用户明确设定的每日目标；身体/活动公式仅保留为估算背景，不覆盖用户设定。'
    if abs(delta) > 1:
        note += f' 用户明确保留热量{daily["kcal"]:g} kcal；宏量4/4/9换算为{macro:g} kcal，差额{delta:g} kcal未分配，不推断其来源。'
    return {**base, 'version': VERSION, 'status': 'user_defined', 'daily': daily,
            'kcal': {'low': daily['kcal'], 'high': daily['kcal']}, 'steps': [],
            'method': '用户明确指定的单值目标；非公式计算或医学处方。', 'note': note,
            'target_override': {'id': row['id'], 'version': row['version'], **data},
            'scoring_context': data.get('scoring_context', base.get('scoring_context')),
            'energy_consistency': {'macro_kcal': macro, 'difference_kcal': delta, 'explicitly_retained': data['allow_energy_mismatch']},
            'input_refs': [*base.get('input_refs', []), {'id': row['id'], 'version': row['version']}]}


def save(value):
    value = TargetWrite.model_validate(value)
    payload = value.model_dump(mode='json')
    signature = digest(db.encode(payload).encode())
    key = 'diet:target:request:' + value.idempotency_key
    with db.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        prior = con.execute('SELECT value FROM runtime WHERE key=?', (key,)).fetchone()
        if prior:
            import json
            receipt = json.loads(prior['value'])
            if receipt['signature'] != signature:
                raise db.Conflict('同一目标幂等键内容冲突')
            return db.get_record(receipt['id'], 'diet_targets', con)
        if value.data.effective_from < diet_day.current_diet_day():
            raise ValueError('用户目标不能回填过去饮食日')
        rows = [db.unpack(r) for r in con.execute("SELECT * FROM records WHERE kind='diet_targets' AND deleted_at IS NULL ORDER BY created_at DESC,id DESC")]
        if (rows[0]['id'] if rows else None) != value.expected_target_id:
            raise db.Conflict('目标已变化，请重新读取后确认')
        identifier, stamp = db.uid(), db.now()
        from . import diet_energy, diet_tracking
        estimate = diet_energy.estimate(diet_tracking.health_state()[0])
        data = {**payload['data'], 'revision_of': value.expected_target_id,
                'target_revision': (rows[0]['data'].get('target_revision', 0) if rows else 0) + 1,
                'scoring_context': estimate.get('scoring_context')} 
        con.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                    (identifier, 'diet_targets', 'diet', None, 1, db.encode(data), stamp, stamp, 'live'))
        con.execute('INSERT INTO revisions VALUES(?,?,?,?)', (identifier, 1, db.encode(data), stamp))
        con.execute('INSERT INTO runtime VALUES(?,?)', (key, db.encode({'signature': signature, 'id': identifier})))
        db.audit(con, 'diet.target.saved', identifier, {'version': 1, 'effective_from': data['effective_from']})
        return db.get_record(identifier, 'diet_targets', con)


def register(app):
    @app.get('/api/v1/diet/targets')
    def listing():
        return {'items': records(), 'active': selected()}

    @app.post('/api/v1/diet/target-override', status_code=201)
    def create(value: TargetWrite):
        return save(value)
