"""Bounded read-only review of official career pages before writing new adapters."""
import json
import re
from urllib.parse import urlsplit
from .sources import Client, SourceError, postings

PRIORITIES = ('CardiacSense', 'ColorChip', 'Rapid Medical', 'Camtek', 'Prisma Photonics')


def ats_references(document):
    # Report public board paths only: never echo query strings, tokens or embedded credentials.
    references = set()
    for value in re.findall(r'https://[^\s<>"\x27]+', document.replace('\\/', '/')):
        parts = urlsplit(value)
        if parts.username or parts.password: continue
        if parts.hostname in {'www.comeet.com', 'www.comeet.co'}:
            match = re.match(r'/jobs/([a-zA-Z0-9_-]+)/([a-zA-Z0-9.]+)(?:/|$)', parts.path)
        elif parts.hostname in {'boards.greenhouse.io', 'job-boards.greenhouse.io', 'job-boards.eu.greenhouse.io'}:
            match = re.match(r'/([a-zA-Z0-9_-]+)(?:/|$)', parts.path)
        else: continue
        if match: references.add('https://' + parts.hostname + match.group(0).rstrip('/'))
    return sorted(references)


def report(db, client_factory=Client):
    print('READ-ONLY OFFICIAL CAREER PAGE PROBE (up to five selected companies)')
    for name in PRIORITIES:
        company = db.execute('SELECT * FROM companies WHERE name=?', (name,)).fetchone()
        if company is None:
            print(json.dumps({'company': name, 'status': 'not_in_database'})); continue
        company = dict(company)
        if not company['career_url']:
            print(json.dumps({'company': name, 'status': 'missing_career_url'})); continue
        try:
            document = client_factory(company).get(company['career_url'])
            records, _ = postings(document)
            result = {'company': name, 'status': 'page_readable', 'jobposting_records_on_page': len(records), 'linked_public_boards': ats_references(document)}
        except SourceError as error:
            result = {'company': name, 'status': error.status, 'error': error.message}
        print(json.dumps(result, ensure_ascii=False))
    print('A readable page or board link is not a completed job scan. No monitoring changes, cloud writes or notifications performed.')
