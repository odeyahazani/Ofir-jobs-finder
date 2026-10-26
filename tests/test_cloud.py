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
from scripts.export_cloud_bootstrap import export, batch_payload, data_statement


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
               "description": "Description\nJunior lab integration. Python MATLAB, optics, sensors and signal processing.\nRequirements\n0-1 years experience.",
               "url": "https://example.com/cloud-fixture", "status": "open"}
        with self.db:
            save_job(self.db, company["id"], job, assess(job["title"], job["description"], job["location"], company))

    def test_generated_setup_matches_checked_in_sql(self):
        self.assertEqual(Path("supabase/setup.sql").read_text(), generate())
        self.assertEqual(generate().count("REPLACE_WITH_OFIR_GOOGLE_EMAIL"), 1)

    def test_export_provides_a_private_data_only_file_without_function_definitions(self):
        self.job()
        target = Path(self.temp.name) / "transfer.sql"
        parts = export(Path(self.temp.name) / "test.sqlite", target)
        data = target.with_name("transfer-data-only.sql").read_text()
        self.assertNotIn("CREATE OR REPLACE FUNCTION", data)
        self.assertIn("SELECT public.ofir_sync($ofir_snapshot$", data)
        self.assertTrue(data.rstrip().endswith("COMMIT;"))
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        manifest = json.loads(target.with_name("transfer-parts.json").read_text())
        self.assertEqual([part.name for part in parts], [entry["file"] for entry in manifest])
        self.assertEqual(len(parts), 1)
        self.assertEqual(manifest[0]["records"]["jobs"], 1)
        for part, entry in zip(parts, manifest):
            self.assertEqual(part.stat().st_size, entry["bytes"])
            self.assertLessEqual(entry["bytes"], 700_000)
            self.assertEqual(part.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("CREATE OR REPLACE FUNCTION", part.read_text())

    def test_sql_editor_parts_bound_utf8_bytes_preserve_every_record_and_keep_dependencies(self):
        payload = {"companies": [{"id": "c"}], "jobs": [{"id": str(i), "description": "א" * 1500} for i in range(8)], "job_events": [{"job_id": str(i)} for i in range(8)]}
        batches = batch_payload(payload, max_bytes=9000)
        self.assertGreater(len(batches), 1)
        self.assertTrue(all(len(data_statement(part, "999/999").encode()) <= 9000 for part in batches))
        for table in payload:
            self.assertEqual([row for part in batches for row in part.get(table, [])], payload[table])
        seen_companies, seen_jobs = set(), set()
        for part in batches:
            seen_companies.update(row["id"] for row in part.get("companies", []))
            for row in part.get("jobs", []):
                self.assertIn("c", seen_companies); seen_jobs.add(row["id"])
            for row in part.get("job_events", []): self.assertIn(row["job_id"], seen_jobs)

    def test_sql_editor_export_rejects_oversized_records_without_truncating_them(self):
        with self.assertRaisesRegex(ValueError, "single record"):
            batch_payload({"jobs": [{"description": "x" * 20000}]}, max_bytes=9000)
        with self.assertRaisesRegex(ValueError, "Unknown snapshot"):
            batch_payload({"unrecognized": [{"id": "x"}]})

    def test_restored_snapshot_retains_feedback_and_event_identity(self):
        self.job()
        self.db.execute("UPDATE jobs SET fit='yes',application_status='applied',personal_note='keep this'")
        data = snapshot(self.db, migrate=True)
        remote = MagicMock()
        remote.rows.side_effect = lambda name: data.get(name, [])
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

    def test_profile_writes_require_additive_schema_with_an_actionable_error(self):
        with patch.dict(os.environ, {"NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "fixture"}):
            remote = Remote()
        remote.request = MagicMock(side_effect=RuntimeError('Supabase HTTP 400'))
        with self.assertRaisesRegex(RuntimeError, 'upgrade-matching.sql'):
            remote.ensure_matching_schema()
        self.assertEqual(remote.request.call_args.args, ('jobs?select=match_category,match_version,match_details&limit=1',))

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

    def test_monitor_controls_page_uses_its_actual_primary_key(self):
        with patch.dict(os.environ, {"NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "fixture"}): remote = Remote()
        remote.request = MagicMock(return_value=[])
        remote.rows("company_monitor_controls")
        self.assertIn("order=company_id.asc", remote.request.call_args.args[0])

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
