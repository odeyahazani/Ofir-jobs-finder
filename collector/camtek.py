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
    lines = [line.replace('\ufeff', '').strip() for line in plain(document).splitlines() if line.replace('\ufeff', '').strip()]
    labels = [re.sub(r'\s+', ' ', line).casefold().rstrip(':').strip() for line in lines]
    try:
        start = labels.index('back to careers') + 1
        description = labels.index('description', start)
        end = labels.index('apply now', description + 1)
    except ValueError:
        missing = [label for label in ('back to careers', 'description', 'apply now') if label not in labels]
        raise SourceError('unsupported', 'Camtek detail markers missing or out of order: ' + ', '.join(missing or ['marker order'])) from None
    requirements = next((index for index in range(description + 1, end) if labels[index] == 'requirements'), None)
    metadata = lines[start:description]
    # Reviewed pages have title / department / actual location, optionally a work model.
    work_pattern = r'Full[ -]time|Part[ -]time'
    valid = (len(metadata) == 4 and re.fullmatch(work_pattern, metadata[3], re.I)) or (len(metadata) == 3 and not re.fullmatch(work_pattern, metadata[2], re.I))
    if not 1 <= len(metadata) <= 4 or not metadata[0] or len(metadata[0]) > 250:
        raise SourceError('unsupported', 'Camtek job title or metadata structure cannot be extracted')
    location = metadata[2] if valid else 'מיקום לא ידוע'
    work_model = metadata[-1] if len(metadata) > 1 and re.fullmatch(work_pattern, metadata[-1], re.I) else 'לא צוין'
    body = '\n'.join(lines[description:end])
    if len(body) < 150 or (requirements is not None and (requirements <= description + 1 or end <= requirements + 1)):
        raise SourceError('unsupported', 'Camtek job description or requirements missing')
    return {'source_id': urlsplit(url).path.strip('/').split('/')[-1], 'title': metadata[0],
            'location': location, 'work_model': work_model, 'url': url, 'description': body,
            'published_at': None, 'updated_at': None,
            'requirements_unconfirmed': requirements is None,
            'status': 'unverified' if requirements is None or not valid else 'open'}


def collect_camtek(company, client):
    if company['career_url'].rstrip('/') != BOARD.rstrip('/'):
        raise SourceError('unsupported', 'Camtek career URL does not match the reviewed listing')
    document = client.get(company['career_url'])
    _, links = postings(document)
    urls = sorted({urljoin(BOARD, link) for link in links if job_url(urljoin(BOARD, link))})
    if not urls or len(urls) > 100:
        raise SourceError('unsupported', 'Camtek listing links missing or exceed the reviewed scan budget')
    jobs, errors, failures = [], [], []
    for url in urls:
        try:
            jobs.append(parse_job(client.get(url), url))
        except SourceError as error:
            errors.append(url + ' (' + error.message + ')')
            failures.append(error)
    if errors:
        raise SourceError('unsupported', f'Partial Camtek scan: {len(jobs)} complete jobs; {len(errors)} detail pages failed. First failures: ' + '; '.join(errors[:3]), partial_jobs=jobs, retryable=all(e.retryable for e in failures), retry_after=max((e.retry_after or 0 for e in failures), default=0))
    return jobs
