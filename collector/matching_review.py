"""Compare profile-based matching without changing source verification, notifications or user feedback."""
from collections import Counter
import json
from pathlib import Path
from .matching import assess, exclude, VERSION
from .scoring import within_age_limit


def evaluate(db):
    records = []
    for row in db.execute('SELECT j.*, c.name AS company, c.notes AS company_notes FROM jobs j JOIN companies c ON c.id=j.company_id ORDER BY j.id'):
        job = dict(row)
        assessment = assess(job['title'], job['description'], job['location'], {'notes': job['company_notes']})
        if not within_age_limit(job['published_at']):
            exclude(assessment, "תאריך הפרסום מחוץ לחלון ששת החודשים")
        # Preserve prior extractor uncertainty even if the text itself happens to contain a similar heading.
        if 'דרישות המשרה לא חולצו' in (job['exclusion_reason'] or ''):
            exclude(assessment, job['exclusion_reason'], uncertain=True)
        records.append({'id': job['id'], 'company': job['company'], 'title': job['title'], 'url': job['url'], 'location': job['location'],
                        'before': {'score': job['score'], 'eligible': bool(job['eligible']), 'category': job.get('match_category') or 'unassessed'},
                        'after': assessment, 'source_status_unchanged': job['status'], 'last_verified_at_unchanged': job['last_verified_at']})
    return records


def preview(db, output=None):
    records = evaluate(db)
    print('READ-ONLY PROFILE MATCHING PREVIEW:', VERSION)
    print('All records by category:', json.dumps(dict(Counter(item['after']['match_category'] for item in records))))
    print('Israeli location rule:', json.dumps(dict(Counter(item['after']['match_category'] for item in records if item['after']['match_details']['location_in_israel']))))
    order = {'priority': 0, 'review': 1, 'gap': 2}
    for item in sorted(records, key=lambda item: (not item['after']['match_details']['location_in_israel'], order[item['after']['match_category']], -item['after']['score'], item['id']))[:20]:
        a = item['after']
        print(f'{item["before"]["category"]} -> {a["match_category"]} | {item["before"]["score"]} -> {a["score"]}/100 | {item["company"]} | {item["title"]} | source={item["source_status_unchanged"]}')
        print('  ', '; '.join(a['match_details']['blockers'] + a['match_details']['checks']) or 'No explicit requirement gap found; source availability remains independent')
    if output:
        path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'version': VERSION, 'records': records}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('No cloud writes, source requests, fresh verification claims, event changes or notifications performed.')
    return records


def rescore(db):
    records = evaluate(db)
    with db:
        for item in records:
            a = item['after']
            db.execute('UPDATE jobs SET score=?,breakdown=?,reasons=?,gaps=?,experience=?,eligible=?,exclusion_reason=?,match_category=?,match_version=?,match_details=? WHERE id=?',
                       (a['score'], json.dumps(a['breakdown'], ensure_ascii=False), json.dumps(a['reasons'], ensure_ascii=False), json.dumps(a['gaps'], ensure_ascii=False),
                        a['experience'], int(a['eligible']), a['exclusion_reason'], a['match_category'], a['match_version'], json.dumps(a['match_details'], ensure_ascii=False), item['id']))
    print(f'Rescored {len(records)} records with {VERSION}; source dates, feedback and events preserved.')
