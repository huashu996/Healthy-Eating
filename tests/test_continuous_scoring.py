"""Synthetic v8 regressions; no real profile, targets or intake are bundled."""
from copy import deepcopy
from decimal import Decimal
import math
import pytest
from app import diet_scoring as scoring, diet_score_estimate as estimate

TARGET={'kcal':2000,'protein_g':150,'fat_g':60,'carbs_g':215}
CONTEXT={'applicable':True,'weight_kg':75,'training':True}
REFS={key:scoring.RULES['structure'][key] for key in scoring.CORE_FOODS}

def values(**changes):
 return {key:{'low':v,'high':v,'coverage':1} for key,v in {**TARGET,**changes}.items()}

def quality(**changes):
 return scoring.aggregate_quality([({'quality_evidence':{'covers_entire_meal':True,'supplements_excluded':True,'confidence':'estimated','basis':'Synthetic complete food evidence',**{k:{'low':v,'high':v} for k,v in REFS.items()},**changes}},1)])

def assess(n=None,q=None,**kwargs):
 return scoring.score(n or values(),TARGET,1,1,False,context=CONTEXT,quality=q or quality(),**kwargs)

@pytest.mark.parametrize('key,nutrient,label,unit',scoring.TARGET_PARTS)
@pytest.mark.parametrize('ratio',[0,.5,.6,.600001,.75,.9,.949999,.95,1,1.05,1.050001,1.1,1.3,1.399999,1.4,2])
def test_macro_formula_boundaries(key,nutrient,label,unit,ratio):
 d=abs(Decimal(str(ratio))-1);factor=max(Decimal(0),min(Decimal(1),(Decimal('.40')-d)/Decimal('.35')))
 actual=scoring.target_points(float(Decimal(str(TARGET[nutrient]))*Decimal(str(ratio))),TARGET[nutrient],key)
 assert actual==pytest.approx(float(factor)*scoring.RULES[key]['maximum'],abs=1e-11)

@pytest.mark.parametrize('key,nutrient,label,unit',scoring.TARGET_PARTS)
def test_macro_symmetric_monotonic(key,nutrient,label,unit):
 t=TARGET[nutrient]
 lower=[scoring.target_points(t*(1-d/1000),t,key) for d in range(1001)]
 upper=[scoring.target_points(t*(1+d/1000),t,key) for d in range(1001)]
 assert lower==sorted(lower,reverse=True)
 assert lower==pytest.approx(upper,abs=1e-11)
 assert min(lower)==0 and max(lower)==scoring.RULES[key]['maximum']

@pytest.mark.parametrize('key',scoring.CORE_FOODS)
@pytest.mark.parametrize('ratio',[0,.1,.5,.9,.95,1,1.05,1.4,2])
def test_food_proportion_caps_without_excess_penalty(key,ratio):
 assert scoring.food_points(REFS[key]*ratio,key)==pytest.approx(scoring.food_maximum(key)*min(1,ratio),abs=1e-11)

@pytest.mark.parametrize('ratio,points',[(.6,0),(.95,25),(1.05,25),(1.4,0)])
@pytest.mark.parametrize('direction',[-math.inf,math.inf])
def test_machine_noise_at_macro_boundaries(ratio,points,direction):
 assert scoring.target_points(math.nextafter(2000*ratio,direction),2000,'energy')==points

def test_seven_weights_total_100():
 assert [scoring.RULES[k]['maximum'] for k in ('energy','protein','fat','carbs')]==[25,20,15,15]
 assert [scoring.food_maximum(k) for k in scoring.CORE_FOODS]==[10,10,5]
 assert assess()['score']==100

def test_missing_food_does_not_renormalize():
 r=assess(q=quality(**{k:{'low':0,'high':0} for k in REFS}))
 assert r['score']==75 and r['score_maximum']==100

def test_v8_has_no_79_cap_but_legacy_keeps_it():
 new=assess(values(fat_g=36));old=assess(values(fat_g=36),version=scoring.V7_VERSION)
 assert new['score']==85 and old['score']==79
 assert 'severe_domain_cap' not in new['score_rules']

def test_dated_policy_keeps_old_rules():
 assert scoring.version_for_date('2026-10-22')==scoring.V7_VERSION
 assert scoring.version_for_date('2026-10-23')==scoring.VERSION
 assert scoring.target_points(175,200,'carbs')==pytest.approx(15*(.4-.125)/.35)
 assert scoring.target_points(175,200,'carbs',version=scoring.V7_VERSION)==6

def test_alcohol_unchanged_and_no_nutrition_mutation():
 q=quality(alcohol_servings=[{'name':'Synthetic drink','volume_ml':40,'abv_percent':40,'basis':'Synthetic test volume','abv_source':'label','abv_basis':'Synthetic label'}])
 n=values();before=deepcopy(n)
 old=assess(n,q,version=scoring.V7_VERSION);new=assess(n,q)
 assert old['alcohol_penalty']==new['alcohol_penalty'] and n==before
 assert new['alcohol_penalty']['points']==pytest.approx(4.2)

def test_no_record_has_no_invented_score():
 r=scoring.score({},None,0,0,False)
 assert r['score'] is None

def test_rounding_only_at_display_and_final_total():
 n=values(**{nutrient:TARGET[nutrient]*(1+.05+.07/scoring.RULES[key]['maximum']*.35) for key,nutrient,_,_ in scoring.TARGET_PARTS})
 q=quality(**{k:{'low':v*(1-.07/scoring.food_maximum(k)),'high':v*(1-.07/scoring.food_maximum(k))} for k,v in REFS.items()})
 r=assess(n,q);assert r['score_raw_points']==pytest.approx(99.51);assert r['score']==100
 assert round(sum(round(p['points'],1) for p in r['components']))==99

def test_saved_v7_snapshot_is_supported_without_rewriting():
 old=assess(version=scoring.V7_VERSION);before=deepcopy(old)
 assert scoring.saved_version_supported(old)
 assess()
 assert old==before and old['score_rules']['carbs']['maximum']==10
 assert not scoring.saved_version_supported({'score_version':scoring.LEGACY_VERSION})

def test_public_distribution_does_not_grant_historical_override():
 from app import diet_policy,diet_score_revision
 assert 'historical_scoring_revision' not in diet_policy.get_policy()
 with pytest.raises(ValueError,match='历史版本覆盖'):
  diet_score_revision.revise({'date':'2020-01-01','expected_report_id':'synthetic-report','expected_report_version':1,'idempotency_key':'synthetic-revision','source_id':'synthetic-explicit-request','reason':'Synthetic authorization must not be preinstalled','score_version_override':scoring.VERSION})

def test_other_missing_evidence_cannot_become_midpoint_estimate():
 n=values(kcal=800);s=assess(n)
 assert s['score'] is None
 with pytest.raises(ValueError):
  estimate.build({**s,'totals':n,'meals':1,'analyzed':1},source_id='synthetic',reason='Synthetic evidence missing',created_at='2030-01-01')
