"""Local structured writeback from a local operator; no model or network client."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Literal
from pydantic import Field
from . import config, db, diet, diet_cycle, schemas, diet_day, diet_publication
from .security import SafeError, digest


class ImageRef(schemas.Strict):
    id: str
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class AnalysisWrite(schemas.Strict):
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=250)
    image_refs: list[ImageRef] = Field(max_length=6)
    analysis: schemas.MealVisionOutput


class Settlement(schemas.Strict):
    target_date: date
    mode: Literal['morning_0700', 'score_only'] = 'morning_0700'


def save_report(con, data, day, key, request_hash):
    identifier = db.uid()
    version = con.execute("SELECT COALESCE(MAX(version),0)+1 FROM reports WHERE module='diet' AND business_date=? AND timezone='Asia/Shanghai'", (day,)).fetchone()[0]
    con.execute('INSERT INTO reports VALUES(?,NULL,?,?,?,?,?,?,?,?)', (identifier,'diet',day,'Asia/Shanghai',version,data.get('status','succeeded'),db.encode(data),db.now(),'live'))
    con.execute('INSERT INTO external_ingests VALUES(?,?,?)',(key,request_hash,identifier))
    db.audit(con,'chat.result_saved',identifier,{'provider':'local_operator'})
    return db.unpack(con.execute('SELECT * FROM reports WHERE id=?',(identifier,)).fetchone())


def existing(con,key,request_hash):
    prior=con.execute('SELECT * FROM external_ingests WHERE idempotency_key=?',(key,)).fetchone()
    if not prior: return None
    if prior['request_sha256']!=request_hash: raise db.Conflict('幂等键已用于其他结果')
    return db.unpack(con.execute('SELECT * FROM reports WHERE id=?',(prior['report_id'],)).fetchone())


def register(app):
    @app.get('/api/v1/providers')
    def providers():
        return {'agent':{'provider':'local_operator','status':'disabled','capabilities':{'vision':False},'detail':'仅接收本地操作者的结构化结果；不含自动识别或模型服务'},'vision':'manual_structured_writeback','scheduler':{'provider':'none','time':'07:00','timezone':'Asia/Shanghai','configured':False}}

    @app.post('/api/v1/diet/meals/{identifier}/analysis',status_code=201)
    def write_analysis(identifier: str, value: AnalysisWrite):
        payload=value.model_dump(mode='json')
        request_hash=digest(db.encode({'meal_id':identifier,**payload}).encode())
        with db.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            prior=existing(con,value.idempotency_key,request_hash)
            if prior: return prior
            meal=db.get_record(identifier,'meals',con)
            if meal['version']!=value.version: raise db.Conflict('餐食已修改，请按最新版本重新分析')
            expected={r.id:r.sha256 for r in value.image_refs}
            if len(expected)!=len(value.image_refs) or set(expected)!=set(meal['data']['assets']):
                raise SafeError('image_refs_mismatch','结果必须精确对应本餐全部图片',409)
            for aid,sha in expected.items():
                asset=con.execute("SELECT * FROM assets WHERE id=? AND module='diet' AND project_id IS NULL",(aid,)).fetchone()
                if not asset or asset['sha256']!=sha: raise SafeError('asset_changed','照片版本不匹配',409)
                path=(config.DATA/'assets'/asset['storage_key']).resolve()
                if not path.is_relative_to((config.DATA/'assets').resolve()) or not path.is_file() or digest(path.read_bytes())!=sha:
                    raise SafeError('asset_changed','照片文件已变化',409)
            result=value.analysis.model_dump(mode='json')
            if set(result['source_ids'])!={identifier}: raise SafeError('invalid_citations','source_ids 必须仅引用当前餐食',422)
            result['nutrition']=diet.normalize_label_nutrition(result['nutrition'])
            result.update(next_meal=None,activity_assessment=None,title='主聊天餐食分析',meal_id=identifier,provider='parent_chat',input_refs=[{'id':identifier,'version':value.version}],image_refs=[r.model_dump() for r in value.image_refs],reference_targets=diet.active_target(meal))
            result['product_refs'] = meal['data'].get('product_refs', [])
            day=diet_day.meal_diet_date(meal).isoformat()
            return save_report(con,result,day,value.idempotency_key,request_hash)

    @app.post('/api/v1/diet/settle',status_code=201)
    def settle(value: Settlement):
        if value.mode == 'score_only':
            raise SafeError('morning_scoring_required', '每日评分统一在北京时间07:00结算上一完整饮食日；晚间仅记录摄入与上下文，不提前评分', 422)
        today=diet_day.current_diet_day()
        if value.target_date>today: raise SafeError('future_settlement','不能提前生成未来日结',422)
        if value.mode == 'morning_0700':
            try:
                diet_publication.require_formal_window(value.target_date)
            except ValueError as error:
                raise SafeError('morning_publication_required', str(error), 422) from error
        day=value.target_date.isoformat(); key='parent:'+value.mode+':v1:'+day
        request_hash=digest(day.encode())
        with db.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if value.mode == 'morning_0700':
                reports = [db.unpack(r) for r in con.execute("SELECT * FROM reports WHERE module='diet' ORDER BY created_at DESC")]
                completed = diet_publication.successful_formal(reports, day)
                if completed: return completed
            prior=existing(con,key,request_hash)
            if prior: return prior
            result=diet_cycle.build(day,'Asia/Shanghai',force=True, plan_mode='formal',
                                    generate_menu=value.mode == 'morning_0700', settle_scores=True)
            result['publication_trigger'] = value.mode
            return save_report(con,result,day,key,request_hash)
