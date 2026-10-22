"""Synthetic regressions. No real person or intake is represented."""
import json
from datetime import date
import pytest
from fastapi.testclient import TestClient
from app import config,db,diet_day,diet_policy,diet_mirror
from app.main import app
@pytest.fixture
def empty(tmp_path,monkeypatch):
 monkeypatch.setattr(config,'DATA',tmp_path/'data');db.init();return config.DATA

def test_empty_database(empty):
 with db.connect(track_mirror=False) as con:
  for table in ('records','reports','assets','jobs','grants'):
   assert con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0

def test_disabled_integrations(empty):
 s=db.settings()
 for key in ('agent_enabled','public_sources_enabled','schedule_enabled','weekly_enabled','evening_enabled'):assert s[key] is False
 assert s['daily_time']=='07:00';assert diet_mirror.status()['configured'] is False

@pytest.mark.parametrize('stamp,expected',[('2030-01-02T06:59:00+08:00','2030-01-01'),('2030-01-02T07:00:00+08:00','2030-01-02'),('2030-01-02T00:00:00+08:00','2030-01-01')])
def test_boundary(stamp,expected):assert diet_day.current_diet_day(stamp)==date.fromisoformat(expected)

def test_migration_idempotent(empty):
 before=db.settings()['version'];db.init();assert db.settings()['version']==before

def test_upgrade_keeps_seven_boundary(empty):
 with db.connect(track_mirror=False) as con:
  con.execute('DELETE FROM schema_migrations WHERE version IN (4,5)')
  con.execute("UPDATE settings SET data=json_set(data,'$.daily_time','03:00','$.schedule_enabled',json('true'))")
 db.init();assert db.settings()['daily_time']=='07:00';assert db.settings()['schedule_enabled'] is False

def test_policy_weights():
 p=diet_policy.get_policy();assert sum(p['scoring_evidence']['macro_weights'].values())==70
 assert p['scoring_evidence']['denominator']==100;assert p['execution']['scheduler_enabled'] is False

@pytest.mark.parametrize('path',['health','settings','diet/overview','diet/history?month=2030-01','diet/body-metrics','providers','diet/recommendations'])
def test_blank_api(empty,path):
 with TestClient(app,base_url='http://127.0.0.1:8765') as c:
  c.get('/api/v1/session')
  r=c.get('/api/v1/'+path);assert r.status_code==200,r.text

def test_optimistic_versions(empty):
 r=db.save_record('synthetic_test','diet',{'label':'fictional'})
 db.save_record('synthetic_test','diet',{'label':'updated'},identifier=r['id'],version=r['version'])
 with pytest.raises(db.Conflict):db.save_record('synthetic_test','diet',{},identifier=r['id'],version=r['version'])
