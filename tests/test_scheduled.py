import contextlib
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from collector import cli, scheduled
from collector.sources import SourceError, Client
from collector.store import connect, seed


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.report = Path(self.temp.name) / 'report.json'
        self.patch = patch.object(scheduled, 'REPORT_PATH', self.report)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_targets_follow_spring_and_autumn_israeli_dst(self):
        for day, hour in [('2026-03-26', 6), ('2026-03-27', 5), ('2026-10-24', 5), ('2026-10-25', 6)]:
            current = datetime.fromisoformat(day + 'T12:00:00+00:00')
            morning = next(t for t in scheduled.targets(current) if t.date().isoformat() == day and t.hour == 8)
            self.assertEqual(morning.astimezone(timezone.utc).hour, hour)
            self.assertEqual(morning.minute, 17)

    def test_delayed_and_missed_triggers_remain_due_outside_target_hour(self):
        current = datetime.fromisoformat('2026-10-25T17:40:00+00:00')
        due = scheduled.due_targets(current)
        self.assertEqual([(t.day, t.hour) for t in due], [(25, 8), (25, 17)])

    def test_midnight_recovery_and_elapsed_24_hour_expiry(self):
        current = datetime.fromisoformat('2026-10-26T00:30:00+02:00')
        self.assertEqual([(t.day, t.hour) for t in scheduled.due_targets(current)], [(25, 8), (25, 17)])
        target = scheduled.due_targets(current)[0].astimezone(timezone.utc)
        self.assertNotIn(target, [t.astimezone(timezone.utc) for t in scheduled.due_targets(target + timedelta(hours=24))])

    def test_no_work_never_restores_snapshot_or_collects(self):
        remote = MagicMock()
        remote.rpc.return_value = {'outcome': 'skipped', 'reason': 'no_eligible_work', 'expired_slots': []}
        with patch('collector.cloud.restore') as restore, patch('collector.cli.scan') as scan:
            self.assertEqual(scheduled.run(lambda: remote), 0)
        restore.assert_not_called(); scan.assert_not_called()
        self.assertEqual(remote.rpc.call_count, 1)
        self.assertEqual(json.loads(self.report.read_text())['outcome'], 'skipped')

    def test_expired_slots_fail_invocation_even_when_no_work_is_claimed(self):
        remote = MagicMock()
        remote.rpc.return_value = {'outcome': 'skipped', 'reason': 'no_eligible_work', 'expired_slots': ['2026-10-25/morning']}
        self.assertEqual(scheduled.run(lambda: remote), 1)

    def test_constructor_failure_still_writes_sanitized_report(self):
        def broken(): raise RuntimeError('SECRET_MUST_NOT_APPEAR')
        self.assertEqual(scheduled.run(broken), 1)
        self.assertNotIn('SECRET_MUST_NOT_APPEAR', self.report.read_text())
        self.assertEqual(json.loads(self.report.read_text())['outcome'], 'failed')

    def test_lost_checkpoint_acknowledgement_replays_identical_rpc_not_source(self):
        remote = MagicMock()
        receipt = {'inserted': 1, 'updated': 0, 'persistence': 'confirmed'}
        remote.rpc.side_effect = [RuntimeError('response lost'), receipt]
        body = {'slot_id': 'fixture', 'worker_token': 'same-token', 'payload': {'jobs': []}}
        self.assertEqual(scheduled.rpc(remote, 'ofir_checkpoint_scheduled', body), receipt)
        self.assertEqual(remote.rpc.call_args_list[0], remote.rpc.call_args_list[1])

    def test_database_failure_is_bounded_to_one_rpc_replay(self):
        remote = MagicMock(); remote.rpc.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError): scheduled.rpc(remote, 'ofir_claim_scheduled', {})
        self.assertEqual(remote.rpc.call_count, 2)

    def test_worker_checkpoint_uses_only_failed_or_unchecked_companies(self):
        remote = MagicMock()
        slot = {'id': 'fixture', 'target_at': '2026-10-25T06:17:00+00:00', 'company_ids': ['a','b'],
                'companies': [{'company_id': 'a', 'state': 'checked'}, {'company_id': 'b', 'state': 'ready'}]}
        calls = []
        def rpc(name, body):
            calls.append((name, body))
            if name == 'ofir_claim_scheduled': return {'outcome': 'claimed', 'slot': slot}
            if name == 'ofir_begin_scheduled_company': return {'status': 'running'}
            if name == 'ofir_checkpoint_scheduled': return {'inserted':0,'updated':0,'persistence':'confirmed'}
            if name == 'ofir_finish_scheduled': return {**slot, 'state':'completed'}
            return slot
        remote.rpc.side_effect = rpc
        def restore(db, remote):
            seed(db)
            # Use a real row with id b, preserving the rest of its schema.
            db.execute("UPDATE companies SET id='b' WHERE name='Augury'")
            db.commit()
        with patch('collector.cloud.restore', side_effect=restore), patch('collector.cli.collect', return_value=[]) as collect:
            self.assertEqual(scheduled.run(lambda:remote),0)
        self.assertEqual(collect.call_count,1)
        begins = [body['company'] for name,body in calls if name=='ofir_begin_scheduled_company']
        self.assertEqual(begins,['b'])
        self.assertEqual(json.loads(self.report.read_text())['invocation_checked'],1)

    def test_two_lost_replies_resolve_persistence_without_false_invocation_counts(self):
        remote = MagicMock()
        slot = {'id': 'fixture', 'target_at': '2026-10-25T06:17:00+00:00', 'company_ids': ['a','b'],
                'companies': [{'company_id': 'a', 'state': 'checked'}, {'company_id': 'b', 'state': 'ready'}]}
        calls = []
        def rpc(name, body):
            calls.append((name, body))
            if name == 'ofir_claim_scheduled': return {'outcome': 'claimed', 'slot': slot}
            if name == 'ofir_begin_scheduled_company': return {'status': 'running', 'id':42}
            if name == 'ofir_checkpoint_scheduled': raise RuntimeError('lost reply')
            if name == 'ofir_scheduled_report': return {**slot,'companies':[{'last_scan_id':42,'checkpoint_confirmed':True}]}
            if name == 'ofir_finish_scheduled': return {**slot, 'state':'completed'}
            return slot
        remote.rpc.side_effect = rpc
        def restore(db, remote):
            seed(db)
            # Use a real row with id b, preserving the rest of its schema.
            db.execute("UPDATE companies SET id='b' WHERE name='Augury'")
            db.commit()
        with patch('collector.cloud.restore', side_effect=restore), patch('collector.cli.collect', return_value=[]) as collect:
            self.assertEqual(scheduled.run(lambda:remote),1)
        self.assertEqual(collect.call_count,1)
        begins = [body['company'] for name,body in calls if name=='ofir_begin_scheduled_company']
        self.assertEqual(begins,['b'])
        report=json.loads(self.report.read_text())
        self.assertIsNone(report['invocation_checked'])
        self.assertEqual(report['persistence'],'confirmed')
        self.assertEqual(sum(n=='ofir_checkpoint_scheduled' for n,b in calls),2)

    def test_cancelled_report_has_explicit_incomplete_summary(self):
        self.report.write_text(json.dumps({'outcome':'running','persistence':'unconfirmed'}))
        destination=Path(self.temp.name)/'summary.md'
        with patch.dict('os.environ', {'GITHUB_STEP_SUMMARY':str(destination)}): scheduled.render_summary(self.report)
        self.assertIn('הופסק',destination.read_text())
        self.assertIn('unconfirmed',destination.read_text())

    def test_source_classification_is_explicit_and_honours_retry_after(self):
        for code, retryable in [(403,False),(404,False),(429,True),(500,True),(503,True)]:
            client=Client({'name':'Augury','career_url':'https://job-boards.greenhouse.io/augury'})
            client.opener=MagicMock()
            client.opener.open.side_effect=HTTPError('https://boards-api.greenhouse.io/x',code,'fixture',{'Retry-After':'7200'},None)
            with patch('collector.sources.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]):
                with self.assertRaises(SourceError) as caught: client.raw('https://boards-api.greenhouse.io/x')
            self.assertEqual(caught.exception.retryable,retryable)
            self.assertEqual(caught.exception.retry_after,7200)
        self.assertFalse(SourceError('unsupported','layout').retryable)
        self.assertFalse(SourceError('blocked','robots').retryable)
        self.assertTrue(SourceError('error','timeout').retryable)

    def test_partial_failure_checkpoints_good_data_and_never_closes_missing_jobs(self):
        with connect(Path(self.temp.name)/'db.sqlite') as db:
            seed(db)
            company = db.execute("SELECT id FROM companies WHERE name='Augury'").fetchone()[0]
            job={'source_id':'fixture','title':'Fixture Engineer','description':'Integration engineering. Requirements: Python.',
                 'location':'Haifa, Israel','url':'https://example.com/fixture','status':'open'}
            saved=[]
            error=SourceError('error','partial timeout',partial_jobs=[job],retryable=True)
            with patch('collector.cli.collect',side_effect=error):
                self.assertEqual(cli.scan(db,company_ids=[company],checkpoint=lambda *args:saved.append(args)),1)
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
            self.assertTrue(saved[0][1]); self.assertEqual(saved[0][0]['fetched_count'],1)
            before={r['id']:dict(r) for r in db.execute('SELECT * FROM jobs')}
            with patch('collector.cli.collect',side_effect=SourceError('blocked','robots')):
                cli.scan(db,company_ids=[company])
            self.assertEqual(before,{r['id']:dict(r) for r in db.execute('SELECT * FROM jobs')})

    def test_inconclusive_recheck_retains_last_verified_timestamp(self):
        with connect(Path(self.temp.name)/'history.sqlite') as db:
            seed(db)
            company = db.execute("SELECT * FROM companies WHERE name='Augury'").fetchone()
            from collector.store import save_job
            from collector.scoring import assess
            job = {'source_id':'known', 'title':'Engineer', 'description':'Requirements: Python',
                   'location':'Haifa, Israel', 'url':'https://example.com/known', 'status':'open'}
            assessment = assess(job['title'],job['description'],job['location'],company)
            save_job(db,company['id'],job,assessment)
            verified = db.execute('SELECT first_seen_at,last_verified_at FROM jobs').fetchone()
            save_job(db,company['id'],{**job, 'status':'unverified'},assessment)
            after = db.execute('SELECT first_seen_at,last_verified_at,status FROM jobs').fetchone()
            self.assertEqual(tuple(after)[:2],tuple(verified))
            self.assertEqual(after['status'],'unverified')

    def test_detail_failures_reach_retry_ledger_instead_of_success(self):
        from collector.sources import collect
        company={'name':'Fixture','ats_hint':'Greenhouse','ats_identifier':'fixture','career_url':'https://job-boards.greenhouse.io/fixture'}
        board=json.dumps({'jobs':[{'id':1,'title':'Engineer','absolute_url':'https://job-boards.greenhouse.io/fixture/jobs/1','content':'Requirements','location':{'name':'Israel'}}]})
        comeet=Path('tests/fixtures/comeet-bootstrap.html').read_text()
        generic=Path('tests/fixtures/comeet.html').read_text()
        for kind,document in [('Greenhouse',board),('Comeet',comeet),('Generic HTML',generic)]:
            client=MagicMock(); client.hosts={'job-boards.greenhouse.io','www.comeet.com'}
            client.get.side_effect=[document,SourceError('error','timeout')]
            with patch('collector.sources.needs_detail',return_value=True):
                with self.assertRaises(SourceError) as caught:
                    collect({**company,'ats_hint':kind},client)
            self.assertTrue(caught.exception.retryable,kind)
            self.assertGreater(len(caught.exception.partial_jobs),0,kind)
            self.assertEqual(caught.exception.partial_jobs[0]['status'],'unverified')

    def test_readable_mismatched_detail_pages_are_explicit_partial_failures(self):
        from collector.sources import collect
        company={'name':'Fixture','ats_hint':'Greenhouse','ats_identifier':'fixture','career_url':'https://job-boards.greenhouse.io/fixture'}
        board=json.dumps({'jobs':[{'id':1,'title':'Engineer','absolute_url':'https://job-boards.greenhouse.io/fixture/jobs/1','content':'Requirements','location':{'name':'Israel'}}]})
        comeet=Path('tests/fixtures/comeet-bootstrap.html').read_text()
        generic=Path('tests/fixtures/comeet.html').read_text()
        for kind,document in [('Greenhouse',board),('Comeet',comeet),('Generic HTML',generic)]:
            client=MagicMock(); client.hosts={'job-boards.greenhouse.io','www.comeet.com'}
            client.get.side_effect=[document,'<html>This job is no longer available</html>']
            with patch('collector.sources.needs_detail',return_value=True):
                with self.assertRaises(SourceError) as caught:
                    collect({**company,'ats_hint':kind},client)
            self.assertFalse(caught.exception.retryable,kind)
            self.assertGreater(len(caught.exception.partial_jobs),0,kind)
            self.assertEqual(caught.exception.partial_jobs[0]['status'],'unverified')

    def test_unsafe_later_record_preserves_only_previously_validated_jobs(self):
        from collector.sources import collect
        company={'name':'Fixture','ats_hint':'Greenhouse','ats_identifier':'fixture'}
        item={'id':1,'title':'Engineer','absolute_url':'https://job-boards.greenhouse.io/fixture/jobs/1','content':'Requirements','location':{'name':'Israel'}}
        client=MagicMock();client.hosts={'job-boards.greenhouse.io'}
        client.get.return_value=json.dumps({'jobs':[item,{**item,'id':2,'absolute_url':'https://127.0.0.1/private'}]})
        with patch('collector.sources.needs_detail',return_value=False):
            with self.assertRaises(SourceError) as caught: collect(company,client)
        self.assertEqual(len(caught.exception.partial_jobs),1)
        self.assertEqual(caught.exception.partial_jobs[0]['source_id'],'1')
        self.assertFalse(caught.exception.retryable)

    def test_malformed_nested_greenhouse_record_retains_valid_prefix(self):
        from collector.sources import collect
        item={'id':1,'title':'Engineer','absolute_url':'https://job-boards.greenhouse.io/f/jobs/1','content':'Requirements','location':{'name':'Israel'}}
        client=MagicMock(); client.hosts={'job-boards.greenhouse.io'}
        client.get.return_value=json.dumps({'jobs':[item,{**item,'id':2,'location':None}]})
        with patch('collector.sources.needs_detail',return_value=False):
            with self.assertRaises(SourceError) as caught:
                collect({'ats_hint':'Greenhouse','ats_identifier':'f'},client)
        self.assertEqual(len(caught.exception.partial_jobs),1)
        self.assertFalse(caught.exception.retryable)

    def test_spectrum_retains_successes_when_later_page_fails(self):
        from collector.sources import collect
        client=MagicMock();client.hosts={'spectrum-dynamics.com'}
        client.get.side_effect=['<a href="/jobs/a/">a</a><a href="/jobs/b/">b</a>','valid',SourceError('blocked','restricted')]
        with patch('collector.sources.spectrum_job',return_value={'source_id':'a','status':'open'}):
            with self.assertRaises(SourceError) as caught:
                collect({'name':'Spectrum','ats_hint':'Generic HTML','career_url':'https://spectrum-dynamics.com/careers/'},client)
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(len(caught.exception.partial_jobs),1)

    def test_existing_sqlite_gets_additive_scan_columns_without_data_loss(self):
        path=Path(self.temp.name)/'old.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE scans(id INTEGER PRIMARY KEY,company_id TEXT,started_at TEXT,finished_at TEXT,status TEXT,fetched_count INTEGER,eligible_count INTEGER,new_count INTEGER,message TEXT)')
            db.execute("INSERT INTO scans(id,status) VALUES(1,'ok')")
        with connect(path) as db:
            self.assertEqual(db.execute('SELECT status FROM scans WHERE id=1').fetchone()[0],'ok')
            self.assertIn('scheduled_slot_id',{r[1] for r in db.execute('PRAGMA table_info(scans)')})


if __name__ == '__main__': unittest.main()
