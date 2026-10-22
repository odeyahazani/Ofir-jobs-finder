import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from collector.cloud import Remote, restore, snapshot, import_cloud_applications
from collector.store import connect, seed, save_job
from collector.scoring import assess
from collector import cli
from scripts.build_supabase_setup import generate


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "test.sqlite")
        seed(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def job(self):
        company = self.db.execute("SELECT * FROM companies WHERE name='Augury'").fetchone()
        job = {"source_id": "cloud-fixture", "title": "TEST ONLY Junior Integration Engineer", "location": "Haifa, Israel",
               "description": "Junior lab integration. Python MATLAB, optics, sensors and signal processing. 0-1 years experience.",
               "url": "https://example.com/cloud-fixture", "status": "open"}
        with self.db:
            save_job(self.db, company["id"], job, assess(job["title"], job["description"], job["location"], company))

    def test_generated_setup_matches_checked_in_sql(self):
        self.assertEqual(Path("supabase/setup.sql").read_text(), generate())
        self.assertEqual(generate().count("REPLACE_WITH_OFIR_GOOGLE_EMAIL"), 1)

    def test_restored_snapshot_retains_feedback_and_event_identity(self):
        self.job()
        self.db.execute("UPDATE jobs SET fit='yes',application_status='applied',personal_note='keep this'")
        data = snapshot(self.db, migrate=True)
        remote = MagicMock()
        remote.rows.side_effect = lambda name: data[name]
        with connect(Path(self.temp.name) / "restored.sqlite") as target:
            restore(target, remote)
            job = target.execute("SELECT * FROM jobs").fetchone()
            self.assertEqual(job["application_status"], "applied")
            self.assertEqual(job["personal_note"], "keep this")
            self.assertEqual(target.execute("SELECT COUNT(*) FROM job_events").fetchone()[0], 1)

    def test_missing_seed_is_not_treated_as_successful_empty_scan(self):
        remote = MagicMock()
        remote.rows.return_value = []
        with self.assertRaisesRegex(RuntimeError, "seed is missing"):
            restore(self.db, remote)

    def test_cloud_import_does_not_replay_unrelated_historical_records(self):
        with self.db:
            self.db.execute("INSERT INTO imports VALUES ('https://example.com/old','applied',NULL,'2026-01-01')")
        path = Path(self.temp.name) / "new.csv"
        path.write_text("url,status\nhttps://example.com/new,applied\n")
        remote = MagicMock()
        import_cloud_applications(self.db, remote, path)
        records = remote.rpc.call_args.args[1]["records"]
        self.assertEqual([row["canonical_url"] for row in records], ["https://example.com/new"])

    def test_cloud_snapshot_does_not_override_remote_notification_reservations(self):
        self.assertNotIn("digest_runs", snapshot(self.db))
        self.assertIn("digest_runs", snapshot(self.db, migrate=True))

    def test_remote_settings_require_https_project_host_and_a_worker_key(self):
        for url in ["http://example.supabase.co", "https://localhost", "https://x.supabase.co/path", "https://x.supabase.co:444", "https://user:pass@x.supabase.co"]:
            with self.subTest(url=url), patch.dict(os.environ, {"NEXT_PUBLIC_SUPABASE_URL": url, "SUPABASE_SERVICE_ROLE_KEY": "fixture"}):
                with self.assertRaises(ValueError): Remote()
        with patch.dict(os.environ, {"NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "securely"): Remote()

    def test_pagination_uses_an_explicit_stable_order_and_reads_all_pages(self):
        with patch.dict(os.environ, {"NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "fixture"}):
            remote = Remote()
        remote.request = MagicMock(side_effect=[[{"id": n} for n in range(500)], [{"id": 500}], []])
        self.assertEqual(len(remote.rows("jobs")), 501)
        self.assertIn("offset=501", remote.request.call_args[0][0])
        self.assertIn("order=id.asc", remote.request.call_args[0][0])

    def test_lower_server_row_limit_does_not_truncate_the_snapshot(self):
        with patch.dict(os.environ, {"NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "fixture"}):
            remote = Remote()
        remote.request = MagicMock(side_effect=[[{"id": 1}], [{"id": 2}], []])
        self.assertEqual([row["id"] for row in remote.rows("jobs")], [1, 2])

    def test_cloud_digest_reserves_before_network_and_finishes_after_confirmation(self):
        self.job()
        remote = MagicMock()
        remote.reserve_digest.return_value = True
        config = {"TELEGRAM_BOT_TOKEN": "fixture-token", "TELEGRAM_CHAT_ID": "fixture-chat", "APP_URL": "https://example.com"}
        def sent(*args, **kwargs):
            remote.reserve_digest.assert_called_once()
            remote.finish_digest.assert_not_called()
            return io.BytesIO(b'{"ok":true}')
        with patch.dict(os.environ, config), patch("collector.cli.urlopen", side_effect=sent):
            cli.digest(self.db, send=True, delivery_store=remote)
        self.assertEqual(remote.finish_digest.call_args.args[1], "sent")
        self.assertEqual(len(remote.finish_digest.call_args.args[2]), 1)

    def test_existing_cloud_reservation_prevents_duplicate_delivery(self):
        self.job()
        remote = MagicMock()
        remote.reserve_digest.return_value = False
        config = {"TELEGRAM_BOT_TOKEN": "fixture-token", "TELEGRAM_CHAT_ID": "fixture-chat", "APP_URL": "https://example.com"}
        with patch.dict(os.environ, config), patch("collector.cli.urlopen") as network:
            cli.digest(self.db, send=True, delivery_store=remote)
        network.assert_not_called()
        remote.finish_digest.assert_not_called()

    def test_network_timeout_retains_uncertain_cloud_reservation(self):
        self.job()
        remote = MagicMock()
        remote.reserve_digest.return_value = True
        config = {"TELEGRAM_BOT_TOKEN": "fixture-token", "TELEGRAM_CHAT_ID": "fixture-chat", "APP_URL": "https://example.com"}
        with patch.dict(os.environ, config), patch("collector.cli.urlopen", side_effect=TimeoutError):
            with self.assertRaisesRegex(ValueError, "unconfirmed"):
                cli.digest(self.db, send=True, delivery_store=remote)
        self.assertEqual(remote.finish_digest.call_args.args[1], "uncertain")


if __name__ == "__main__":
    unittest.main()
