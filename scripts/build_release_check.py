"""Generate a read-only, indicator-only production check; never connects to a database."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def generate():
    expected = []
    for filename, names in [('003_worker.sql', ['ofir_sync']), ('004_growth.sql', ['ofir_enable_sources', 'ofir_link_discoveries'])]:
        source = (ROOT / 'supabase' / filename).read_text()
        for name in names:
            body = re.search(r'CREATE OR REPLACE FUNCTION public\.' + name + r'\(.*?AS \$\$(.*?)\$\$;', source, re.S).group(1)
            assert '$expected$' not in body
            signature = 'public.' + name + ('()' if name == 'ofir_link_discoveries' else '(jsonb)')
            expected.append(f"('{signature}', $expected${body}$expected$)")
    return """-- Run once in project suipvwdqfpgjwlsgrhot SQL Editor after verifying the dashboard reference.
-- Returns only compatibility indicators. Does not invoke worker RPCs or expose live bodies.
-- A false body match is REVIEW REQUIRED, not proof of semantic incompatibility.
BEGIN TRANSACTION READ ONLY;
WITH expected(signature, body) AS (VALUES
""" + ',\n'.join(expected) + """
), bodies AS (
 SELECT signature, p.oid IS NOT NULL AS found,
  coalesce(md5(p.prosrc)=md5(e.body),false) AS exact_match,
  coalesce(md5(btrim(p.prosrc,E' \\t\\r\\n'))=md5(btrim(e.body,E' \\t\\r\\n')),false) AS boundary_match
 FROM expected e LEFT JOIN pg_proc p ON p.oid=to_regprocedure(signature)
), collisions AS (
 SELECT count(*) AS count FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.proname IN (
  'ofir_scheduled_report','ofir_claim_scheduled','ofir_prepare_scheduled',
  'ofir_begin_scheduled_company','ofir_checkpoint_scheduled','ofir_finish_scheduled')
), checks AS (
 SELECT coalesce((SELECT rolbypassrls FROM pg_roles WHERE rolname='service_role'),false) AS rls_bypass,
  (SELECT count=0 FROM collisions) AS collision_free,
  (SELECT bool_and(found AND boundary_match) FROM bodies) AS bodies_compatible
)
SELECT jsonb_build_object(
 'project_reference_requires_dashboard_confirmation','suipvwdqfpgjwlsgrhot',
 'function_bodies',(SELECT jsonb_agg(to_jsonb(bodies)) FROM bodies),
 'scheduling_rpc_collision_free',collision_free,
 'service_role_rls_bypass',rls_bypass,
 'compatibility',CASE WHEN rls_bypass AND collision_free AND bodies_compatible
  THEN 'PASS' ELSE 'REVIEW_REQUIRED' END) AS release_check FROM checks;
ROLLBACK;
"""


if __name__ == '__main__':
    (ROOT / 'supabase/release-readiness-check.sql').write_text(generate())
