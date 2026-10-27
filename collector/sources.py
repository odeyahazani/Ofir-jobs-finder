"""Read-only public sources. No CAPTCHA bypasses, credentials or arbitrary URL fetching."""
from html import unescape
from html.parser import HTMLParser
import json
import re
import socket
import ipaddress
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urljoin, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser
from .scoring import assess
from .store import ROOT

USER_AGENT = "OfirJobsFinder/0.1 (+personal noncommercial job search)"
MAX_BYTES = 5_000_000
ATS_HOSTS = {"boards-api.greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io", "www.comeet.com", "www.comeet.co"}
COMPANY_HOSTS = {"Augury": {"www.augury.com"}}
TRUSTED_SOURCE_HOSTS = ATS_HOSTS | {"www.augury.com"} | {urlsplit(c["career_url"]).hostname for c in json.loads((ROOT / "data/companies.json").read_text()) if c["career_url"]}


class SourceError(Exception):
    def __init__(self, status, message, partial_jobs=None, *, retryable=None, retry_after=None):
        self.status, self.message = status, message
        self.partial_jobs = partial_jobs or []
        self.retryable = status == "error" if retryable is None else retryable
        self.retry_after = retry_after
        super().__init__(message)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.links, self.text = [], [], []
        self.capture = False
        self.script = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.capture = attrs.get("type") == "application/ld+json"
            self.script = []
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"p", "div", "li", "br", "h1", "h2", "h3"}:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self.capture:
            self.scripts.append("".join(self.script))
            self.capture = False
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li"}:
            self.text.append("\n")

    def handle_data(self, data):
        if self.capture:
            self.script.append(data)
        if not self.hidden:
            self.text.append(data)


def plain(value):
    parser = PageParser()
    value = value or ""
    parser.feed(unescape(value) if "<" not in value else value)
    return re.sub(r"[ \t]+", " ", "".join(parser.text)).strip()


def postings(document):
    parser = PageParser()
    parser.feed(document)
    found = []

    def walk(value):
        if isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, dict):
            kind = value.get("@type", "")
            if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
                found.append(value)
            else:
                for child in value.values():
                    if isinstance(child, (list, dict)):
                        walk(child)
    for script in parser.scripts:
        try:
            walk(json.loads(script))
        except (ValueError, TypeError):
            continue
    return found, parser.links


class SafeRedirect(HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url, hosts):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in hosts or parts.port not in (None, 443) or parts.username or parts.password:
        raise SourceError("unsupported", "Redirect or URL outside the explicitly supported HTTPS source hosts")
    if not parts.hostname or not re.fullmatch(r"(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}", parts.hostname) or re.search(r"\.(local|localhost|internal|invalid|test)$", parts.hostname):
        raise SourceError("unsupported", "Only public source hostnames are supported")


class Client:
    def __init__(self, company):
        self.hosts = ATS_HOSTS | {urlsplit(company["career_url"]).hostname} | COMPANY_HOSTS.get(company["name"], set())
        self.opener = build_opener(SafeRedirect(self.hosts))
        self.robots = {}
        self.last_request = 0

    def raw(self, url):
        check_url(url, self.hosts)
        try:
            addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
        except OSError:
            # Some managed environments expose DNS only through their HTTPS egress proxy.
            # Reuse that supported route only for the reviewed seed/ATS hosts, never arbitrary imports.
            if (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")) and urlsplit(url).hostname in TRUSTED_SOURCE_HOSTS:
                addresses = None
            else:
                raise SourceError("error", "Source hostname could not be resolved") from None
        if addresses is not None and (not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses)):
            raise SourceError("blocked", "Source hostname resolves to a non-public address")
        time.sleep(max(0, .3 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        try:
            with self.opener.open(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html"}), timeout=25) as response:
                self.last_url = response.geturl()
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise SourceError("unsupported", "Response exceeds safe size limit")
                return data.decode("utf-8", errors="replace")
        except HTTPError as error:
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone
            delay = None
            value = error.headers.get("Retry-After", "") if error.headers else ""
            try:
                delay = int(value) if value.isdigit() else max(0, int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()))
            except (ValueError, TypeError, OverflowError):
                pass
            raise SourceError("blocked" if error.code in {401, 403, 429, 491} else "error", f"HTTP {error.code}",
                              retryable=error.code in {408, 429} or 500 <= error.code < 600, retry_after=delay) from None
        except (URLError, TimeoutError, OSError) as error:
            # Proxy errors can contain URLs. Persist only the error category, never credentials.
            status = "blocked" if "403" in str(error) else "error"
            raise SourceError(status, f"Network request failed ({type(error).__name__})") from None

    def get(self, url, api=False):
        check_url(url, self.hosts)
        # Greenhouse's documented public read API is expressly designed for this operation.
        if not api:
            parts = urlsplit(url)
            origin = f"https://{parts.netloc}"
            if origin not in self.robots:
                robot = RobotFileParser()
                try:
                    robot.parse(self.raw(origin + "/robots.txt").splitlines())
                except SourceError as error:
                    if error.message == "HTTP 404":
                        robot.parse([])
                    else:
                        raise
                self.robots[origin] = robot
            if not self.robots[origin].can_fetch(USER_AGENT, url):
                raise SourceError("blocked", "Source robots.txt disallows this path")
        return self.raw(url)


def normalize_posting(item, fallback_url):
    location = item.get("jobLocation", [])
    if isinstance(location, dict):
        location = [location]
    names = []
    for place in location:
        if not isinstance(place, dict):
            continue
        address = place.get("address", {})
        if isinstance(address, dict):
            country = address.get("addressCountry", "")
            if isinstance(country, dict):
                country = country.get("name", "")
            names.append(", ".join(str(x) for x in [address.get("addressLocality"), address.get("addressRegion"), country] if x))
    identifier = item.get("identifier", {})
    if isinstance(identifier, dict):
        identifier = identifier.get("value")
    url = item.get("url") or fallback_url
    return {"source_id": str(identifier or url), "title": plain(item.get("title", "")),
            "location": " / ".join(names) or "לא צוין", "url": url,
            "description": plain(item.get("description", "")),
            "published_at": item.get("datePosted"), "updated_at": item.get("dateModified"),
            "status": "open", "work_model": "מרחוק" if item.get("jobLocationType") == "TELECOMMUTE" else "לא צוין"}


def embedded_json(document, name):
    """Read JSON from a named public bootstrap variable, without executing JavaScript."""
    match = re.search(r"\b" + re.escape(name) + r"\s*=\s*", document)
    if not match:
        return None
    try:
        return json.JSONDecoder().raw_decode(document[match.end():])[0]
    except ValueError:
        raise SourceError("unsupported", "Public source data is not valid JSON") from None


def comeet_job(item):
    fields = item.get("custom_fields", {}).get("details", [])
    description = "\n".join(plain(field.get("name", "")) + "\n" + plain(field.get("value", "")) for field in fields)
    location = item.get("location") or {}
    return {"source_id": item["uid"], "title": item["name"],
            "location": location.get("name") or "לא צוין", "url": item["url_comeet_hosted_page"],
            "description": description, "published_at": None, "updated_at": item.get("time_updated"),
            "status": "unverified", "work_model": str(item.get("workplace_type") or "לא צוין")}


def spectrum_job(document, url):
    title = re.search(r"<h1\b[^>]*>(.*?)</h1>", document, re.S | re.I)
    end = re.search(r"<h2\b[^>]*>\s*Share this position", document, re.I)
    if not title or not end or end.start() <= title.end():
        raise SourceError("unsupported", "Spectrum detail layout changed; could not isolate job content")
    content = document[title.end():end.start()]
    location = re.search(r"<h3\b[^>]*>(.*?)</h3>", content, re.S | re.I)
    # The explicit 'Based in' statement is authoritative; never infer from company HQ.
    based = re.search(r"Based in ([^\n]{2,100})", plain(content), re.I)
    place = based.group(1).strip() if based else plain(location.group(1)) if location else "לא צוין"
    # Official detail pages link an application form or contain instructions for submitting an application.
    application_present = bool(re.search(r"mailto:|submit job applications|Send CV", document, re.I))
    if not application_present:
        raise SourceError("unsupported", "Could not verify Spectrum application instructions")
    return {"source_id": urlsplit(url).path, "title": plain(title.group(1)), "description": plain(content),
            "location": place, "url": url, "published_at": None, "updated_at": None, "status": "open"}


def needs_detail(title, description, location, company):
    return assess(title, description, location, {"notes": company.get("notes", "")})["eligible"]


def collect(company, client=None):
    client = client or Client(company)
    if company.get("name") == "Camtek":
        from .camtek import collect_camtek
        return collect_camtek(company, client)
    if company["ats_hint"] == "Greenhouse" and company["ats_identifier"]:
        board = quote(company["ats_identifier"], safe="")
        try:
            data = json.loads(client.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true", api=True))
        except ValueError:
            raise SourceError("error", "Greenhouse returned invalid JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise SourceError("error", "Unexpected Greenhouse response; not treated as an empty board")
        jobs = []
        for item in data["jobs"]:
            if not all(key in item for key in ("id", "title", "absolute_url", "content", "location")):
                raise SourceError("unsupported", "Incomplete Greenhouse job record")
            url = item["absolute_url"]
            check_url(url, client.hosts)
            # The official board's full record verifies listing presence. The application page must also load.
            status = "unverified"
            if needs_detail(item["title"], plain(item["content"]), item["location"].get("name") or "", company):
                try:
                    page = client.get(url)
                    if item["title"].casefold() in plain(page).casefold():
                        status = "open"
                except SourceError:
                    pass
            jobs.append({"source_id": str(item["id"]), "title": item["title"], "location": item["location"].get("name") or "לא צוין", "url": url,
                         "description": plain(item["content"]), "published_at": item.get("first_published"),
                         "updated_at": item.get("updated_at"), "status": status})
        return jobs

    # Comeet and custom company pages: use public JobPosting structured data and exact job links.
    # Do not guess API tokens, claim empty results from a JS shell, or bypass blocked pages.
    url = company["career_url"]
    document = client.get(url)
    if company["ats_hint"] == "Comeet":
        items = embedded_json(document, "COMPANY_POSITIONS_DATA")
        if isinstance(items, list):
            jobs = []
            for item in items:
                if not isinstance(item, dict) or not all(item.get(key) for key in ["uid", "name", "url_comeet_hosted_page", "custom_fields"]):
                    raise SourceError("unsupported", "Incomplete Comeet record; source layout may have changed")
                if item.get("is_internal"):
                    continue
                job = comeet_job(item)
                check_url(job["url"], client.hosts)
                if not job["description"]:
                    raise SourceError("unsupported", "Comeet job lacks description")
                if needs_detail(job["title"], job["description"], job["location"], company):
                    try:
                        detail = embedded_json(client.get(job["url"]), "POSITION_DATA")
                        if isinstance(detail, dict) and detail.get("uid") == job["source_id"] and detail.get("name") == job["title"]:
                            job["status"] = "open"
                    except SourceError:
                        pass
                jobs.append(job)
            return jobs

    if urlsplit(url).hostname == "spectrum-dynamics.com":
        _, links = postings(document)
        job_urls = sorted({urljoin(url, link) for link in links if urlsplit(urljoin(url, link)).hostname == "spectrum-dynamics.com" and re.fullmatch(r"/jobs/[^/]+/", urlsplit(urljoin(url, link)).path)})
        if not job_urls or len(job_urls) > 100:
            raise SourceError("unsupported", "Spectrum job links missing or source layout changed")
        return [spectrum_job(client.get(detail), detail) for detail in job_urls]

    structured, links = postings(document)
    jobs = [normalize_posting(item, url) for item in structured]
    if not structured and company["ats_hint"] == "Comeet":
        base_path = urlsplit(url).path.rstrip("/")
        detail_urls = sorted({urljoin(url, link).split("#")[0] for link in links if urlsplit(urljoin(url, link)).path.startswith(base_path + "/")})
        if len(detail_urls) > 100:
            raise SourceError("unsupported", "Too many candidate detail pages; source requires a dedicated adapter")
        for detail in detail_urls:
            check_url(detail, client.hosts)
            items, _ = postings(client.get(detail))
            jobs.extend(normalize_posting(item, detail) for item in items)
    if not jobs:
        raise SourceError("unsupported", "Page readable, but no complete JobPosting records extracted; not evidence of zero jobs")
    for job in jobs:
        check_url(job["url"], client.hosts)
        if not job["title"] or not job["description"] or job["url"].rstrip("/") == url.rstrip("/"):
            raise SourceError("unsupported", "Missing specific job URL or description")
        # Verify that the individual posting is still exposed on its application page.
        try:
            detail_items, _ = postings(client.get(job["url"]))
            job["status"] = "open" if any(plain(x.get("title", "")).casefold() == job["title"].casefold() for x in detail_items) else "unverified"
        except SourceError:
            job["status"] = "unverified"
    return jobs
