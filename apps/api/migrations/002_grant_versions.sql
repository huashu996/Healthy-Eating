CREATE TABLE IF NOT EXISTS grant_versions(grant_id TEXT PRIMARY KEY REFERENCES grants(id),record_version INTEGER NOT NULL,project_id TEXT);
INSERT OR IGNORE INTO schema_migrations VALUES(2, strftime('%Y-%m-%dT%H:%M:%SZ','now'));
