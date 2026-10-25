from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import os
from collector.growth import new_sources, scheduled_slot
from collector.store import connect, seed
from collector.cli import scan
from collector.sources import Client, SourceError


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "test.sqlite")
        seed(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_expansion_is_small_relevant_and_uses_supported_sources(self):
        ids = new_sources(self.db, 2)
        self.assertEqual(len(ids), 2)
        for id in ids:
            company = self.db.execute("SELECT * FROM companies WHERE id=?", (id,)).fetchone()
            self.assertEqual(company["enabled"], 0)
            self.assertIn(company["ats_hint"], {"Greenhouse", "Comeet"})
            self.assertTrue("אופיר" in company["notes"] or "Ofir" in company["notes"])
        self.assertEqual(new_sources(self.db, 0), [])
        with self.assertRaises(ValueError): new_sources(self.db, 50)

    def test_checked_sources_are_not_automatically_added_again(self):
        ids = new_sources(self.db, 5)
        with self.db:
            for id in ids: self.db.execute("UPDATE companies SET last_checked='2026-10-25',enabled=0 WHERE id=?", (id,))
        self.assertFalse(set(ids) & set(new_sources(self.db, 5)))

    def test_user_opt_out_is_respected_even_for_a_never_scanned_source(self):
        id = new_sources(self.db, 1)[0]
        with self.db: self.db.execute("INSERT INTO company_monitor_controls VALUES (?,1)", (id,))
        self.assertNotIn(id, new_sources(self.db, 5))

    def test_scan_budget_rotates_oldest_sources_and_records_actual_outcome(self):
        with self.db:
            self.db.execute("UPDATE companies SET last_checked='2026-10-25T12:00:00+00:00' WHERE enabled=1")
            self.db.execute("UPDATE companies SET last_checked=NULL WHERE name='Augury'")
        with patch("collector.cli.collect", return_value=[]) as collect:
            self.assertEqual(scan(self.db, limit=1), 0)
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(collect.call_args.args[0]["name"], "Augury")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 1)

    def test_schedule_follows_israeli_daylight_saving(self):
        self.assertTrue(scheduled_slot(datetime(2026, 7, 1, 5, 17, tzinfo=timezone.utc)))
        self.assertFalse(scheduled_slot(datetime(2026, 7, 1, 6, 17, tzinfo=timezone.utc)))
        self.assertTrue(scheduled_slot(datetime(2026, 12, 1, 6, 17, tzinfo=timezone.utc)))
        self.assertTrue(scheduled_slot(datetime(2026, 12, 1, 15, 17, tzinfo=timezone.utc)))

    def test_new_sources_cannot_fetch_private_network_addresses(self):
        company = {"name": "Fixture", "career_url": "https://example.com/careers"}
        client = Client(company)
        client.opener = MagicMock()
        with patch("collector.sources.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(SourceError) as error: client.raw(company["career_url"])
        self.assertEqual(error.exception.status, "blocked")
        client.opener.open.assert_not_called()

    def test_reviewed_sources_can_use_a_managed_https_proxy_without_local_dns(self):
        import socket
        client = Client({"name": "Augury", "career_url": "https://job-boards.greenhouse.io/augury"})
        client.opener = MagicMock()
        client.opener.open.return_value.__enter__.return_value.read.return_value = b"public fixture"
        with patch.dict(os.environ, {"HTTPS_PROXY": "https://fixture-proxy.example"}), patch("collector.sources.socket.getaddrinfo", side_effect=socket.gaierror):
            self.assertEqual(client.raw("https://boards-api.greenhouse.io/v1/boards/augury/jobs"), "public fixture")
            with self.assertRaises(SourceError): Client({"name": "Imported", "career_url": "https://unreviewed.example.com/jobs"}).raw("https://unreviewed.example.com/jobs")


if __name__ == "__main__": unittest.main()
