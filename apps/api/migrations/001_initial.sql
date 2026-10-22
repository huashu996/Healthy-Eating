CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
INSERT OR IGNORE INTO schema_migrations VALUES(1, strftime('%Y-%m-%dT%H:%M:%SZ','now'));
CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records(
 id TEXT PRIMARY KEY,kind TEXT NOT NULL,module TEXT NOT NULL,project_id TEXT REFERENCES records(id),
 version INTEGER NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('live','mock')),deleted_at TEXT);
CREATE INDEX IF NOT EXISTS records_kind ON records(kind,updated_at);
CREATE INDEX IF NOT EXISTS records_project ON records(project_id);
CREATE TABLE IF NOT EXISTS revisions(record_id TEXT REFERENCES records(id),version INTEGER,data TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(record_id,version));
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,storage_key TEXT UNIQUE,mime TEXT,size INTEGER,sha256 TEXT,module TEXT,project_id TEXT REFERENCES records(id),created_at TEXT,original_name TEXT);
CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY,module TEXT,provider TEXT,purpose TEXT,scope TEXT,expires_at TEXT,once_job TEXT,revoked_at TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE,module TEXT,operation TEXT,business_date TEXT,timezone TEXT,
 status TEXT,input TEXT,result TEXT,attempt INTEGER DEFAULT 0,lease_until TEXT,heartbeat TEXT,
 scheduled_at TEXT,started_at TEXT,finished_at TEXT,next_attempt TEXT,error_code TEXT,
 cancel_requested INTEGER DEFAULT 0,mode TEXT DEFAULT 'live',external_started INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status,next_attempt);
CREATE TABLE IF NOT EXISTS job_events(job_id TEXT REFERENCES jobs(id),sequence INTEGER,type TEXT,payload TEXT,created_at TEXT,PRIMARY KEY(job_id,sequence));
CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY,job_id TEXT UNIQUE REFERENCES jobs(id),module TEXT,business_date TEXT,timezone TEXT,version INTEGER,status TEXT,data TEXT,created_at TEXT,mode TEXT);
CREATE TABLE IF NOT EXISTS schedules(module TEXT PRIMARY KEY,next_due TEXT,timezone TEXT,last_business_date TEXT,last_success TEXT);
CREATE TABLE IF NOT EXISTS missed_runs(module TEXT,business_date TEXT,timezone TEXT,PRIMARY KEY(module,business_date,timezone));
CREATE TABLE IF NOT EXISTS runtime(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS audit_events(id TEXT PRIMARY KEY,action TEXT,target TEXT,safe_metadata TEXT,created_at TEXT);
