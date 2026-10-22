-- Initialize the local structured-write API and disable internal scheduling.
BEGIN IMMEDIATE;
UPDATE settings SET data=json_set(data,'$.daily_time','07:00','$.evening_time','07:00','$.schedule_enabled',json('false'),'$.weekly_enabled',json('false'),'$.evening_enabled',json('false'),'$.agent_enabled',json('false'),'$.public_sources_enabled',json('false'),'$.timezone','Asia/Shanghai','$.timezone_confirmed',json('true')),version=version+1 WHERE id=1 AND NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version=5);
CREATE TABLE IF NOT EXISTS external_ingests(idempotency_key TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, report_id TEXT NOT NULL REFERENCES reports(id));
INSERT OR IGNORE INTO schema_migrations VALUES(5,strftime('%Y-%m-%dT%H:%M:%SZ','now'));
COMMIT;
