"""Generate one SQL-editor script with the schema, permissions and complete company seed."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def generate():
    companies = json.loads((ROOT / "data/companies.json").read_text())
    columns = list(companies[0])
    companies = [{k: int(v) if isinstance(v, bool) else v for k, v in company.items()} for company in companies]
    parts = ["-- Replace the email placeholder below before running this file in Supabase SQL Editor.\nBEGIN;\nSELECT set_config('ofir.setup_email','REPLACE_WITH_OFIR_GOOGLE_EMAIL',true);\n"]
    for filename in ["001_schema.sql", "002_permissions.sql", "005_matching.sql", "003_worker.sql", "004_growth.sql"]:
        parts.append((ROOT / "supabase" / filename).read_text())
    parts.append("\nSELECT private.configure_owner(current_setting('ofir.setup_email'));\n")
    names = ",".join(columns)
    data = json.dumps(companies, ensure_ascii=False, separators=(",", ":"))
    if "$ofir_seed$" in data:
        raise ValueError("Company data contains the SQL delimiter")
    parts.append(f"\nINSERT INTO public.companies ({names}) SELECT {names} FROM jsonb_populate_recordset(NULL::public.companies, $ofir_seed${data}$ofir_seed$::jsonb) ON CONFLICT(id) DO NOTHING;\n")
    parts.append("NOTIFY pgrst, 'reload schema';\nCOMMIT;\n")
    return "\n".join(parts)


if __name__ == "__main__":
    target = ROOT / "supabase/setup.sql"
    target.write_text(generate())
    (ROOT / "supabase/upgrade-growth.sql").write_text("BEGIN;\n" + (ROOT / "supabase/004_growth.sql").read_text() + "\n" + (ROOT / "supabase/005_matching.sql").read_text() + "\n" + (ROOT / "supabase/003_worker.sql").read_text() + "\nNOTIFY pgrst, 'reload schema';\nCOMMIT;\n")
    (ROOT / "supabase/upgrade-matching.sql").write_text("BEGIN;\n" + (ROOT / "supabase/005_matching.sql").read_text() + "\n" + (ROOT / "supabase/003_worker.sql").read_text() + "\nNOTIFY pgrst, 'reload schema';\nCOMMIT;\n")
    print("Generated setup.sql, upgrade-growth.sql and upgrade-matching.sql")
