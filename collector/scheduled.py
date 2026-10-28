"""Durable scheduled collection. RPCs own time, claims, retries and fencing.

No production credentials or network calls are needed to import/test this module.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from zoneinfo import ZoneInfo

from . import cli
from .growth import new_sources
from .store import connect

ZONE = ZoneInfo('Asia/Jerusalem')
REPORT_PATH = Path('.local/scheduled-report.json')


def targets(current):
    """Civil targets for reporting/tests; the database independently enforces due work."""
    local = current.astimezone(ZONE)
    return [datetime.combine(local.date() - timedelta(days=days), datetime.min.time(), ZONE).replace(hour=hour, minute=17)
            for days in (1, 0) for hour in (8, 17)]


def due_targets(current):
    current = current.astimezone(timezone.utc)
    return [target for target in targets(current) if target.astimezone(timezone.utc) <= current < target.astimezone(timezone.utc) + timedelta(hours=24)]


def rpc(remote, name, body):
    """One replay of an idempotent RPC resolves lost acknowledgements, never recollects."""
    try:
        return remote.rpc(name, body)
    except RuntimeError:
        return remote.rpc(name, body)


def company_payload(db, company_id, before):
    changed = [dict(row) for row in db.execute('SELECT * FROM jobs WHERE company_id=?', (company_id,))
               if dict(row) != before.get(row['id'])]
    ids = {row['id'] for row in changed}
    events = [dict(row) for row in db.execute('SELECT * FROM job_events') if row['job_id'] in ids]
    return {'companies': [dict(db.execute('SELECT * FROM companies WHERE id=?', (company_id,)).fetchone())],
            'jobs': changed, 'job_events': events}


def write_report(report):
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(REPORT_PATH)
    print(json.dumps(report, ensure_ascii=False))


def render_summary(path=REPORT_PATH):
    """Called by an always() workflow step, including when the worker was cancelled."""
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        report = {'outcome': 'failed', 'reason': 'worker_did_not_report', 'persistence': 'unconfirmed'}
    labels = {'completed': 'הושלם', 'retry_wait': 'הצלחה חלקית — ממתין לניסיון חוזר',
              'failed': 'נכשל', 'skipped': 'דולג', 'running': 'הופסק לפני דיווח סופי'}
    text = '### איסוף משרות מתוזמן\n\n'
    text += labels.get(report.get('outcome'), 'לא ידוע') + '\n\n'
    text += 'הצלחת הפעלת התהליך אינה אישור להשלמת האיסוף. מצב האיסוף וההתמדה מפורטים בנפרד.\n\n'
    # JSON escaping prevents source names/messages from injecting Markdown/HTML into the summary.
    text += '```json\n' + json.dumps(report, ensure_ascii=True, indent=2) + '\n```\n'
    destination = os.environ.get('GITHUB_STEP_SUMMARY')
    if destination:
        with open(destination, 'a') as output:
            output.write(text)
    else:
        print(text)


def public_slot(slot):
    return {key: value for key, value in slot.items() if key not in {'attempt_token', 'lease_until', 'company_ids'}}


def run(remote_factory):
    from .cloud import restore
    started = datetime.now(timezone.utc)
    token = uuid.uuid4().hex
    report = {'outcome': 'running', 'actual_execution': started.isoformat(),
              'workflow_run_id': os.environ.get('GITHUB_RUN_ID'), 'commit_sha': os.environ.get('GITHUB_SHA'),
              'persistence': 'not_attempted', 'invocation_attempted': 0, 'invocation_checked': 0,
              'invocation_jobs_inserted': 0, 'invocation_jobs_updated': 0, 'slot': None}
    write_report(report)
    remote, slot = None, None
    try:
        report['stage'] = 'claim'
        remote = remote_factory()
        claim = rpc(remote, 'ofir_claim_scheduled', {'worker_token': token,
                    'workflow_run': report['workflow_run_id'], 'sha': report['commit_sha']})
        report['expired_slots'] = claim.get('expired_slots', [])
        if claim['outcome'] == 'skipped':
            report.update(outcome='skipped', reason=claim['reason'],
                          slot=public_slot(claim['slot']) if claim.get('slot') else None)
            # Expired missed work is a failure even if this invocation has nothing to collect.
            return 1 if report['expired_slots'] else 0
        slot = claim['slot']
        report['slot'] = public_slot(slot)
        report['execution_delay_seconds'] = max(0, (started - datetime.fromisoformat(slot['target_at'])).total_seconds())
        write_report(report)
        report['stage'] = 'schema_check'
        remote.ensure_matching_schema()
        with tempfile.TemporaryDirectory(prefix='ofir-scheduled-') as folder:
            with connect(Path(folder) / 'worker.sqlite') as db:
                report['stage'] = 'restore'
                restore(db, remote)
                report['stage'] = 'prepare'
                slot = rpc(remote, 'ofir_prepare_scheduled', {'slot_id': slot['id'], 'worker_token': token,
                           'expansion_ids': new_sources(db, 1) if slot['company_ids'] is None else []})
                budget = time.monotonic() + 15 * 60
                for item in slot['companies']:
                    if time.monotonic() >= budget:
                        report['reason'] = 'invocation_budget_reached'
                        break
                    if item['state'] != 'ready':
                        continue
                    company_id = item['company_id']
                    report['stage'] = 'begin_company'
                    attempt = rpc(remote, 'ofir_begin_scheduled_company', {'slot_id': slot['id'], 'worker_token': token, 'company': company_id})
                    if attempt['status'] != 'running':
                        continue
                    # Prepare may have enabled one reviewed source after the snapshot was restored.
                    with db:
                        db.execute('UPDATE companies SET enabled=1 WHERE id=?', (company_id,))
                    before = {row['id']: dict(row) for row in db.execute('SELECT * FROM jobs WHERE company_id=?', (company_id,))}
                    report['pending_scan_id'] = attempt.get('id')
                    report['pending_company_id'] = company_id
                    report['invocation_attempted'] += 1
                    write_report(report)

                    def checkpoint(result, retryable, retry_after):
                        body = {'slot_id': slot['id'], 'worker_token': token, 'company': company_id,
                                'result': {**result, 'retryable': retryable, 'retry_after_seconds': min(86400, max(0, retry_after or 0))},
                                'payload': company_payload(db, company_id, before)}
                        # Write before requesting: cancellation/response loss must not imply persistence failed.
                        report['stage'] = 'checkpoint'
                        report['persistence'] = 'unconfirmed'
                        write_report(report)
                        receipt = rpc(remote, 'ofir_checkpoint_scheduled', body)
                        report['persistence'] = receipt['persistence']
                        report.pop('pending_scan_id', None)
                        report.pop('pending_company_id', None)
                        report['invocation_jobs_inserted'] += receipt['inserted']
                        report['invocation_jobs_updated'] += receipt['updated']
                        report['invocation_checked'] += result['status'] in {'ok', 'empty'}
                        report['slot'] = public_slot(rpc(remote, 'ofir_scheduled_report', {'slot_id': slot['id']}))
                        write_report(report)

                    report['stage'] = 'collect'
                    cli.scan(db, company_ids=[company_id], checkpoint=checkpoint)
                report['stage'] = 'finish'
                slot = rpc(remote, 'ofir_finish_scheduled', {'slot_id': slot['id'], 'worker_token': token})
                report.update(outcome=slot['state'], slot=public_slot(slot))
                return 0 if slot['state'] == 'completed' and not report['expired_slots'] else 1
    except Exception as error:
        # Never log exception text from arbitrary HTTP/SQL libraries (may contain credentials).
        report.update(outcome='failed', reason='scheduled_operation_failed', error_type=type(error).__name__)
        if remote is not None and slot is not None:
            try:
                report['slot'] = public_slot(rpc(remote, 'ofir_scheduled_report', {'slot_id': slot['id']}))
                # A fresh database read can resolve two lost checkpoint responses without a third write.
                for item in report['slot'].get('companies', []):
                    if item.get('last_scan_id') == report.get('pending_scan_id') and item.get('checkpoint_confirmed'):
                        report['persistence'] = 'confirmed'
                        for counter in ('invocation_checked','invocation_jobs_inserted','invocation_jobs_updated'):
                            report[counter] = None
                        report['invocation_counts_status'] = 'unknown_after_response_loss; use confirmed slot totals'
                        report['reason'] = 'checkpoint_confirmed_after_response_loss'
            except Exception:
                pass
        return 1
    finally:
        report['finished_execution'] = datetime.now(timezone.utc).isoformat()
        write_report(report)


if __name__ == '__main__':
    render_summary()
