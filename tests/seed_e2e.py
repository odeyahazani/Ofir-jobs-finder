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
        if index == 0:
            job["description"] += "\n\n" + "Responsibilities\n\n" + "\n\n".join([
                "Define repeatable integration procedures and document expected behavior for multidisciplinary systems.",
                "Plan laboratory experiments, choose measurement methods and compare the results against a documented baseline.",
                "Use Python and MATLAB to inspect measurement data and prepare clear validation reports.",
                "Investigate discrepancies between expected system performance and observations from the laboratory.",
                "Collaborate with electrical engineering, physics and systems teams to understand cross-functional requirements.",
                "Maintain traceable experiment records, instrument settings and test results so that another engineer can reproduce the work.",
                "Present findings in technical reviews and explain the assumptions and limitations of each measurement.",
                "Support the preparation of test plans for new sensors, optics and electronic assemblies.",
                "Requirements", "An electrical engineering or physics degree, practical laboratory experience and professional English.",
                "Familiarity with structured experiments and data analysis. This is isolated synthetic browser-test content, not a real vacancy.",
                "Ability to document technical work clearly and collaborate with a multidisciplinary team.",
            ])
        save_job(db, company["id"], job, assess(job["title"], job["description"], job["location"], company))
    for source_id, location in [("test-abroad", "San Jose, California, United States"), ("test-unknown", "Remote")]:
        job = {"source_id": source_id, "title": f"TEST ONLY · {source_id}",
               "description": "Junior integration engineer, Python, MATLAB and laboratory experiments.",
               "location": location, "url": f"https://example.com/{source_id}", "status": "open"}
        save_job(db, company["id"], job, assess(job["title"], job["description"], job["location"], company))
        # Simulate legacy/imported scores: recommendations must still enforce Israeli location.
        db.execute("UPDATE jobs SET eligible=1,score=95 WHERE source_id=?", (source_id,))
db.close()
