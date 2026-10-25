import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from collector.discoveries import verify_pending
from collector.store import connect, seed


class DiscoveryVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "test.sqlite")
        seed(self.db)
        self.company = self.db.execute("SELECT * FROM companies WHERE name='Augury'").fetchone()
        self.url = "https://www.augury.com/careers/test-fixture"
        with self.db:
            self.db.execute("INSERT INTO job_discoveries(id,company_id,company_name,title,url,added_at) VALUES('fixture',?,'Augury','Reported title',?,'2026-10-25')", (self.company["id"], self.url))
        self.posting = {"@type": "JobPosting", "title": "Junior Integration Engineer", "url": self.url,
                        "description": "Junior optical lab integration. Python and MATLAB, signal processing and tests. No prior experience.",
                        "hiringOrganization": {"name": "Augury"}, "jobLocation": {"address": {"addressLocality": "Haifa", "addressCountry": "Israel"}}}

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def run_verification(self, posting=None):
        client = MagicMock()
        client.last_url = self.url
        client.get.return_value = '<script type="application/ld+json">' + json.dumps(posting or self.posting) + '</script>'
        with patch("collector.discoveries.Client", return_value=client): return verify_pending(self.db)

    def test_actual_official_fields_replace_untrusted_reported_title_and_keep_dates_unknown(self):
        self.assertEqual(self.run_verification(), 1)
        job = self.db.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(job["title"], "Junior Integration Engineer")
        self.assertIsNone(job["published_at"])
        self.assertEqual(job["status"], "open")
        self.assertEqual(self.db.execute("SELECT status FROM job_discoveries").fetchone()[0], "linked")

    def test_different_company_or_expired_posting_does_not_become_a_verified_job(self):
        for replacement in [{"hiringOrganization": {"name": "Another company"}}, {"validThrough": "2020-01-01T00:00:00Z"}]:
            with self.subTest(replacement=replacement): self.assertEqual(self.run_verification({**self.posting, **replacement}), 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)

    def test_missing_structured_data_remains_pending_with_a_recorded_check(self):
        self.assertEqual(self.run_verification({"@type": "WebPage"}), 0)
        row = self.db.execute("SELECT * FROM job_discoveries").fetchone()
        self.assertEqual(row["status"], "pending"); self.assertIsNotNone(row["last_checked"])

    def test_explicit_monitor_pause_also_stops_individual_url_checks(self):
        with self.db: self.db.execute("INSERT INTO company_monitor_controls VALUES (?,1)", (self.company["id"],))
        self.assertEqual(self.run_verification(), 0)


if __name__ == "__main__": unittest.main()
