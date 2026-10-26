import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parent.parent


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_url(url):
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("A public HTTPS job URL is required")
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_") and k.lower() not in {"source", "ref", "gh_src", "fbclid", "gclid"}]
    return urlunsplit(("https", parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def connect(path=None):
    path = Path(path or os.environ.get("OFIR_DB_PATH", ROOT / ".local/ofir.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.executescript((ROOT / "data/schema.sql").read_text())
    columns = {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
    for name, default in [('match_category', 'unassessed'), ('match_version', ''), ('match_details', '{}')]:
        if name not in columns:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT DEFAULT '{default}'")
    return db


def seed(db):
    companies = json.loads((ROOT / "data/companies.json").read_text())
    with db:
        for company in companies:
            keys = list(company)
            db.execute(f"INSERT OR IGNORE INTO companies ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", list(company.values()))


def save_job(db, company_id, job, assessment):
    stamp = now()
    url = canonical_url(job["url"])
    identity = f'{company_id}:{job["source_id"]}'
    job_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
    # Publication, tracking params and crawl timestamps cannot generate a change notification.
    digest = hashlib.sha256(json.dumps([job["title"], job["location"], " ".join(job["description"].split())], ensure_ascii=False).encode()).hexdigest()
    previous = db.execute("SELECT * FROM jobs WHERE id=? OR url=?", (job_id, url)).fetchone()
    if previous:
        job_id = previous["id"]
    version = (previous["version"] if previous else 1)
    kind = "new"
    material_change = bool(previous and previous["content_hash"] != digest)
    reopened = bool(previous and previous["status"] == "closed" and job["status"] == "open")
    # Only verified reopenings or changes that make a previously ineligible job eligible generate new alerts.
    new_event = not previous or reopened or (material_change and not previous["eligible"] and assessment["eligible"])
    if previous and new_event:
        version += 1
        kind = "reopened" if reopened else "became_relevant"
    values = {
        "id": job_id, "company_id": company_id, "source_id": job["source_id"],
        "title": job["title"], "location": job["location"], "url": url,
        "description": job["description"], "work_model": job.get("work_model", "לא צוין"),
        "published_at": job.get("published_at"), "updated_at": job.get("updated_at"),
        "first_seen_at": previous["first_seen_at"] if previous else stamp,
        "last_seen_at": stamp, "last_verified_at": stamp if job["status"] == "open" else None,
        "status": job["status"], "score": assessment["score"],
        "breakdown": json.dumps(assessment["breakdown"], ensure_ascii=False),
        "reasons": json.dumps(assessment["reasons"], ensure_ascii=False),
        "gaps": json.dumps(assessment["gaps"], ensure_ascii=False),
        "experience": assessment["experience"], "eligible": assessment["eligible"],
        "exclusion_reason": assessment["exclusion_reason"], "content_hash": digest, "version": version,
        "match_category": assessment.get("match_category", "unassessed"),
        "match_version": assessment.get("match_version", ""),
        "match_details": json.dumps(assessment.get("match_details", {}), ensure_ascii=False),
    }
    keys = list(values)
    updates = ','.join(f'{key}=excluded.{key}' for key in keys if key not in {"id", "first_seen_at"})
    db.execute(f"INSERT INTO jobs ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)}) ON CONFLICT(id) DO UPDATE SET {updates}", list(values.values()))
    imported = db.execute("SELECT * FROM imports WHERE canonical_url=?", (url,)).fetchone()
    if imported and (not previous or not previous["user_updated_at"]):
        db.execute("UPDATE jobs SET application_status=?, familiar=1 WHERE id=?", (imported["application_status"], job_id))
    if new_event:
        db.execute("INSERT OR IGNORE INTO job_events (job_id, version, kind, created_at) VALUES (?,?,?,?)", (job_id, version, kind, stamp))
    return not previous


@contextlib.contextmanager
def process_lock(name):
    """One scan/digest writer at a time, including across cron invocations."""
    import fcntl
    path = Path(os.environ.get("OFIR_DB_PATH", ROOT / ".local/ofir.sqlite")).parent
    path.mkdir(parents=True, exist_ok=True)
    with (path / f"{name}.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f"Another {name} process is running") from None
        yield
