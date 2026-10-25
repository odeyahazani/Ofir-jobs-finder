"""Prepare a private, one-time SQL-editor transfer; never commit the generated file."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector.cloud import snapshot


def export(source, target):
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
    sql = ("-- PRIVATE LOCAL DATA TRANSFER. Do not commit or post this generated file.\n"
           "-- Run the complete file in your own Supabase project's SQL Editor as database owner.\n" + upgrade[:-len("COMMIT;")] +
           data_sql)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sql)
    target.chmod(0o600)
    data_target = target.with_name(target.stem + "-data-only" + target.suffix)
    data_target.write_text("-- PRIVATE DATA ONLY. Apply supabase/upgrade-growth.sql separately first.\nBEGIN;\n" + data_sql)
    data_target.chmod(0o600)
    print(f"Private SQL transfer prepared: {len(payload['companies'])} companies, {len(payload['jobs'])} jobs; {target.stat().st_size} bytes")
    print("Separate data-only SQL file prepared for the two-step SQL Editor workflow")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default=str(ROOT / ".local/ofir.sqlite"))
    parser.add_argument("--output", default=str(ROOT / ".local/cloud-bootstrap.sql"))
    args = parser.parse_args()
    export(args.sqlite, args.output)
