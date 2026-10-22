-- Retained migration number; do not change clocks or existing records.
INSERT OR IGNORE INTO schema_migrations VALUES(4,strftime('%Y-%m-%dT%H:%M:%SZ','now'));
