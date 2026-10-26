"""Verify a bounded batch of externally found job URLs against official structured data."""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
from .sources import Client, SourceError, postings, embedded_json, comeet_job, normalize_posting, plain
from .matching import exclude
from .scoring import assess, within_age_limit
from .store import canonical_url, save_job, now


def belongs_to_company(company, url, organization=""):
    normalize = lambda value: re.sub(r"[^\w]", "", str(value).casefold())
    if organization:
        return normalize(organization) == normalize(company["name"])
    career, target = urlsplit(company["career_url"]), urlsplit(url)
    greenhouse = {"boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io"}
    comeet = {"www.comeet.com", "www.comeet.co"}
    if career.hostname in greenhouse | comeet or target.hostname in greenhouse | comeet:
        if career.hostname in greenhouse and target.hostname in greenhouse:
            return career.path.strip("/").split("/")[0] == target.path.strip("/").split("/")[0]
        return career.hostname in comeet and target.hostname in comeet and career.path.strip("/").split("/")[:3] == target.path.strip("/").split("/")[:3]
    return career.hostname == target.hostname


def verify_pending(db, limit=5):
    findings = db.execute("""SELECT d.* FROM job_discoveries d WHERE d.status='pending' AND NOT EXISTS
        (SELECT 1 FROM company_monitor_controls m WHERE m.company_id=d.company_id AND m.opted_out=1)
        ORDER BY CASE WHEN last_checked IS NULL THEN 0 ELSE 1 END,last_checked,id LIMIT ?""", (limit,)).fetchall()
    verified = 0
    for finding in findings:
        company = dict(db.execute("SELECT * FROM companies WHERE id=?", (finding["company_id"],)).fetchone())
        message = "הממצא טרם אומת; נדרש מידע מובנה בדף הרשמי"
        try:
            career = company["career_url"]
            if not career or canonical_url(career) == finding["url"]:
                raise SourceError("unsupported", "נדרש קישור קריירה נפרד של החברה לפני אימות המשרה")
            client = Client(company)
            document = client.get(finding["url"])
            final_url = getattr(client, "last_url", None)
            if isinstance(final_url, str) and canonical_url(final_url) != finding["url"]:
                raise SourceError("unsupported", "הקישור הופנה לדף אחר; נדרש קישור משרה קנוני מעודכן")
            if re.search(r"no longer accepting applications|this job has expired|(?:this|the) (?:job|position) is closed", plain(document), re.I):
                raise SourceError("unsupported", "דף המשרה מציין שההגשה נסגרה")
            job = None
            detail = embedded_json(document, "POSITION_DATA")
            if isinstance(detail, dict):
                if not belongs_to_company(company, finding["url"], detail.get("company_name", "")):
                    raise SourceError("unsupported", "לא ניתן לאמת שהמשרה שייכת לחברה שנבחרה")
                candidate = comeet_job(detail)
                if canonical_url(candidate["url"]) == finding["url"]:
                    job = candidate
            if job is None:
                items, _ = postings(document)
                for item in items:
                    candidate = normalize_posting(item, finding["url"])
                    if canonical_url(candidate["url"]) != finding["url"]:
                        continue
                    organization = item.get("hiringOrganization") or {}
                    if not isinstance(organization, dict) or not belongs_to_company(company, finding["url"], organization.get("name", "")):
                        continue
                    if item.get("validThrough"):
                        expires = datetime.fromisoformat(str(item["validThrough"]).replace("Z", "+00:00"))
                        if expires.tzinfo is None: expires = expires.replace(tzinfo=timezone.utc)
                        if expires < datetime.now(timezone.utc):
                            raise SourceError("unsupported", "תוקף המשרה לפי המקור הרשמי הסתיים")
                    job = candidate
                    break
            if not job or not job["title"] or not job["description"]:
                raise SourceError("unsupported", message)
            previous = db.execute("SELECT status FROM jobs WHERE url=?", (finding["url"],)).fetchone()
            if previous and previous["status"] == "closed":
                raise SourceError("unsupported", "המשרה נסגרה במקור; נדרש אימות פתיחה מחדש בסריקת החברה")
            job["status"] = "open"
            assessment = assess(job["title"], job["description"], job["location"], company)
            if not within_age_limit(job.get("published_at")):
                exclude(assessment, "תאריך הפרסום מחוץ לחלון ששת החודשים")
            with db:
                save_job(db, company["id"], job, assessment)
                stored = db.execute("SELECT id FROM jobs WHERE url=?", (finding["url"],)).fetchone()
                db.execute("UPDATE job_discoveries SET status='linked',linked_job_id=?,last_checked=?,last_result=? WHERE id=?",
                           (stored["id"], now(), "הפרטים נאספו ואומתו בדף המשרה הרשמי; התאמה נבחנת בנפרד", finding["id"]))
            verified += 1
            continue
        except SourceError as error:
            message = error.message
        except (ValueError, TypeError, KeyError):
            message = "מבנה דף המשרה אינו מאפשר עדיין אימות אמין"
        with db:
            db.execute("UPDATE job_discoveries SET last_checked=?,last_result=? WHERE id=?", (now(), message, finding["id"]))
    print(f"External findings checked: {len(findings)}; verified: {verified}")
    return verified
