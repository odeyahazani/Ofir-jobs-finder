"""Optional real PostgreSQL tests, always against a new disposable local cluster.

OFIR_TEST_PG_BIN=/path/to/postgresql/bin python -m unittest tests/test_scheduled_concurrency.py -v
No application database URL or credentials are read. No production service is contacted.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

BIN = os.environ.get('OFIR_TEST_PG_BIN')
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(BIN, 'Set OFIR_TEST_PG_BIN to run isolated multi-session PostgreSQL tests')
class PostgreSQLConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ofir-pg-test-')
        cls.folder = Path(cls.temp.name)
        cls.bin = Path(BIN)
        cls.run_command('initdb', '-D', str(cls.folder/'data'), '--no-locale', '--encoding=UTF8', '--auth-local=trust', '--auth-host=reject')
        cls.run_command('pg_ctl', '-D', str(cls.folder/'data'), '-l', str(cls.folder/'server.log'), '-o', f"-k {cls.folder} -h '' -p 55439", '-w', 'start')
        try:
            cls.query('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS; CREATE SCHEMA auth;'
                      "CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT NULL::uuid $$;"
                      "CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$;")
            setup = (ROOT/'supabase/setup.sql').read_text().replace('REPLACE_WITH_OFIR_GOOGLE_EMAIL','fixture@example.com')
            cls.query(setup)
            cls.company = cls.query('SELECT id FROM companies ORDER BY id LIMIT 1').strip()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def run_command(cls, command, *args):
        return subprocess.run([str(cls.bin/command), *args], text=True, capture_output=True, check=True).stdout

    @classmethod
    def query(cls, sql):
        return subprocess.run([str(cls.bin/'psql'), '-X', '-v', 'ON_ERROR_STOP=1', '-At', '-h', str(cls.folder), '-p', '55439', '-d', 'postgres'],
                              input=sql, text=True, capture_output=True, check=True).stdout

    @classmethod
    def tearDownClass(cls):
        cls.run_command('pg_ctl', '-D', str(cls.folder/'data'), '-m', 'immediate', '-w', 'stop')
        cls.temp.cleanup()

    def setUp(self):
        self.query('DELETE FROM scans; DELETE FROM scheduled_slots;')
        # Create and complete real due targets, leaving only the controlled fixture claimable.
        self.query("SELECT ofir_claim_scheduled('fixture-bootstrap-token','test','test'); UPDATE scheduled_slots SET state='completed',lease_until=NULL;")
        self.query(f"INSERT INTO scheduled_slots(id,local_day,slot_name,target_at,deadline_at,company_ids) VALUES('fixture','2000-01-01','morning',clock_timestamp()-interval '2 hours',clock_timestamp()+interval '22 hours','[\"{self.company}\"]'); UPDATE companies SET enabled=1 WHERE id='{self.company}';")

    def test_two_sessions_cannot_claim_the_same_slot(self):
        def claim(token):
            return json.loads(self.query(f"SELECT ofir_claim_scheduled('{token}','test','test');").strip())
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(claim, ['concurrent-token-0001','concurrent-token-0002']))
        self.assertEqual(sum(r['outcome']=='claimed' for r in replies),1)
        self.assertEqual(next(r for r in replies if r['outcome']=='skipped')['reason'],'lease_owned')
        self.assertEqual(self.query("SELECT claims FROM scheduled_slots WHERE id='fixture'").strip(),'1')

    def test_takeover_fences_old_worker_in_another_session(self):
        self.query("SELECT ofir_claim_scheduled('old-worker-token-0001','test','test'); UPDATE scheduled_slots SET lease_until=clock_timestamp()-interval '1 second' WHERE id='fixture'; SELECT ofir_claim_scheduled('new-worker-token-0001','test','test');")
        with self.assertRaises(subprocess.CalledProcessError) as error:
            self.query(f"SELECT ofir_begin_scheduled_company('fixture','old-worker-token-0001','{self.company}');")
        self.assertIn('lease lost',error.exception.stderr)
        self.assertEqual(self.query("SELECT count(*) FROM scans WHERE scheduled_slot_id='fixture'").strip(),'0')

    def test_checkpoint_rechecks_lease_after_waiting_for_sync_lock(self):
        self.query(f"SELECT ofir_claim_scheduled('old-worker-token-0001','test','test'); SELECT ofir_begin_scheduled_company('fixture','old-worker-token-0001','{self.company}'); UPDATE scheduled_slots SET lease_until=clock_timestamp()+interval '1 second' WHERE id='fixture';")
        # Hold the shared sync lock in a separate connection. Wait for server evidence,
        # not a timing assumption, before launching the checkpoint.
        with ThreadPoolExecutor(2) as pool:
            blocker = pool.submit(self.query,"BEGIN; SELECT pg_advisory_xact_lock(4801739); SELECT pg_sleep(2); COMMIT;")
            for _ in range(100):
                locked=self.query("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=4801739 AND granted").strip()
                if locked=='1': break
                time.sleep(.01)
            self.assertEqual(locked,'1')
            with self.assertRaises(subprocess.CalledProcessError) as error:
                self.query(f"SELECT ofir_checkpoint_scheduled('fixture','old-worker-token-0001','{self.company}','{{\"status\":\"ok\"}}','{{}}');")
            self.assertIn('lease lost',error.exception.stderr)
            blocker.result()
        self.assertEqual(self.query("SELECT status FROM scans WHERE scheduled_slot_id='fixture'").strip(),'running')


if __name__ == '__main__': unittest.main()
