PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS companies (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, location_hint TEXT NOT NULL,
 suggested_url TEXT NOT NULL, career_url TEXT NOT NULL, ats_hint TEXT NOT NULL,
 ats_identifier TEXT NOT NULL, imported_active INTEGER NOT NULL,
 imported_priority TEXT NOT NULL, imported_last_checked TEXT NOT NULL,
 imported_last_result TEXT NOT NULL, notes TEXT NOT NULL, enabled INTEGER NOT NULL,
 source_status TEXT NOT NULL DEFAULT 'pending', last_checked TEXT,
 last_result TEXT NOT NULL DEFAULT 'טרם נבדק במערכת החדשה', job_count INTEGER,
 verified_url TEXT
);
CREATE TABLE IF NOT EXISTS scans (
 id INTEGER PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
 started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
 fetched_count INTEGER, eligible_count INTEGER, new_count INTEGER, message TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
 source_id TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL,
 work_model TEXT NOT NULL DEFAULT 'לא צוין', url TEXT NOT NULL UNIQUE,
 description TEXT NOT NULL, published_at TEXT, updated_at TEXT,
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, last_verified_at TEXT,
 status TEXT NOT NULL DEFAULT 'unverified', score INTEGER NOT NULL,
 breakdown TEXT NOT NULL, reasons TEXT NOT NULL, gaps TEXT NOT NULL,
 experience TEXT NOT NULL, eligible INTEGER NOT NULL, exclusion_reason TEXT,
 content_hash TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 fit TEXT NOT NULL DEFAULT 'unrated', familiar INTEGER NOT NULL DEFAULT 0,
 application_status TEXT NOT NULL DEFAULT 'not_applied', personal_note TEXT NOT NULL DEFAULT '',
 user_updated_at TEXT
);
CREATE TABLE IF NOT EXISTS job_events (
 id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
 version INTEGER NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL,
 notified_at TEXT, UNIQUE(job_id, version)
);
CREATE TABLE IF NOT EXISTS imports (
 canonical_url TEXT PRIMARY KEY, application_status TEXT NOT NULL,
 applied_at TEXT, imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS digest_runs (
 id INTEGER PRIMARY KEY, day TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL, created_at TEXT NOT NULL, sent_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS events_pending ON job_events(notified_at);
