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
    columns = []
    for filename in ('001_schema.sql', '004_growth.sql'):
        for table, body in re.findall(r'CREATE TABLE IF NOT EXISTS public\.(\w+) \((.*?)\n\);', (ROOT/'supabase'/filename).read_text(), re.S):
            for name, kind in re.findall(r'(?:^|,)\s*(\w+)\s+(TEXT|INTEGER|BIGINT)\b', body):
                columns.append(f"('{table}','{name}','{kind.lower()}')")
    columns.extend(f"('jobs','{name}','text')" for name in ('match_category','match_version','match_details'))
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
), required_columns(table_name,column_name,type_name) AS (VALUES
""" + ',\n'.join(columns) + """
), schema_check AS (
 SELECT bool_and(a.attname IS NOT NULL AND format_type(a.atttypid,a.atttypmod)=r.type_name) AS compatible
 FROM required_columns r LEFT JOIN pg_namespace n ON n.nspname='public'
 LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=r.table_name AND c.relkind='r'
 LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname=r.column_name AND NOT a.attisdropped
), grant_check AS (
 SELECT bool_and(CASE WHEN to_regclass('public.'||t) IS NULL THEN false ELSE
  has_table_privilege('service_role',to_regclass('public.'||t),'SELECT') AND
  has_table_privilege('service_role',to_regclass('public.'||t),'INSERT') AND
  has_table_privilege('service_role',to_regclass('public.'||t),'UPDATE') END) AS compatible
 FROM (SELECT DISTINCT table_name AS t FROM required_columns) tables
), sequence_check AS (
 SELECT bool_and(CASE WHEN to_regclass('public.'||t) IS NULL THEN false ELSE coalesce(has_sequence_privilege('service_role',
  pg_get_serial_sequence('public.'||t,'id'),'USAGE'),false) END) AS compatible
 FROM (VALUES ('scans'),('job_events'),('digest_runs')) tables(t)
), key_check AS (
 SELECT bool_and(EXISTS(SELECT 1 FROM pg_index i WHERE i.indrelid=to_regclass('public.'||t)
  AND i.indisunique AND i.indisvalid AND i.indpred IS NULL AND i.indexprs IS NULL
  AND ARRAY(SELECT a.attname::text FROM unnest(i.indkey) WITH ORDINALITY k(attnum,ord)
   JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum ORDER BY ord)=cols)) AS compatible
 FROM (VALUES ('jobs',ARRAY['id']),('jobs',ARRAY['url']),('companies',ARRAY['id']),
  ('scans',ARRAY['id']),('scans',ARRAY['company_id','started_at']),('job_events',ARRAY['job_id','version'])) keys(t,cols)
), migration_conflict AS (
 SELECT to_regclass('public.scheduled_slots') IS NULL
  AND to_regclass('public.scans_scheduled_attempt') IS NULL
  AND NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='scans'
   AND column_name IN ('scheduled_slot_id','scheduled_attempt','retry_kind','retry_after','checkpoint_receipt')) AS clear
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
 'table_schema_compatible',(SELECT compatible FROM schema_check),
 'worker_table_grants',(SELECT compatible FROM grant_check),
 'worker_sequences',(SELECT compatible FROM sequence_check),
 'required_unique_keys',(SELECT compatible FROM key_check),
 'migration_objects_absent',(SELECT clear FROM migration_conflict),
 'compatibility',CASE WHEN rls_bypass AND collision_free AND bodies_compatible
  AND (SELECT compatible FROM schema_check) AND (SELECT compatible FROM grant_check)
  AND (SELECT compatible FROM sequence_check) AND (SELECT compatible FROM key_check)
  AND (SELECT clear FROM migration_conflict)
  THEN 'PASS' ELSE 'REVIEW_REQUIRED' END) AS release_check FROM checks;
ROLLBACK;
"""


if __name__ == '__main__':
    (ROOT / 'supabase/release-readiness-check.sql').write_text(generate())
