"""Reviewed Camtek public HTML adapter; no guessed APIs or company-address locations."""
import re
from urllib.parse import urljoin, urlsplit
from .sources import SourceError, plain, postings

BOARD = 'https://www.camtek.com/careers/open-positions/'


def job_url(url):
    parts = urlsplit(url)
    return (parts.scheme == 'https' and parts.netloc == 'www.camtek.com' and not parts.query and not parts.fragment
            and re.fullmatch(r'/careers/open-positions/[A-Za-z0-9.-]+/', parts.path))


def parse_job(document, url):
    if not job_url(url):
        raise SourceError('unsupported', 'Not a reviewed Camtek job URL')
    document = re.sub(r'(</?(?:h[1-6]|a|button)\b[^>]*>)', r'\n\1\n', document)
    lines = [line.strip().lstrip('\ufeff') for line in plain(document).splitlines() if line.strip().lstrip('\ufeff')]
    try:
        start = lines.index('Back to Careers') + 1
        description = lines.index('Description', start)
        requirements = lines.index('Requirements', description + 1)
        end = lines.index('Apply Now', requirements + 1)
    except ValueError:
        raise SourceError('unsupported', 'Camtek detail markers changed; not treating the page as a verified job') from None
    metadata = lines[start:description]
    # Reviewed pages have title / department / actual location, optionally a work model.
    work_pattern = r'Full[ -]time|Part[ -]time'
    valid = (len(metadata) == 4 and re.fullmatch(work_pattern, metadata[3], re.I)) or (len(metadata) == 3 and not re.fullmatch(work_pattern, metadata[2], re.I))
    if not valid or len(metadata[0]) > 250:
        raise SourceError('unsupported', 'Camtek job metadata changed; location cannot be inferred')
    body = '\n'.join(lines[description:end])
    if requirements <= description + 1 or end <= requirements + 1 or len(body) < 150:
        raise SourceError('unsupported', 'Camtek job description or requirements missing')
    return {'source_id': urlsplit(url).path.strip('/').split('/')[-1], 'title': metadata[0],
            'location': metadata[2], 'work_model': metadata[3] if len(metadata) == 4 else 'לא צוין', 'url': url, 'description': body,
            'published_at': None, 'updated_at': None, 'status': 'open'}


def collect_camtek(company, client):
    if company['career_url'].rstrip('/') != BOARD.rstrip('/'):
        raise SourceError('unsupported', 'Camtek career URL does not match the reviewed listing')
    document = client.get(company['career_url'])
    _, links = postings(document)
    urls = sorted({urljoin(BOARD, link) for link in links if job_url(urljoin(BOARD, link))})
    if not urls or len(urls) > 100:
        raise SourceError('unsupported', 'Camtek listing links missing or exceed the reviewed scan budget')
    # Fail the source on a failed detail: an incomplete scan must not claim zero jobs.
    return [parse_job(client.get(url), url) for url in urls]
