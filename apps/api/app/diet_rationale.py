"""Evidence-based explanation only; never generate meals or calculate scores."""
from copy import deepcopy
from . import db
from .security import digest

SOURCES = [
 {"title":"NIH ODS：Omega-3脂肪酸","url":"https://ods.od.nih.gov/factsheets/Omega3FattyAcids-HealthProfessional/","checked_on":"2026-10-13"},
 {"title":"NIH ODS：维生素C","url":"https://ods.od.nih.gov/factsheets/VitaminC-HealthProfessional/","checked_on":"2026-10-13"},
 {"title":"WHO：健康饮食","url":"https://www.who.int/news-room/fact-sheets/detail/healthy-diet","checked_on":"2026-10-13"},
 {"title":"NIH ODS：膳食补充剂","url":"https://ods.od.nih.gov/factsheets/WYNTK-Consumer/","checked_on":"2026-10-13"},
 {"title":"NIH ODS：运动营养","url":"https://ods.od.nih.gov/factsheets/ExerciseAndAthleticPerformance-HealthProfessional/","checked_on":"2026-10-13"},
]

def revise(payload):
    """Explicit explanation correction with CAS, idempotency and retained audit.

    Does not create a second formal plan or modify its timing, score, portions,
    variants, targets, nutrient sums, source versions or food records.
    """
    allowed={"expected_report_id","expected_report_version","idempotency_key","source_id","reason_summary","reasons","sources"}
    if set(payload)-{"caveat"}!=allowed: raise ValueError("只允许修改说明及依据，不能夹带菜单或数值")
    if not payload['source_id'] or len(payload['idempotency_key'])<8: raise ValueError("需要明确来源及幂等键")
    if not isinstance(payload['reason_summary'],str) or not 1<=len(payload['reason_summary'])<=4000: raise ValueError("说明长度无效")
    if not isinstance(payload['reasons'],list) or not 1<=len(payload['reasons'])<=10: raise ValueError("需要分条依据")
    for source in payload['sources']:
        if not isinstance(source,dict) or not str(source.get('url','')).startswith('https://'): raise ValueError("依据需HTTPS来源")
    if "caveat" in payload and (not isinstance(payload["caveat"],str) or not 1<=len(payload["caveat"])<=4000): raise ValueError("附注长度无效")
    signature=digest(db.encode(payload).encode())
    with db.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        old=con.execute("SELECT * FROM audit_events WHERE action='diet.rationale_revision' AND target=?",(payload['expected_report_id'],)).fetchall()
        for row in old:
            import json
            a=json.loads(row['safe_metadata'])
            if a.get('idempotency_key')==payload['idempotency_key']:
                if a.get('signature')!=signature: raise db.Conflict('幂等键内容冲突')
                return {"report_id":payload['expected_report_id'],"version":a['new_version'],"reused":True}
        row=con.execute("SELECT * FROM reports WHERE id=? AND module='diet'",(payload['expected_report_id'],)).fetchone()
        if not row: raise db.Conflict('目标菜单不存在')
        report=db.unpack(row)
        if report['version']!=payload['expected_report_version']: raise db.Conflict('菜单版本已变化')
        data=deepcopy(report['data']); menu=data.get('next_meal')
        if not menu or menu.get('valid_for_use') is not True: raise ValueError('没有有效菜单可解释')
        fields=['reason_summary','reasons','sources'] + (['caveat'] if 'caveat' in payload else [])
        before={k:deepcopy(menu.get(k)) for k in fields}
        for k in before: menu[k]=deepcopy(payload[k])
        stamp=db.now(); version=report['version']+1
        data.setdefault('rationale_revisions',[]).append({"at":stamp,"source_id":payload['source_id'],"previous":before,"version":version})
        con.execute('UPDATE reports SET data=?,version=? WHERE id=? AND version=?',(db.encode(data),version,report['id'],report['version']))
        db.audit(con,'diet.rationale_revision',report['id'],{'idempotency_key':payload['idempotency_key'],'signature':signature,'new_version':version,'source_id':payload['source_id'],'modified_fields':list(before)})
        return {"report_id":report['id'],"version":version,"reused":False}
