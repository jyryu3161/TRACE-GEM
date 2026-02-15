"""SQLite cache schema definitions."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at REAL NOT NULL,
    ttl INTEGER NOT NULL,
    source TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_cache_source ON api_cache(source);
CREATE INDEX IF NOT EXISTS idx_api_cache_created ON api_cache(created_at);
"""
