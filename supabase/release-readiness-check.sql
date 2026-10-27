-- Run once in project suipvwdqfpgjwlsgrhot SQL Editor after verifying the dashboard reference.
-- Returns only compatibility indicators. Does not invoke worker RPCs or expose live bodies.
-- A false body match is REVIEW REQUIRED, not proof of semantic incompatibility.
BEGIN TRANSACTION READ ONLY;
WITH expected(signature, body) AS (VALUES
('public.ofir_sync(jsonb)', $expected$
DECLARE c public.companies; j public.jobs; s public.scans; e public.job_events; i public.imports; d public.digest_runs; finding JSONB;
BEGIN
 PERFORM pg_catalog.pg_advisory_xact_lock(4801739);
 FOR c IN SELECT * FROM jsonb_populate_recordset(NULL::public.companies,COALESCE(payload->'companies','[]')) LOOP
   INSERT INTO public.companies SELECT c.* ON CONFLICT(id) DO UPDATE SET
     source_status=excluded.source_status,last_checked=excluded.last_checked,last_result=excluded.last_result,
     job_count=excluded.job_count,verified_url=excluded.verified_url
     WHERE companies.last_checked IS NULL OR excluded.last_checked>=companies.last_checked;
 END LOOP;
 FOR j IN SELECT * FROM jsonb_populate_recordset(NULL::public.jobs,COALESCE(payload->'jobs','[]')) LOOP
   INSERT INTO public.jobs SELECT j.* ON CONFLICT(id) DO UPDATE SET
     source_id=excluded.source_id,title=excluded.title,location=excluded.location,work_model=excluded.work_model,
     url=excluded.url,description=excluded.description,published_at=excluded.published_at,updated_at=excluded.updated_at,
     last_seen_at=excluded.last_seen_at,last_verified_at=excluded.last_verified_at,status=excluded.status,
     score=excluded.score,breakdown=excluded.breakdown,reasons=excluded.reasons,gaps=excluded.gaps,
     experience=excluded.experience,eligible=excluded.eligible,exclusion_reason=excluded.exclusion_reason,
     content_hash=excluded.content_hash,version=excluded.version,
     match_category=COALESCE(excluded.match_category,jobs.match_category),
     match_version=COALESCE(excluded.match_version,jobs.match_version),
     match_details=COALESCE(excluded.match_details,jobs.match_details)
     WHERE excluded.last_seen_at>=jobs.last_seen_at
       AND (COALESCE(jobs.match_version,'')='' OR COALESCE(excluded.match_version,'')<>'');
   -- Feedback, application status, personal notes and first_seen_at are preserved on updates.
 END LOOP;
 FOR e IN SELECT * FROM jsonb_populate_recordset(NULL::public.job_events,COALESCE(payload->'job_events','[]')) LOOP
   INSERT INTO public.job_events(job_id,version,kind,created_at,notified_at)
    SELECT e.job_id,e.version,e.kind,e.created_at,e.notified_at
    WHERE EXISTS(SELECT 1 FROM public.jobs WHERE id=e.job_id AND version>=e.version)
    ON CONFLICT(job_id,version) DO NOTHING;
 END LOOP;
 FOR s IN SELECT * FROM jsonb_populate_recordset(NULL::public.scans,COALESCE(payload->'scans','[]')) LOOP
   INSERT INTO public.scans(company_id,started_at,finished_at,status,fetched_count,eligible_count,new_count,message)
   VALUES(s.company_id,s.started_at,s.finished_at,s.status,s.fetched_count,s.eligible_count,s.new_count,s.message)
   ON CONFLICT(company_id,started_at) DO NOTHING;
 END LOOP;
 FOR i IN SELECT * FROM jsonb_populate_recordset(NULL::public.imports,COALESCE(payload->'imports','[]')) LOOP
   INSERT INTO public.imports SELECT i.* ON CONFLICT(canonical_url) DO UPDATE SET
    application_status=excluded.application_status,applied_at=excluded.applied_at,imported_at=excluded.imported_at
    WHERE excluded.imported_at>=imports.imported_at;
 END LOOP;
 FOR d IN SELECT * FROM jsonb_populate_recordset(NULL::public.digest_runs,COALESCE(payload->'digest_runs','[]')) LOOP
   INSERT INTO public.digest_runs(day,status,created_at,sent_at) VALUES(d.day,d.status,d.created_at,d.sent_at)
   ON CONFLICT(day) DO NOTHING;
 END LOOP;
 FOR finding IN SELECT * FROM jsonb_array_elements(COALESCE(payload->'company_monitor_controls','[]')) LOOP
   INSERT INTO public.company_monitor_controls SELECT * FROM jsonb_populate_record(NULL::public.company_monitor_controls,finding)
   ON CONFLICT(company_id) DO NOTHING;
 END LOOP;
 FOR finding IN SELECT * FROM jsonb_array_elements(COALESCE(payload->'job_discoveries','[]')) LOOP
   INSERT INTO public.job_discoveries SELECT * FROM jsonb_populate_record(NULL::public.job_discoveries,finding)
   ON CONFLICT(url) DO UPDATE SET status=excluded.status,linked_job_id=excluded.linked_job_id,
    last_checked=excluded.last_checked,last_result=excluded.last_result
    WHERE excluded.last_checked IS NOT NULL AND (job_discoveries.last_checked IS NULL OR excluded.last_checked>=job_discoveries.last_checked)
      AND NOT(job_discoveries.status='linked' AND excluded.status='pending');
 END LOOP;
END;
$expected$),
('public.ofir_enable_sources(jsonb)', $expected$
 WITH activated AS (UPDATE public.companies SET enabled=1 WHERE id IN (SELECT jsonb_array_elements_text(ids)) AND enabled=0 AND last_checked IS NULL
  AND NOT EXISTS(SELECT 1 FROM public.company_monitor_controls m WHERE m.company_id=companies.id AND m.opted_out=1) RETURNING id)
 SELECT coalesce(jsonb_agg(id),'[]'::jsonb) FROM activated;
$expected$),
('public.ofir_link_discoveries()', $expected$
 UPDATE public.job_discoveries d SET linked_job_id=j.id,status='linked',last_checked=j.last_verified_at,
  last_result='הממצא קושר למשרה שנאספה ואומתה במקור הרשמי'
 FROM public.jobs j WHERE d.company_id=j.company_id AND d.url=j.url AND j.status='open' AND j.last_verified_at IS NOT NULL;
$expected$)
), bodies AS (
 SELECT signature, p.oid IS NOT NULL AS found,
  coalesce(md5(p.prosrc)=md5(e.body),false) AS exact_match,
  coalesce(md5(btrim(p.prosrc,E' \t\r\n'))=md5(btrim(e.body,E' \t\r\n')),false) AS boundary_match
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
