import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError
from zoneinfo import ZoneInfo

from .store import connect, seed, now, save_job, process_lock, canonical_url
from .scoring import assess, within_age_limit
from .sources import collect, SourceError


def scan(db, company_name=None, limit=None):
    if limit is not None and not 1 <= limit <= 50:
        raise ValueError("Scan limit must be between 1 and 50 companies")
    query = "SELECT * FROM companies WHERE enabled=1" + (" AND name=?" if company_name else "") + " ORDER BY CASE WHEN last_checked IS NULL THEN 0 ELSE 1 END,last_checked,id"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    companies = db.execute(query, (company_name,) if company_name else ()).fetchall()
    if not companies:
        raise ValueError("No enabled company matches the selection")
    failures = 0
    for row in companies:
        company = dict(row)
        started = now()
        with db:
            scan_id = db.execute("INSERT INTO scans(company_id,started_at,status) VALUES (?,?,'running')", (company["id"], started)).lastrowid
        try:
            partial = None
            try:
                jobs = collect(company)
            except SourceError as error:
                if not error.partial_jobs:
                    raise
                jobs, partial = error.partial_jobs, error
            new, eligible = 0, 0
            seen = []
            with db:
                for job in jobs:
                    assessment = assess(job["title"], job["description"], job["location"], company)
                    if not within_age_limit(job.get("published_at")):
                        assessment.update(eligible=False, exclusion_reason="תאריך הפרסום מחוץ לחלון ששת החודשים")
                    eligible += bool(assessment["eligible"])
                    new += save_job(db, company["id"], job, assessment)
                    seen.append(canonical_url(job["url"]))
                # Only a successful complete official API listing establishes that missing jobs closed.
                if partial is None and company["ats_hint"] in {"Greenhouse", "Comeet"}:
                    existing = db.execute("SELECT id,url FROM jobs WHERE company_id=?", (company["id"],)).fetchall()
                    for old in existing:
                        if old["url"] not in seen:
                            db.execute("UPDATE jobs SET status='closed' WHERE id=?", (old["id"],))
                status = partial.status if partial else "ok" if jobs else "empty"
                message = f"{len(jobs)} jobs extracted; {eligible} eligible; {new} new"
                if partial:
                    failures += 1
                    message += '; ' + partial.message
                db.execute("UPDATE companies SET source_status=?,last_checked=?,last_result=?,job_count=?,verified_url=? WHERE id=?", (status, now(), message, None if partial else len(jobs), company["career_url"], company["id"]))
                db.execute("UPDATE scans SET finished_at=?,status=?,fetched_count=?,eligible_count=?,new_count=?,message=? WHERE id=?", (now(), status, len(jobs), eligible, new, message, scan_id))
            print(company["name"], status, message)
        except SourceError as error:
            failures += 1
            with db:
                db.execute("UPDATE companies SET source_status=?,last_checked=?,last_result=?,job_count=NULL WHERE id=?", (error.status, now(), error.message, company["id"]))
                db.execute("UPDATE scans SET finished_at=?,status=?,message=? WHERE id=?", (now(), error.status, error.message, scan_id))
            print(company["name"], error.status, error.message)
    return 1 if failures else 0


def import_applications(db, path):
    with open(path, encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    allowed = {"not_applied", "planned", "applied", "interviewing", "rejected", "withdrawn"}
    validated = []
    for index, row in enumerate(rows, 2):
        try:
            url = canonical_url(row["url"])
            status = row.get("status") or "applied"
            if status not in allowed:
                raise ValueError("Invalid status")
            validated.append((url, status, row.get("applied_at") or None, now()))
        except (ValueError, KeyError):
            raise ValueError(f"Invalid application import row {index}; nothing imported") from None
    with db:
        for values in validated:
            db.execute("INSERT INTO imports VALUES (?,?,?,?) ON CONFLICT(canonical_url) DO UPDATE SET application_status=excluded.application_status,applied_at=excluded.applied_at,imported_at=excluded.imported_at", values)
            db.execute("UPDATE jobs SET application_status=?,familiar=1,user_updated_at=? WHERE url=?", (values[1], now(), values[0]))
    print(f"Imported {len(validated)} application records")
    return validated


def digest(db, send=False, delivery_store=None):
    day = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(timespec="seconds")
    rows = db.execute("""SELECT e.id AS event_id,j.*,c.name AS company FROM job_events e JOIN jobs j ON j.id=e.job_id
        JOIN companies c ON c.id=j.company_id WHERE e.notified_at IS NULL AND e.version=j.version
        AND j.eligible=1 AND j.score>=70 AND j.status='open' AND j.last_verified_at>=?
        AND j.familiar=0 AND j.application_status='not_applied' AND j.fit!='no'
        ORDER BY j.score DESC,j.published_at DESC,j.first_seen_at DESC""", (cutoff,)).fetchall()
    # All matched events are represented by the count; the first five also get individual links.
    text = f"הסיכום היומי של אופיר · {day}\n{len(rows)} הזדמנויות חדשות או שהפכו לרלוונטיות."
    for row in rows[:5]:
        text += f"\n\n{row['company']} · {row['title']}\n{row['score']}/100 · {row['location']}\n{row['url']}"
    app_url = os.environ.get("APP_URL", "")
    if app_url.startswith("https://"):
        text += f"\n\nלכל המשרות ולסימון מועמדות: {app_url.rstrip('/')}"
    health = dict(db.execute("SELECT source_status,COUNT(*) FROM companies WHERE enabled=1 GROUP BY source_status").fetchall())
    problems = sum(count for status, count in health.items() if status not in {"ok", "empty"})
    if problems:
        text += f"\n\nלתשומת לבך: {problems} מקורות טרם נסרקו בהצלחה."
    if not send:
        print(text)
        print("\n[Preview only; no message sent or notification state changed]")
        return
    if not rows:
        print("No eligible verified new jobs; no notification sent")
        return
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat or not app_url.startswith("https://"):
        raise ValueError("Set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID and an HTTPS APP_URL securely before sending")
    # Reserve before the external request: after a timeout Telegram may already have accepted it.
    # Never auto-retry an uncertain send, avoiding duplicate notifications.
    try:
        with db:
            db.execute("INSERT INTO digest_runs(day,status,created_at) VALUES (?,'sending',?)", (day, now()))
    except sqlite3.IntegrityError:
        print("Today's digest was already sent or attempted; inspect digest_runs before any manual retry")
        return
    if delivery_store and not delivery_store.reserve_digest(day):
        print("Today's cloud digest was already sent or attempted; no duplicate message sent")
        return
    body = json.dumps({"chat_id": chat, "text": text[:4000], "link_preview_options": {"is_disabled": True}}).encode()
    try:
        request = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=25) as response:
            result = json.load(response)
            if not result.get("ok"):
                raise ValueError("Telegram did not confirm delivery")
    except Exception:
        with db:
            db.execute("UPDATE digest_runs SET status='uncertain' WHERE day=?", (day,))
        if delivery_store:
            delivery_store.finish_digest(day, "uncertain", [])
        raise ValueError("Telegram delivery unconfirmed; inspect Telegram before retrying. Credentials have not been logged.") from None
    if delivery_store:
        delivery_store.finish_digest(day, "sent", [{"job_id": row["id"], "version": row["version"]} for row in rows])
    with db:
        for row in rows:
            db.execute("UPDATE job_events SET notified_at=? WHERE id=?", (now(), row["event_id"]))
        db.execute("UPDATE digest_runs SET status='sent',sent_at=? WHERE day=?", (now(), day))
    print(f"Digest sent; {len(rows)} events marked notified")


def main():
    from .config import load_local_config
    load_local_config()
    parser = argparse.ArgumentParser(description="Ofir Jobs Finder")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    scanner = commands.add_parser("scan")
    scanner.add_argument("--company")
    importer = commands.add_parser("import-applications")
    importer.add_argument("file")
    notifier = commands.add_parser("digest")
    notifier.add_argument("--send", action="store_true")
    args = parser.parse_args()
    try:
        with connect() as db:
            seed(db)
            if args.command == "init":
                print(f"Database initialized; {db.execute('SELECT COUNT(*) FROM companies').fetchone()[0]} companies")
            elif args.command == "scan":
                with process_lock("scan"):
                    return scan(db, args.company)
            elif args.command == "digest":
                with process_lock("digest"):
                    digest(db, args.send)
            else:
                import_applications(db, args.file)
        return 0
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
