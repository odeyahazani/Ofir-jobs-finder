"""Isolated browser fixtures; never writes to the real development database."""
from pathlib import Path
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.store import connect, seed, save_job
from collector.scoring import assess

if "e2e" not in Path(os.environ.get("OFIR_DB_PATH", "")).name:
    raise SystemExit("An explicitly isolated e2e database is required")
db = connect()
with db:
    db.execute("DELETE FROM job_discoveries")
    db.execute("DELETE FROM job_events")
    db.execute("DELETE FROM jobs")
    db.execute("DELETE FROM imports")
    db.execute("DELETE FROM scans")
    db.execute("DELETE FROM company_monitor_controls")
    db.execute("DELETE FROM companies")
    seed(db)
    company = db.execute("SELECT * FROM companies WHERE name='Augury'").fetchone()
    for index, status in enumerate(["open", "unverified", "closed"]):
        job = {"source_id": f"test-only-{index}", "title": f"TEST ONLY · Junior Integration Engineer {index}",
               "description": "Junior optical integration and validation engineer. Python and MATLAB. Laboratory experiments and signal processing. 0-1 years of experience.",
               "location": "Haifa, Israel", "url": f"https://example.com/test-only/{index}", "status": status}
        save_job(db, company["id"], job, assess(job["title"], job["description"], job["location"], company))
db.close()
