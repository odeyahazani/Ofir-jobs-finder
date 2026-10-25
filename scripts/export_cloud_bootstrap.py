"""Prepare a private, one-time SQL-editor transfer; never commit the generated file."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector.cloud import snapshot

TABLE_ORDER = ("companies", "jobs", "job_events", "job_discoveries", "scans", "imports", "company_monitor_controls", "digest_runs")


def data_statement(payload, part=None):
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if "$ofir_snapshot$" in encoded:
        raise ValueError("Source data contains the SQL delimiter")
    label = f" Part {part}." if part else ""
    return ("-- PRIVATE DATA TRANSFER." + label + " Run the whole file after the structure upgrade.\nBEGIN;\n"
            "SELECT public.ofir_sync($ofir_snapshot$" + encoded + "$ofir_snapshot$::jsonb);\n"
            "SELECT public.ofir_link_discoveries();\nCOMMIT;\n")


def batch_payload(payload, max_bytes=700_000):
    """Keep whole records and parent-before-child order under the editor's UTF-8 byte limit."""
    if not 1000 <= max_bytes <= 900_000:
        raise ValueError("SQL batch limit must be between 1000 and 900000 bytes")
    if set(payload) - set(TABLE_ORDER):
        raise ValueError("Unknown snapshot table; update the dependency order before exporting")
    batches, current = [], {}
    for table in TABLE_ORDER:
        for row in payload.get(table, []):
            proposed = {**current, table: [*current.get(table, []), row]}
            if len(data_statement(proposed, "999/999").encode("utf-8")) > max_bytes:
                if current:
                    batches.append(current)
                current = {table: [row]}
                if len(data_statement(current, "999/999").encode("utf-8")) > max_bytes:
                    raise ValueError("A single record exceeds the editor limit; use the authenticated API transfer")
            else:
                current = proposed
    if current:
        batches.append(current)
    if len(batches) > 999:
        raise ValueError("Too many editor batches; use the authenticated API transfer")
    return batches


def export(source, target, max_bytes=700_000):
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_file():
        raise ValueError("Source database does not exist")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        payload = snapshot(db, migrate=True)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if "$ofir_snapshot$" in encoded:
        raise ValueError("Source data contains the SQL delimiter")
    upgrade = (ROOT / "supabase/upgrade-growth.sql").read_text().rstrip()
    if not upgrade.endswith("COMMIT;"):
        raise ValueError("Upgrade script must end in COMMIT")
    data_sql = ("\nSELECT public.ofir_sync($ofir_snapshot$" + encoded + "$ofir_snapshot$::jsonb);\n"
                "SELECT public.ofir_link_discoveries();\nCOMMIT;\n")
    batches = batch_payload(payload, max_bytes)
    sql = ("-- PRIVATE LOCAL DATA TRANSFER. Do not commit or post this generated file.\n"
           "-- Run the complete file in your own Supabase project's SQL Editor as database owner.\n" + upgrade[:-len("COMMIT;")] +
           data_sql)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sql)
    target.chmod(0o600)
    data_target = target.with_name(target.stem + "-data-only" + target.suffix)
    data_target.write_text("-- PRIVATE DATA ONLY. Apply supabase/upgrade-growth.sql separately first.\nBEGIN;\n" + data_sql)
    data_target.chmod(0o600)
    manifest = []
    paths = []
    for index, batch in enumerate(batches, 1):
        part_target = target.with_name(f"{target.stem}-part-{index:02d}{target.suffix}")
        part_sql = data_statement(batch, f"{index}/{len(batches)}")
        if len(part_sql.encode("utf-8")) > max_bytes:
            raise ValueError("SQL part exceeds the configured byte limit")
        part_target.write_text(part_sql)
        part_target.chmod(0o600)
        paths.append(part_target)
        manifest.append({"file": part_target.name, "bytes": part_target.stat().st_size, "records": {key: len(value) for key, value in batch.items()}})
    manifest_target = target.with_name(target.stem + "-parts.json")
    manifest_target.write_text(json.dumps(manifest, indent=2) + "\n")
    manifest_target.chmod(0o600)
    print(f"Private SQL transfer prepared: {len(payload['companies'])} companies, {len(payload['jobs'])} jobs; {target.stat().st_size} bytes")
    print(f"SQL Editor transfer prepared in {len(batches)} ordered parts, maximum {max_bytes} bytes each")
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default=str(ROOT / ".local/ofir.sqlite"))
    parser.add_argument("--output", default=str(ROOT / ".local/cloud-bootstrap.sql"))
    parser.add_argument("--batch-bytes", type=int, default=700_000)
    args = parser.parse_args()
    export(args.sqlite, args.output, args.batch_bytes)
