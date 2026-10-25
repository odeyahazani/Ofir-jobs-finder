"""Read-only diagnostics: separate collection coverage from recommendation gates."""
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
from .growth import new_sources


def report(db):
    companies = [dict(row) for row in db.execute("SELECT * FROM companies")]
    jobs = [dict(row) for row in db.execute("SELECT j.*,c.name AS company FROM jobs j JOIN companies c ON c.id=j.company_id")]
    active = [c for c in companies if c['enabled']]
    print('COMPANY COVERAGE (snapshot being audited)')
    print(f'Total: {len(companies)}; monitoring enabled: {len(active)}; ever checked: {sum(bool(c["last_checked"]) for c in companies)}')
    print(f'Disabled and never checked: {sum(not c["enabled"] and not c["last_checked"] for c in companies)}')
    print('Active source states:', json.dumps(dict(Counter(c['source_status'] for c in active)), ensure_ascii=False))
    print('Source types:', json.dumps(dict(Counter(c['ats_hint'] for c in companies)), ensure_ascii=False))
    ids = new_sources(db, 5)
    print('Next supported, relevant, unpaused onboarding candidates (up to 5):')
    for c in companies:
        if c['id'] in ids: print(f'  {c["name"]} | {c["ats_hint"]} | {c["career_url"]}')
    print('Scheduled onboarding adds at most one company per run; it does not cover all source types.')
    # This is deliberately labeled as the collector rule, not the UI's separate location classifier.
    israel = [j for j in jobs if json.loads(j['breakdown']).get('location', 0) > 0]
    eligible = [j for j in israel if j['eligible']]
    scored = [j for j in eligible if j['score'] >= 70]
    now = datetime.now(timezone.utc)
    def fresh(j):
        try:
            age = now - datetime.fromisoformat(j['last_verified_at'].replace('Z', '+00:00'))
            return j['status'] == 'open' and timedelta(0) <= age < timedelta(hours=30)
        except (ValueError, TypeError, AttributeError): return False
    verified = [j for j in scored if fresh(j)]
    actionable = [j for j in verified if j['fit'] != 'no' and j['application_status'] == 'not_applied']
    print('\nRECOMMENDATION FUNNEL (collector location rule; UI location classification is independent)')
    print(f'Raw jobs: {len(jobs)} -> Israeli location rule: {len(israel)} -> eligible: {len(eligible)} -> score >=70: {len(scored)} -> open and verified <30h: {len(verified)} -> not applied/not rejected by user: {len(actionable)}')
    print('Stored primary exclusions in Israeli records:', json.dumps(dict(Counter(j['exclusion_reason'] or 'eligible' for j in israel)), ensure_ascii=False))
    print('These are primary stored reasons, not every independently failing requirement.')
    print('\nHIGHEST SCORING ELIGIBLE ISRAELI RECORDS (review candidates, not recommendations)')
    for j in sorted(eligible, key=lambda j: (-j['score'], j['id']))[:10]:
        print(f'{j["score"]}/100 | {j["company"]} | {j["title"]} | {j["experience"]} | status={j["status"]} | verified={j["last_verified_at"]}')
        print(j['url'])
    print('\nNo source requests, scoring changes, cloud writes or notifications performed by this audit.')
