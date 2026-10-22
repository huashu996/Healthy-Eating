"""Explicit user-requested recipe correction, without rerunning the daily cycle."""
from copy import deepcopy
from . import db, diet, diet_planning, diet_policy
from .security import digest

def revise(payload):
    required={'expected_report_id','expected_report_version','idempotency_key','source_id','reason','recipes','caveat'}
    if set(payload)!=required or len(payload['idempotency_key'])<8 or not payload['source_id']:
        raise ValueError('需要完整修订来源、版本和幂等键')
    signature=digest(db.encode(payload).encode())
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for row in c.execute("SELECT * FROM audit_events WHERE action='diet.recipe_revision' AND target=?",(payload['expected_report_id'],)):
            import json
            a=json.loads(row['safe_metadata'])
            if a.get('idempotency_key')==payload['idempotency_key']:
                if a['signature']!=signature: raise db.Conflict('幂等键内容冲突')
                return {'report_id':payload['expected_report_id'],'version':a['new_version'],'reused':True}
        row=c.execute("SELECT * FROM reports WHERE id=? AND module='diet'",(payload['expected_report_id'],)).fetchone()
        if not row: raise db.Conflict('菜单不存在')
        report=db.unpack(row)
        if report['version']!=payload['expected_report_version']: raise db.Conflict('菜单版本已变化')
        data=deepcopy(report['data']); before=deepcopy(data.get('next_meal'))
        if not before or before.get('valid_for_use') is not True: raise ValueError('需先有有效菜单')
        recipes=payload['recipes']
        if [(r['meal_type'],r['dish_title']) for r in recipes]!=[(r['meal_type'],r['dish_title']) for r in before['recipes']]:
            raise ValueError('配方修订不能新增、删除或更换菜式')
        if any(r.get('items') != old.get('items') for r, old in zip(recipes, before['recipes'])):
            raise ValueError('食材或份量变化须使用完整菜单修订入口，重新核验全部分支与近期重复')
        if before.get('variants') and recipes != before['recipes']:
            raise ValueError('含分支菜单须使用完整菜单修订入口，不能只改变根菜单')
        menu=deepcopy(before);menu['recipes']=deepcopy(recipes)
        from .diet_quantified import total, compare
        for r in menu['recipes']:
            for item in r['items']: diet_planning.CandidateItem.model_validate(item)
            r['nutrition']=total(r['items'])
        menu['daily_nutrition']=total([i for r in recipes for i in r['items']])
        target=diet.overview()['target']['daily']
        menu['target_comparison']=compare(menu['daily_nutrition'],target)
        menu['numeric_validation']=diet_planning.validate_menu(menu,target)
        menu['caveat']=payload['caveat']; menu['policy']=diet_policy.get_policy()
        menu['independent_review']={'status':'software_revalidated','scope':'source amounts, meal and daily sums'}
        data['next_meal']=menu
        version=report['version']+1
        data.setdefault('recipe_revisions',[]).append({'at':db.now(),'source_id':payload['source_id'],'reason':payload['reason'],'previous':before,'version':version})
        c.execute('UPDATE reports SET data=?,version=? WHERE id=? AND version=?',(db.encode(data),version,report['id'],report['version']))
        db.audit(c,'diet.recipe_revision',report['id'],{'idempotency_key':payload['idempotency_key'],'signature':signature,'new_version':version,'source_id':payload['source_id']})
        return {'report_id':report['id'],'version':version,'daily_nutrition':menu['daily_nutrition'],'comparison':menu['target_comparison'],'reused':False}
