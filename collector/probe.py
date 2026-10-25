"""Bounded read-only review of official career pages before writing new adapters."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urljoin, parse_qsl
from .sources import Client, SourceError, postings
from .sources import plain

PRIORITIES = ('CardiacSense', 'ColorChip', 'Rapid Medical', 'Camtek', 'Prisma Photonics')


def html_document(document):
    # Some official site builders respond to Accept: application/json with page data.
    if document.lstrip().startswith('{'):
        try:
            payload = json.loads(document)
        except ValueError:
            raise SourceError('unsupported', 'Career page JSON is invalid') from None
        if not isinstance(payload, dict) or not isinstance(payload.get('content'), str):
            raise SourceError('unsupported', 'Career page JSON has no supported HTML content field')
        return payload['content']
    return document


def detail_candidates(document, base_url):
    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.current = None
            self.links = []
        def handle_starttag(self, tag, attrs):
            if tag == 'a': self.current = [dict(attrs).get('href', ''), []]
        def handle_data(self, value):
            if self.current is not None: self.current[1].append(value)
        def handle_endtag(self, tag):
            if tag == 'a' and self.current is not None:
                self.links.append((self.current[0], ' '.join(self.current[1])))
                self.current = None
    parser = Links()
    parser.feed(document)
    paths = {'www.camtek.com': r'/careers/open-positions/[A-Za-z0-9.-]+/',
             'www.prismaphotonics.com': r'/job/[a-z0-9-]+/'}
    host = urlsplit(base_url).hostname
    if host not in paths: return []
    candidates = {}
    for href, label in parser.links:
        url = urlsplit(urljoin(base_url, href))
        if url.scheme != 'https' or url.hostname != host or url.username or url.password or url.port not in (None, 443) or url.query:
            continue
        if re.fullmatch(paths[host], url.path):
            priority = 0 if re.search('integrat|validat|system|test|אינטגר|בדיק', label, re.I) else 1
            candidates['https://' + host + url.path] = (priority, label.strip()[:300])
    return sorted(candidates, key=lambda url: (candidates[url][0], url))[:3]


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


def page_evidence(document, base_url):
    class EvidenceParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.resources = []
            self.markers = set()

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            for key in ('href', 'src'):
                value = attrs.get(key)
                if not value: continue
                parts = urlsplit(urljoin(base_url, value))
                if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password: continue
                self.resources.append({'tag': tag, 'url': 'https://' + parts.netloc + parts.path,
                                       'query_keys': sorted({key for key, _ in parse_qsl(parts.query)})})
            for key in ('id', 'class'):
                value = attrs.get(key, '')
                if re.search(r'job|career|position|comeet|greenhouse|workable|iframe', value, re.I):
                    self.markers.add(value[:200])

    parser = EvidenceParser()
    parser.feed(document)
    return {'text': plain(document)[:120_000], 'text_limit': 120_000,
            'resources': parser.resources[:400], 'resource_limit': 400,
            'layout_markers': sorted(parser.markers)[:100]}


def report(db, client_factory=Client, output=None):
    print('READ-ONLY OFFICIAL CAREER PAGE PROBE (up to five selected companies)')
    evidence = []
    for name in PRIORITIES:
        company = db.execute('SELECT * FROM companies WHERE name=?', (name,)).fetchone()
        if company is None:
            print(json.dumps({'company': name, 'status': 'not_in_database'})); continue
        company = dict(company)
        if not company['career_url']:
            print(json.dumps({'company': name, 'status': 'missing_career_url'})); continue
        try:
            client = client_factory(company)
            document = html_document(client.get(company['career_url']))
            records, _ = postings(document)
            result = {'company': name, 'status': 'page_readable', 'jobposting_records_on_page': len(records), 'linked_public_boards': ats_references(document)}
            details = []
            for url in detail_candidates(document, company['career_url']):
                try:
                    detail = html_document(client.get(url))
                    details.append({'url': url, 'status': 'page_readable', **page_evidence(detail, url)})
                except SourceError as error:
                    details.append({'url': url, 'status': error.status, 'error': error.message})
            result['detail_pages_read'] = sum(d['status'] == 'page_readable' for d in details)
            evidence.append({**result, 'career_url': company['career_url'], **page_evidence(document, company['career_url']), 'detail_pages': details})
        except SourceError as error:
            result = {'company': name, 'status': error.status, 'error': error.message}
            evidence.append(result)
        print(json.dumps(result, ensure_ascii=False))
    print('A readable page or board link is not a completed job scan. No monitoring changes, cloud writes or notifications performed.')
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Public career-page text and sanitized resource links saved for adapter review.')
