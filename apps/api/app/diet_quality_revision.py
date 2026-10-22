"""Audited photo-portion evidence correction; preserves actual macros and targets."""
from copy import deepcopy
from . import db, diet, schemas, external_api
from .security import digest

def revise(payload):
    required={'meal_id','expected_analysis_id','expected_analysis_version','expected_meal_version','quality_evidence','source_id','reason','idempotency_key'}
    if set(payload)!=required or not payload['source_id'] or len(payload['reason'])<10 or len(payload['idempotency_key'])<8:
        raise ValueError('需要明确授权、版本、依据与幂等键')
    quality=schemas.MealQualityEvidence.model_validate(payload['quality_evidence']).model_dump(mode='json')
    if not quality['covers_entire_meal'] or not quality['supplements_excluded']:
        raise ValueError('必须核验整餐，且补剂不计入食物组')
    signature=digest(db.encode(payload).encode())
    with db.connect(track_mirror=False) as con:
        con.execute('BEGIN IMMEDIATE')
        prior=external_api.existing(con,payload['idempotency_key'],signature)
        if prior:return {'report_id':prior['id'],'version':prior['version'],'reused':True}
        meal=db.get_record(payload['meal_id'],'meals',con)
        reports=[db.unpack(r) for r in con.execute("SELECT * FROM reports WHERE module='diet' ORDER BY created_at DESC")]
        report=diet.current_analysis(meal,reports)
        if meal['version']!=payload['expected_meal_version'] or not report or report['id']!=payload['expected_analysis_id'] or report['version']!=payload['expected_analysis_version']:
            raise db.Conflict('餐食或分析版本已改变')
        # Verify the actual input bytes have not changed since the analysis.
        from . import config
        for ref in report['data'].get('image_refs',[]):
            asset=con.execute('SELECT * FROM assets WHERE id=?',(ref['id'],)).fetchone()
            if not asset or asset['sha256']!=ref['sha256'] or digest((config.DATA/'assets'/asset['storage_key']).read_bytes())!=ref['sha256']:
                raise db.Conflict('餐图内容已改变')
        data=deepcopy(report['data']);data['quality_evidence']=quality
        data['quality_revision']={'source_id':payload['source_id'],'reason':payload['reason'],'previous_analysis_id':report['id'],'at':db.now()}
        saved=external_api.save_report(con,data,report['business_date'],payload['idempotency_key'],signature)
        db.audit(con,'diet.quality_revision',saved['id'],data['quality_revision'])
        from . import diet_mirror
        diet_mirror.mark_dirty(con)
    return {'report_id':saved['id'],'version':saved['version'],'reused':False}
