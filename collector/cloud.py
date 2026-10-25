"""Stateless collector using Supabase as durable storage; no Python packages required."""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from . import cli
from .config import load_local_config
from .store import connect, seed, now, process_lock
from .growth import new_sources, scheduled_slot
from .discoveries import verify_pending

TABLES = ("companies", "company_monitor_controls", "imports", "jobs", "job_events", "job_discoveries", "digest_runs")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Remote:
    def __init__(self):
        self.url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
        self.key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        parts = urlsplit(self.url)
        if parts.scheme != "https" or not re.fullmatch(r"[a-z0-9]+\.supabase\.co", parts.hostname or "") or parts.path or parts.query or parts.fragment or parts.username or parts.password or parts.port:
            raise ValueError("Set the HTTPS Supabase project URL, without a path")
        if not self.key:
            raise ValueError("Set SUPABASE_SERVICE_ROLE_KEY securely for the collector; the web app does not need it")
        self.client = build_opener(NoRedirect())

    def request(self, route, body=None):
        headers = {"apikey": self.key, "Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        encoded = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        if encoded and len(encoded) > 10_000_000:
            raise RuntimeError("Cloud snapshot exceeds 10MB; split the source group before syncing")
        request = Request(self.url + "/rest/v1/" + route, data=encoded, headers=headers)
        try:
            with self.client.open(request, timeout=45) as response:
                data = response.read(20_000_001)
                if len(data) > 20_000_000:
                    raise RuntimeError("Cloud response too large; not treating it as a complete snapshot")
                return json.loads(data) if data else None
        except HTTPError as error:
            raise RuntimeError(f"Supabase HTTP {error.code}; check schema, worker permissions and settings") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise RuntimeError("Supabase request failed; no credential values have been logged") from None

    def rows(self, table):
        if table not in TABLES:
            raise ValueError("Unsupported snapshot table")
        key = "canonical_url" if table == "imports" else "company_id" if table == "company_monitor_controls" else "id"
        result = []
        offset = 0
        while offset < 100_000:
            page = self.request(table + "?" + urlencode({"select": "*", "order": key + ".asc", "limit": 500, "offset": offset}))
            if not isinstance(page, list):
                raise RuntimeError("Supabase returned an invalid table response")
            if not page:
                return result
            result.extend(page)
            offset += len(page)
        raise RuntimeError("Cloud snapshot exceeds supported row limit; refusing a partial scan")

    def rpc(self, name, body):
        return self.request("rpc/" + name, body)

    def reserve_digest(self, day):
        return self.rpc("ofir_reserve_digest", {"digest_day": day, "stamp": now()}) is True

    def finish_digest(self, day, outcome, events):
        self.rpc("ofir_finish_digest", {"digest_day": day, "outcome": outcome, "stamp": now(), "events": events})


def restore(db, remote):
    seed(db)
    with db:
        for table in TABLES:
            rows = remote.rows(table)
            if table == "companies" and not rows:
                raise RuntimeError("Cloud company seed is missing; run supabase/setup.sql first")
            allowed = {column[1] for column in db.execute(f"PRAGMA table_info({table})")}
            for row in rows:
                columns = [column for column in row if column in allowed]
                db.execute(f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [row[column] for column in columns])


def snapshot(db, migrate=False):
    tables = ("companies", "jobs", "job_events", "job_discoveries", "scans", "imports") + (("company_monitor_controls", "digest_runs") if migrate else ())
    return {table: [dict(row) for row in db.execute(f"SELECT * FROM {table}")] for table in tables}


def import_cloud_applications(db, remote, path):
    values = cli.import_applications(db, path)
    # Replay only this file, never old import rows that could overwrite later user progress.
    records = [dict(zip(("canonical_url", "application_status", "applied_at", "imported_at"), row)) for row in values]
    remote.rpc("ofir_import_applications", {"records": records})


def main():
    load_local_config()
    parser = argparse.ArgumentParser(description="Durable Supabase collector")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    scan = commands.add_parser("scan")
    scan.add_argument("--company")
    scan.add_argument("--expand-by", type=int, default=0)
    scan.add_argument("--limit", type=int, default=20)
    commands.add_parser("scheduled-scan")
    commands.add_parser("audit")
    commands.add_parser("probe-sources")
    digest = commands.add_parser("digest")
    digest.add_argument("--send", action="store_true")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--sqlite", required=True)
    importer = commands.add_parser("import-applications")
    importer.add_argument("file")
    findings = commands.add_parser("import-discoveries")
    findings.add_argument("file")
    args = parser.parse_args()
    try:
        if args.command == "scan" and (not 1 <= args.limit <= 50 or not 0 <= args.expand_by <= 5 or (args.company and args.expand_by)):
            raise ValueError("Use a limit of 1–50, expand by 0–5, and select either expansion or a specific company")
        if args.command == "scheduled-scan" and not scheduled_slot():
            print("Outside the Israeli-local 08:00/17:00 scan slots; no work scheduled")
            return 0
        remote = Remote()
        if args.command == "check":
            print(f"Supabase worker read access verified; {len(remote.rows('companies'))} companies")
            return 0
        if args.command == "import-discoveries":
            path = Path(args.file)
            if path.stat().st_size > 500_000:
                raise ValueError("Findings file exceeds 500KB")
            result = remote.rpc("ofir_add_discoveries", {"payload": json.loads(path.read_text(encoding="utf-8-sig"))})
            print("Imported unverified findings:", json.dumps(result))
            return 0
        with process_lock("cloud"):
            if args.command == "migrate":
                source = Path(args.sqlite).resolve()
                if not source.is_file():
                    raise ValueError("The source SQLite database does not exist")
                with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
                    db.row_factory = sqlite3.Row
                    remote.rpc("ofir_sync", {"payload": snapshot(db, migrate=True)})
                    remote.rpc("ofir_link_discoveries", {})
                print("Local snapshot copied to Supabase; existing cloud feedback preserved")
                return 0
            with tempfile.TemporaryDirectory(prefix="ofir-worker-") as folder:
                db = connect(Path(folder) / "worker.sqlite")
                try:
                    restore(db, remote)
                    if args.command == "probe-sources":
                        from .probe import report
                        report(db, output=Path('.local/source-probe/report.json'))
                        return 0
                    if args.command == "audit":
                        from .audit import report
                        report(db)
                        return 0
                    if args.command in {"scan", "scheduled-scan"}:
                        ids = new_sources(db, 1 if args.command == "scheduled-scan" else args.expand_by)
                        if ids:
                            activated = remote.rpc("ofir_enable_sources", {"ids": ids})
                            if not isinstance(activated, list) or any(value not in ids for value in activated):
                                raise RuntimeError("Invalid source activation response")
                            with db:
                                for company_id in activated:
                                    db.execute("UPDATE companies SET enabled=1 WHERE id=?", (company_id,))
                            print(f"Added {len(activated)} relevant sources to monitoring")
                        result = cli.scan(db, args.company if args.command == "scan" else None, args.limit if args.command == "scan" else 20)
                        verify_pending(db, limit=5)
                        # Commit successful sources and explicit failure status even after a partial failure.
                        remote.rpc("ofir_sync", {"payload": snapshot(db)})
                        remote.rpc("ofir_link_discoveries", {})
                        return result
                    if args.command == "digest":
                        cli.digest(db, args.send, delivery_store=remote)
                    else:
                        import_cloud_applications(db, remote, args.file)
                finally:
                    db.close()
        return 0
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
