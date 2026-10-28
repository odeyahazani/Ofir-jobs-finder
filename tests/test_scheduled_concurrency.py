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
class PostgreSQLHarness(unittest.TestCase):
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

class PostgreSQLConcurrencyTests(PostgreSQLHarness):
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



    def test_worker_lifecycle_persists_and_reconciles_against_real_postgres(self):
        from unittest.mock import patch
        import contextlib, io
        from collector import scheduled
        harness=self
        class RemoteFixture:
            def ensure_matching_schema(self):
                harness.query('SELECT match_version FROM jobs LIMIT 1')
            def rows(self, table):
                return json.loads(harness.query(f"SELECT coalesce(jsonb_agg(to_jsonb(t)),'[]') FROM public.{table} t").strip())
            def rpc(self, name, body):
                def literal(value):
                    if value is None: return 'NULL'
                    value=json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value)
                    return "'"+value.replace("'","''")+"'"
                args=','.join(k+'=>'+literal(v) for k,v in body.items())
                output=harness.query(f'SET ROLE service_role; SELECT public.{name}({args}); RESET ROLE;')
                return next(json.loads(line) for line in output.splitlines() if line.startswith('{'))
        job={'source_id':'worker-fixture','title':'Integration Engineer','description':'Integration testing. Requirements: Python, 0-1 years experience.',
             'location':'Haifa, Israel','url':'https://example.com/original','status':'open'}
        with tempfile.TemporaryDirectory() as temp, patch.object(scheduled,'REPORT_PATH',Path(temp)/'report.json'), contextlib.redirect_stdout(io.StringIO()):
            with patch('collector.cli.collect',return_value=[job]):
                self.assertEqual(scheduled.run(RemoteFixture),0)
            first=json.loads(self.query('SELECT to_jsonb(j) FROM jobs j').strip())
            self.assertEqual(self.query('SELECT count(*) FROM job_events').strip(),'1')
            report=json.loads((Path(temp)/'report.json').read_text())
            self.assertEqual(report['invocation_jobs_inserted'],1)
            self.assertEqual(report['slot']['checked'],1)
            self.query("UPDATE jobs SET personal_note='הערה',application_status='interviewing',fit='yes';")
            self.query(f"INSERT INTO scheduled_slots(id,local_day,slot_name,target_at,deadline_at,company_ids) VALUES('fixture-second','2000-01-02','evening',clock_timestamp()-interval '1 hour',clock_timestamp()+interval '23 hours','[\"{self.company}\"]');")
            with patch('collector.cli.collect',return_value=[{**job,'url':'https://example.com/changed','title':'Integration Engineer updated'}]):
                self.assertEqual(scheduled.run(RemoteFixture),0)
            second=json.loads(self.query('SELECT to_jsonb(j) FROM jobs j').strip())
            for key in ('id','first_seen_at'): self.assertEqual(second[key],first[key])
            self.assertEqual(second['personal_note'],'הערה')
            self.assertEqual(second['application_status'],'interviewing')
            self.assertEqual(second['url'],'https://example.com/changed')
            self.assertEqual(self.query('SELECT count(*) FROM job_events').strip(),'1')
            report=json.loads((Path(temp)/'report.json').read_text())
            self.assertEqual(report['invocation_jobs_inserted'],0)
            self.assertEqual(report['invocation_jobs_updated'],1)
            with patch('collector.cli.collect') as collect:
                self.assertEqual(scheduled.run(RemoteFixture),0)
                collect.assert_not_called()

# Recovery uses synthetic data and private temporary CSVs, never user exports.
@unittest.skipUnless(BIN, 'Set OFIR_TEST_PG_BIN for isolated recovery tests')
class RecoveryTests(PostgreSQLHarness):
    def setUp(self):
        # Every recovery experiment gets a separate database, including object state.
        import uuid
        type(self).database = 'recovery_' + uuid.uuid4().hex
        super().query('CREATE DATABASE ' + self.database)
        setup = (ROOT/'supabase/setup.sql').read_text()
        scheduling = (ROOT/'supabase/006_scheduling.sql').read_text()
        setup = setup.replace(scheduling, '').replace('REPLACE_WITH_OFIR_GOOGLE_EMAIL','fixture@example.com')
        self.query("CREATE SCHEMA auth; CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT NULL::uuid $$; CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$;")
        self.query(setup)

    @classmethod
    def query(cls, sql):
        return subprocess.run([str(cls.bin/'psql'), '-X', '-v', 'ON_ERROR_STOP=1', '-At', '-h', str(cls.folder), '-p', '55439', '-d', getattr(cls,'database','postgres')],
                              input=sql, text=True, capture_output=True, check=True).stdout

    def tearDown(self):
        super().query('DROP DATABASE ' + self.database)

    def snapshot(self):
        return {t:self.query(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]') FROM public.{t} t").strip()
                for t in ['companies','jobs','job_events','scans','imports','digest_runs','company_monitor_controls','job_discoveries']}

    def seed_synthetic(self):
        self.query("""INSERT INTO jobs(id,company_id,source_id,title,location,url,description,first_seen_at,last_seen_at,last_verified_at,
         score,breakdown,reasons,gaps,experience,eligible,content_hash,fit,personal_note,application_status,match_version)
         SELECT 'j'||n,(SELECT id FROM companies ORDER BY id LIMIT 1),'s'||n,'Fixture','Israel','https://example.com/'||n,
          'Synthetic','2026-01-01','2026-01-02','2026-01-02',70,'{}','[]','[]','research',1,'hash','yes',E'עברית, "quoted"\\nsecond line','interviewing','fixture'
         FROM generate_series(1,419) n;
         INSERT INTO job_events(job_id,version,kind,created_at) SELECT id,1,'new','2026-01-01' FROM jobs;
         INSERT INTO scans(company_id,started_at,status) SELECT id,'2026-01-01','ok' FROM companies;
         INSERT INTO imports VALUES('https://example.com/1','applied','2026-01-01','2026-01-01');
         INSERT INTO digest_runs(day,status,created_at) VALUES('2026-01-01','sent','2026-01-01');
         INSERT INTO company_monitor_controls SELECT id,1 FROM companies ORDER BY id LIMIT 1;
         INSERT INTO job_discoveries(id,company_id,company_name,title,url,added_at) SELECT 'finding',id,name,'Fixture','https://example.com/finding','2026-01-01' FROM companies ORDER BY id LIMIT 1;
        """)

    def test_upgrade_repeatability_and_code_rollback(self):
        self.seed_synthetic()
        before=self.snapshot()
        migration=(ROOT/'supabase/upgrade-scheduling.sql').read_text()
        self.query(migration); self.query(migration)
        # Old scan columns unchanged; the only extra values are nullable scheduling metadata.
        after=self.snapshot()
        rows=json.loads(after['scans'])
        for row in rows:
            for col in ['scheduled_slot_id','scheduled_attempt','retry_kind','retry_after','checkpoint_receipt']:
                self.assertIsNone(row.pop(col))
        self.assertEqual(rows,json.loads(before['scans']))
        for table in before.keys()-{'scans'}: self.assertEqual(after[table],before[table],table)
        # Legacy worker's existing sync contract still operates after upgrade (code rollback).
        payload={table:json.loads(data) for table,data in before.items()}
        for job in payload['jobs']:
            job['personal_note']='stale legacy note'
            job['application_status']='not_applied'
        encoded=json.dumps(payload,ensure_ascii=False).replace("'","''")
        self.query("SET ROLE service_role; SELECT ofir_sync('"+encoded+"'::jsonb); RESET ROLE;")
        self.assertEqual(self.snapshot(),after)

    def test_failed_migration_rolls_back_schema_and_data(self):
        self.seed_synthetic(); before=self.snapshot()
        migration=(ROOT/'supabase/upgrade-scheduling.sql').read_text().replace('COMMIT;','SELECT 1/0; COMMIT;')
        with self.assertRaises(subprocess.CalledProcessError): self.query(migration)
        self.assertEqual(self.query("SELECT to_regclass('public.scheduled_slots') IS NULL").strip(),'t')
        self.assertEqual(self.snapshot(),before)

    def test_csv_roundtrip_restores_rows_but_requires_schema_and_sequences(self):
        self.seed_synthetic(); before=self.snapshot()
        tables=['companies','company_monitor_controls','imports','jobs','job_events','scans','digest_runs','job_discoveries']
        csvs={t:self.query(f'COPY public.{t} TO STDOUT WITH CSV HEADER') for t in tables}
        self.query('TRUNCATE ' + ','.join('public.'+t for t in tables) + ' CASCADE;')  # Only disposable synthetic database.
        self.query('DELETE FROM private.ofir_owner;')  # Not included in public CSV exports.
        for t in tables:
            try:
                self.query(f'COPY public.{t} FROM STDIN WITH CSV HEADER;\n'+csvs[t]+chr(92)+'.\n')
            except subprocess.CalledProcessError as error:
                self.fail(t + ': ' + error.stderr)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.query('SELECT count(*) FROM private.ofir_owner').strip(),'0')
        # Restoring into existing schema kept original sequence counters; rebuilding schema
        # does not. Force the latter condition and demonstrate required reconciliation.
        self.query("ALTER SEQUENCE scans_id_seq RESTART WITH 1;")
        with self.assertRaises(subprocess.CalledProcessError):
            self.query("INSERT INTO scans(company_id,started_at,status) SELECT id,'2026-02-01','ok' FROM companies LIMIT 1;")
        self.query("SELECT setval(pg_get_serial_sequence('public.scans','id'),(SELECT max(id) FROM scans),true);")
        self.query("INSERT INTO scans(company_id,started_at,status) SELECT id,'2026-02-01','ok' FROM companies LIMIT 1;")

    def test_indicator_script_and_boundary_variations(self):
        from scripts.build_release_check import generate
        diagnostic=generate()
        self.assertEqual((ROOT/'supabase/release-readiness-check.sql').read_text(),diagnostic)
        def result():
            lines=self.query(diagnostic).splitlines()
            return next(json.loads(line) for line in lines if line.startswith('{'))
        self.assertEqual(result()['compatibility'],'PASS')
        self.query("""DO $$ DECLARE body text; BEGIN
          SELECT prosrc INTO body FROM pg_proc WHERE oid='public.ofir_sync(jsonb)'::regprocedure;
          EXECUTE format('CREATE OR REPLACE FUNCTION ofir_sync(payload jsonb) RETURNS void LANGUAGE plpgsql SET search_path='''' AS %L', E'  \\n' || body || E'\\n  ');
          END $$;""")
        self.assertEqual(result()['compatibility'],'PASS')
        self.query("ALTER ROLE service_role NOBYPASSRLS;")
        self.assertEqual(result()['compatibility'],'REVIEW_REQUIRED')
        self.query("ALTER ROLE service_role BYPASSRLS;")
        self.query('REVOKE UPDATE ON public.jobs FROM service_role;')
        self.assertFalse(result()['worker_table_grants'])
        self.query('GRANT UPDATE ON public.jobs TO service_role;')
        self.query('DROP INDEX public.scans_source_start;')
        self.assertFalse(result()['required_unique_keys'])
        self.query('CREATE UNIQUE INDEX scans_source_start ON public.scans(company_id,started_at);')
        self.query('ALTER TABLE public.jobs RENAME COLUMN match_version TO renamed_version;')
        self.assertFalse(result()['table_schema_compatible'])
        self.query('ALTER TABLE public.jobs RENAME COLUMN renamed_version TO match_version;')
        self.assertEqual(result()['compatibility'],'PASS')
        self.query((ROOT/'supabase/upgrade-scheduling.sql').read_text())
        self.assertFalse(result()['scheduling_rpc_collision_free'])
