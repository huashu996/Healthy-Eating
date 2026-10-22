-- Stop previously queued automatic output work once. Historical reports remain readable.
BEGIN IMMEDIATE;
INSERT INTO job_events(job_id,sequence,type,payload,created_at)
SELECT j.id,COALESCE((SELECT MAX(sequence) FROM job_events WHERE job_id=j.id),0)+1,
       'cancelled','{"reason":"click_only_updates"}',strftime('%Y-%m-%dT%H:%M:%SZ','now')
FROM jobs j
WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=3)
  AND j.status IN ('queued','running','awaiting_permission')
  AND ((j.module='tech' AND j.operation='daily_digest') OR (j.module='finance' AND j.operation='market_refresh'))
  AND (j.idempotency_key LIKE 'tech:auto:%' OR j.idempotency_key LIKE 'tech:daily_digest:%:v1' OR j.idempotency_key LIKE 'finance:market_refresh:%:v1');
UPDATE jobs SET status='cancelled',cancel_requested=1,finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),lease_until=NULL,error_code='click_only_updates'
WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=3)
  AND status IN ('queued','running','awaiting_permission')
  AND ((module='tech' AND operation='daily_digest') OR (module='finance' AND operation='market_refresh'))
  AND (idempotency_key LIKE 'tech:auto:%' OR idempotency_key LIKE 'tech:daily_digest:%:v1' OR idempotency_key LIKE 'finance:market_refresh:%:v1');
DELETE FROM schedules WHERE module IN ('tech:daily_digest','finance:market_refresh')
  AND NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=3);
INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(3,strftime('%Y-%m-%dT%H:%M:%SZ','now'));
COMMIT;
