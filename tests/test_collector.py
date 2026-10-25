import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from collector import cli
from collector.store import connect, seed, save_job, canonical_url
from collector.scoring import assess, within_age_limit
from collector.sources import collect, postings, normalize_posting, SourceError, plain, check_url, embedded_json
from collector.scheduler import due

COMPANY = {"notes": "Medical devices, optics and integration"}
DESCRIPTION = "Junior integration engineer. Python and MATLAB. Optical lab experiments, sensors and signal processing. 0-1 years of experience."


class ScoringTests(unittest.TestCase):
    def score(self, title="Integration Engineer", description=DESCRIPTION, location="Caesarea, Israel"):
        return assess(title, description, location, COMPANY)

    def test_academic_entry_role_is_eligible(self):
        result = self.score()
        self.assertTrue(result["eligible"])
        self.assertGreaterEqual(result["score"], 70)
        self.assertLessEqual(result["score"], 100)
        self.assertEqual(result["breakdown"]["growth"], 0)

    def test_no_junior_in_title_required(self):
        self.assertTrue(self.score(description="Integration and laboratory testing, Python. 2 years of experience.")["eligible"])

    def test_four_plus_years_is_excluded_even_if_otherwise_perfect(self):
        result = self.score(description=DESCRIPTION + "\nAt least 4+ years of experience required.")
        self.assertFalse(result["eligible"])

    def test_optional_experience_is_not_a_hard_gate(self):
        self.assertTrue(self.score(description="Lab test and Python. 5 years of experience preferred.")["eligible"])

    def test_optional_clause_does_not_cancel_mandatory_clause(self):
        self.assertFalse(self.score(description="Test integration. 4 years of experience required.\nPython experience preferred.")["eligible"])

    def test_range_uses_minimum(self):
        self.assertTrue(self.score(description="Integration. 2–4 years experience.")["eligible"])
        self.assertFalse(self.score(description="Integration. 4–6 years experience.")["eligible"])

    def test_hebrew_years(self):
        self.assertFalse(self.score(description="בדיקות מערכת\n4 שנות ניסיון חובה")["eligible"])

    def test_varied_required_experience_wording(self):
        for requirement in ["5+ years of hands-on experience", "4 years’ relevant experience", "Minimum 4 years in validation", "At least 6 yrs in engineering"]:
            with self.subTest(requirement=requirement):
                self.assertFalse(self.score(description="Integration.\n" + requirement)["eligible"])

    def test_senior_and_customer_service_are_excluded(self):
        for title in ["Senior Integration Engineer", "Field Service Engineer", "R&D Manager", "Principal Optical Engineer"]:
            with self.subTest(title=title):
                self.assertFalse(self.score(title=title)["eligible"])

    def test_team_leader_is_not_recommended_even_with_high_fit(self):
        result = self.score(title="Failure Analysis and Quality Control Team Leader")
        self.assertGreaterEqual(result["score"], 70)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["exclusion_reason"], "תפקיד בכיר או ניהולי")
        self.assertTrue(self.score(title="Integration Engineer", description=DESCRIPTION + " Work with the team leader.")["eligible"])

    def test_hardware_tenure_is_not_hidden_by_a_lower_leadership_requirement(self):
        result = self.score(description="Integration testing.\n6+ years in hardware design and failure analysis; minimum 2 years in a leadership role- Must.")
        self.assertEqual(result["experience"], "לפחות 6 שנות ניסיון")
        self.assertFalse(result["eligible"])

    def test_unknown_experience_not_assumed_entry(self):
        result = self.score(description="Hardware testing and Python")
        self.assertEqual(result["experience"], "לא צוין בבירור")
        self.assertLess(result["breakdown"]["experience"], 25)

    def test_outside_israel_not_assumed_local_from_company_address(self):
        self.assertFalse(self.score(location="New York, US")["eligible"])

    def test_six_month_limit_and_unknown_date(self):
        self.assertTrue(within_age_limit(None))
        self.assertFalse(within_age_limit((datetime.now(timezone.utc) - timedelta(days=200)).isoformat()))
        self.assertFalse(within_age_limit((datetime.now(timezone.utc) + timedelta(days=10)).isoformat()))


class ParserTests(unittest.TestCase):
    def test_comeet_public_bootstrap_and_detail_verification(self):
        document = Path("tests/fixtures/comeet-bootstrap.html").read_text()
        item = embedded_json(document, "COMPANY_POSITIONS_DATA")[0]
        class FakeClient:
            hosts = {"www.comeet.com"}
            def get(self, url, **kwargs):
                return "<script>POSITION_DATA = " + json.dumps(item) + ";</script>" if url.endswith("AA.002") else document
        jobs = collect({"career_url": "https://www.comeet.com/jobs/test/AA.001", "ats_hint": "Comeet"}, FakeClient())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "open")
        self.assertIsNone(jobs[0]["published_at"])
        self.assertEqual(jobs[0]["updated_at"], "2026-10-20T00:00:00Z")

    def test_empty_public_comeet_list_is_a_valid_empty_result(self):
        class FakeClient:
            hosts = {"www.comeet.com"}
            def get(self, url, **kwargs): return "<script>COMPANY_POSITIONS_DATA = [];</script>"
        self.assertEqual(collect({"career_url": "https://www.comeet.com/jobs/test/AA.001", "ats_hint": "Comeet"}, FakeClient()), [])

    def test_nested_jsonld_and_html_cleaning(self):
        document = Path("tests/fixtures/comeet.html").read_text()
        items, links = postings(document)
        self.assertEqual(len(items), 1)
        job = normalize_posting(items[0], "https://www.comeet.com/jobs/example/AA.001/BB.002")
        self.assertEqual(job["location"], "Caesarea, Israel")
        self.assertEqual(job["source_id"], "BB.002")
        self.assertIn("Python", job["description"])

    def test_scripts_never_become_description_text(self):
        self.assertEqual(plain("<p>Test</p><script>secret()</script><p>Python</p>"), "Test\n\nPython")

    def test_tracking_params_deduplicate_without_dropping_job_identifier(self):
        self.assertEqual(canonical_url("https://example.com/job/?jobId=4&utm_source=test#tracking"), "https://example.com/job?jobId=4")

    def test_redirects_reject_local_and_cross_source_destinations(self):
        for url in ["http://example.com", "https://127.0.0.1", "https://example.com:444", "https://user:pass@example.com", "https://other.example.com"]:
            with self.assertRaises(SourceError):
                check_url(url, {"example.com"})

    def test_readable_js_shell_is_unsupported_not_empty(self):
        class FakeClient:
            hosts = {"example.com"}
            def get(self, url, **kwargs): return "<html><div id='root'></div></html>"
        with self.assertRaises(SourceError) as context:
            collect({"career_url": "https://example.com/careers", "ats_hint": "Generic HTML"}, FakeClient())
        self.assertEqual(context.exception.status, "unsupported")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "test.sqlite")
        seed(self.db)
        self.company = self.db.execute("SELECT * FROM companies WHERE name='Augury'").fetchone()
        self.job = {"source_id": "fixture-1", "title": "Junior Integration Engineer", "description": DESCRIPTION, "location": "Haifa, Israel", "url": "https://job-boards.greenhouse.io/augury/jobs/123", "status": "open"}
        self.assessment = assess(self.job["title"], self.job["description"], self.job["location"], self.company)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def save(self):
        with self.db:
            return save_job(self.db, self.company["id"], self.job, self.assessment)

    def test_seed_is_repeatable_and_keeps_current_source_state(self):
        self.db.execute("UPDATE companies SET source_status='blocked' WHERE id=?", (self.company["id"],))
        seed(self.db)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 138)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM companies WHERE enabled=1").fetchone()[0], 8)
        self.assertEqual(self.db.execute("SELECT source_status FROM companies WHERE id=?", (self.company["id"],)).fetchone()[0], "blocked")

    def test_rescan_preserves_feedback_and_does_not_duplicate(self):
        self.assertTrue(self.save())
        self.db.execute("UPDATE jobs SET fit='yes',familiar=1,application_status='applied',personal_note='follow up'")
        self.job["url"] += "?utm_source=other"
        self.assertFalse(self.save())
        job = self.db.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(job["fit"], "yes")
        self.assertEqual(job["application_status"], "applied")
        self.assertEqual(job["personal_note"], "follow up")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM job_events").fetchone()[0], 1)

    def test_updated_timestamp_alone_does_not_notify(self):
        self.save()
        self.job["updated_at"] = "2026-10-22T00:00:00Z"
        self.save()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM job_events").fetchone()[0], 1)

    def test_verified_reopening_generates_exactly_one_new_event(self):
        self.save()
        self.db.execute("UPDATE jobs SET status='closed'")
        self.save()
        self.save()
        events = self.db.execute("SELECT kind FROM job_events ORDER BY id").fetchall()
        self.assertEqual([r[0] for r in events], ["new", "reopened"])

    def test_import_before_discovery_marks_job_as_applied(self):
        file = Path(self.temp.name) / "applications.csv"
        file.write_text("url,status\n" + self.job["url"] + "?utm_source=old,applied\n")
        cli.import_applications(self.db, file)
        self.save()
        self.assertEqual(self.db.execute("SELECT application_status,familiar FROM jobs").fetchone()[:], ("applied", 1))

    def test_invalid_import_is_atomic(self):
        file = Path(self.temp.name) / "applications.csv"
        file.write_text("url,status\nhttps://example.com/job,applied\nhttp://bad,invalid\n")
        with self.assertRaises(ValueError): cli.import_applications(self.db, file)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM imports").fetchone()[0], 0)

    def test_failed_scan_does_not_close_preexisting_jobs(self):
        self.save()
        with patch("collector.cli.collect", side_effect=SourceError("blocked", "HTTP 403")):
            self.assertEqual(cli.scan(self.db, "Augury"), 1)
        self.assertEqual(self.db.execute("SELECT status FROM jobs").fetchone()[0], "open")
        self.assertIsNone(self.db.execute("SELECT job_count FROM companies WHERE id=?", (self.company["id"],)).fetchone()[0])

    def test_partial_scan_saves_complete_jobs_without_claiming_completeness_or_closing_old_jobs(self):
        self.save()
        complete = {**self.job, "source_id": "fixture-new", "url": "https://job-boards.greenhouse.io/augury/jobs/456"}
        error = SourceError("unsupported", "A detail page failed", partial_jobs=[complete])
        with patch("collector.cli.collect", side_effect=error):
            self.assertEqual(cli.scan(self.db, "Augury"), 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM jobs WHERE status='open'").fetchone()[0], 2)
        company = self.db.execute("SELECT source_status,job_count,last_result FROM companies WHERE id=?", (self.company["id"],)).fetchone()
        self.assertEqual(company["source_status"], "unsupported")
        self.assertIsNone(company["job_count"])
        self.assertIn("1 jobs extracted", company["last_result"])
        self.assertIn("A detail page failed", company["last_result"])
        self.assertEqual(self.db.execute("SELECT fetched_count FROM scans ORDER BY id DESC LIMIT 1").fetchone()[0], 1)

    def test_successful_full_api_scan_marks_missing_jobs_closed(self):
        self.save()
        with patch("collector.cli.collect", return_value=[]):
            self.assertEqual(cli.scan(self.db, "Augury"), 0)
        self.assertEqual(self.db.execute("SELECT status FROM jobs").fetchone()[0], "closed")

    def test_digest_preview_does_not_send_or_mark_notified(self):
        self.save()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch("collector.cli.urlopen") as request:
            cli.digest(self.db)
        request.assert_not_called()
        self.assertIn("Junior Integration Engineer", output.getvalue())
        self.assertIsNone(self.db.execute("SELECT notified_at FROM job_events").fetchone()[0])

    def test_digest_excludes_familiar_applied_unverified_and_low_scores(self):
        self.save()
        for field, value in [("familiar", 1), ("application_status", "applied"), ("status", "unverified"), ("score", 65)]:
            with self.subTest(field=field):
                self.db.execute(f"UPDATE jobs SET {field}=?", (value,))
                output = io.StringIO()
                with contextlib.redirect_stdout(output): cli.digest(self.db)
                self.assertNotIn("Junior Integration Engineer", output.getvalue())
                self.db.execute("UPDATE jobs SET familiar=0,application_status='not_applied',status='open',score=80")

    def test_missing_telegram_credentials_does_not_change_state(self):
        self.save()
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            cli.digest(self.db, send=True)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM digest_runs").fetchone()[0], 0)

    def test_successful_digest_sends_once_and_marks_only_after_confirmation(self):
        self.save()
        config = {"TELEGRAM_BOT_TOKEN": "test-fixture-token", "TELEGRAM_CHAT_ID": "test-chat", "APP_URL": "https://example.com"}
        with patch.dict(os.environ, config), patch("collector.cli.urlopen", return_value=io.BytesIO(b'{"ok":true}')) as request:
            cli.digest(self.db, send=True)
            cli.digest(self.db, send=True)
        self.assertEqual(request.call_count, 1)
        self.assertIsNotNone(self.db.execute("SELECT notified_at FROM job_events").fetchone()[0])
        self.assertEqual(self.db.execute("SELECT status FROM digest_runs").fetchone()[0], "sent")

    def test_uncertain_send_keeps_events_pending_and_prevents_automatic_retry(self):
        self.save()
        config = {"TELEGRAM_BOT_TOKEN": "test-fixture-token", "TELEGRAM_CHAT_ID": "test-chat", "APP_URL": "https://example.com"}
        with patch.dict(os.environ, config), patch("collector.cli.urlopen", side_effect=TimeoutError) as request:
            with self.assertRaisesRegex(ValueError, "delivery unconfirmed"):
                cli.digest(self.db, send=True)
            cli.digest(self.db, send=True)
        self.assertEqual(request.call_count, 1)
        self.assertIsNone(self.db.execute("SELECT notified_at FROM job_events").fetchone()[0])
        self.assertEqual(self.db.execute("SELECT status FROM digest_runs").fetchone()[0], "uncertain")


class ScheduleTests(unittest.TestCase):
    def test_schedule_uses_israeli_local_time_and_small_catchup_window(self):
        for month in [1, 7]:
            self.assertEqual(due(datetime(2026, month, 1, 8, 1, tzinfo=ZoneInfo("Asia/Jerusalem"))), "scan-morning")
        self.assertEqual(due(datetime(2026, 10, 22, 18, 0)), "digest")
        self.assertIsNone(due(datetime(2026, 10, 22, 18, 15)))
        self.assertIsNone(due(datetime(2026, 10, 22, 12, 0)))


if __name__ == "__main__":
    unittest.main()
