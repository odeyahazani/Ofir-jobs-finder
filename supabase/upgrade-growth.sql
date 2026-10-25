BEGIN;
-- Additive upgrade. Existing owner configuration, jobs, feedback and history are retained.
CREATE TABLE IF NOT EXISTS public.company_monitor_controls (
 company_id TEXT PRIMARY KEY REFERENCES public.companies(id), opted_out INTEGER NOT NULL CHECK(opted_out IN (0,1))
);
ALTER TABLE public.company_monitor_controls ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.company_monitor_controls FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.company_monitor_controls TO authenticated;
GRANT ALL ON public.company_monitor_controls TO service_role;
DROP POLICY IF EXISTS ofir_read_monitor_controls ON public.company_monitor_controls;
CREATE POLICY ofir_read_monitor_controls ON public.company_monitor_controls FOR SELECT TO authenticated USING((SELECT public.ofir_is_owner()));
CREATE TABLE IF NOT EXISTS public.job_discoveries (
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES public.companies(id),
 company_name TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
 location_hint TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
 added_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','linked')),
 linked_job_id TEXT REFERENCES public.jobs(id), last_checked TEXT,
 last_result TEXT NOT NULL DEFAULT 'ממצא שיובא — טרם אומת במקור הרשמי'
);
ALTER TABLE public.job_discoveries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.job_discoveries FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.job_discoveries TO authenticated;
GRANT ALL ON public.job_discoveries TO service_role;
DROP POLICY IF EXISTS ofir_read_discoveries ON public.job_discoveries;
CREATE POLICY ofir_read_discoveries ON public.job_discoveries FOR SELECT TO authenticated USING((SELECT public.ofir_is_owner()));

CREATE OR REPLACE FUNCTION private.clean_source_url(value TEXT,optional BOOLEAN DEFAULT false)
RETURNS TEXT LANGUAGE plpgsql SET search_path='' AS $$
DECLARE base TEXT; authority TEXT; query TEXT; path TEXT;
BEGIN
 IF optional AND coalesce(value,'')='' THEN RETURN ''; END IF;
 value:=btrim(value);
 IF value IS NULL OR length(value)>2000 OR value ~ '[[:space:][:cntrl:]]' OR value !~ '^https://([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/|\?|#|$)' THEN RAISE EXCEPTION 'A public HTTPS URL is required'; END IF;
 authority:=lower(substring(value FROM '^https://([^/?#]+)'));
 IF authority ~ '\.(local|internal|localhost|test|invalid)$' THEN RAISE EXCEPTION 'Private hosts are not supported'; END IF;
 value:=split_part(value,'#',1);
 path:=regexp_replace(split_part(value,'?',1),'^https://[^/?#]+','');
 path:=regexp_replace(path,'/+$','');
 base:='https://'||authority||path;
 IF position('?' IN value)>0 THEN
   SELECT string_agg(part,'&' ORDER BY part) INTO query FROM unnest(string_to_array(split_part(value,'?',2),'&')) part
    WHERE part<>'' AND lower(split_part(part,'=',1)) !~ '^utm_' AND lower(split_part(part,'=',1)) NOT IN ('source','ref','gh_src','fbclid','gclid');
 END IF;
 RETURN base||CASE WHEN coalesce(query,'')<>'' THEN '?'||query ELSE '' END;
END;
$$;
REVOKE ALL ON FUNCTION private.clean_source_url(TEXT,BOOLEAN) FROM PUBLIC,anon,authenticated;

CREATE OR REPLACE FUNCTION public.ofir_add_discoveries(payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE c JSONB; j JSONB; label TEXT; career TEXT; target_id TEXT; target_url TEXT; ats TEXT; identifier TEXT;
 added_companies INTEGER:=0; added_jobs INTEGER:=0; changed INTEGER;
BEGIN
 IF NOT coalesce(public.ofir_is_owner(),false) AND coalesce(auth.jwt()->>'role','')<>'service_role' THEN RAISE EXCEPTION 'Forbidden'; END IF;
 IF jsonb_typeof(coalesce(payload->'companies','[]'))<>'array' OR jsonb_typeof(coalesce(payload->'jobs','[]'))<>'array'
   OR jsonb_array_length(coalesce(payload->'companies','[]'))+jsonb_array_length(coalesce(payload->'jobs','[]')) NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'Import must contain 1 to 100 findings'; END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(4801739);
 FOR c IN SELECT * FROM jsonb_array_elements(coalesce(payload->'companies','[]')) UNION ALL
  SELECT jsonb_build_object('name',v->>'company') FROM jsonb_array_elements(coalesce(payload->'jobs','[]')) v LOOP
   label:=btrim(c->>'name');
   IF label IS NULL OR length(label) NOT BETWEEN 1 AND 200 OR length(coalesce(c->>'notes',''))>4000 OR length(coalesce(c->>'location',''))>250 THEN RAISE EXCEPTION 'Invalid company'; END IF;
   career:=private.clean_source_url(c->>'career_url',true);
   ats:='Generic HTML'; identifier:='';
   IF career ~ '^https://(www\.)?comeet\.(com|co)/jobs/' THEN ats:='Comeet'; END IF;
   IF career ~ '^https://(job-boards(\.eu)?|boards)\.greenhouse\.io/[^/?]+' THEN
     ats:='Greenhouse'; identifier:=split_part(regexp_replace(career,'^https://[^/]+/',''), '/',1);
   END IF;
   SELECT id INTO target_id FROM public.companies WHERE lower(btrim(name))=lower(label) ORDER BY id LIMIT 1;
   IF target_id IS NOT NULL THEN
     UPDATE public.companies SET career_url=career,ats_hint=ats,ats_identifier=identifier WHERE id=target_id AND career_url='' AND career<>'';
     CONTINUE;
   END IF;
   INSERT INTO public.companies(id,name,location_hint,suggested_url,career_url,ats_hint,ats_identifier,imported_active,
    imported_priority,imported_last_checked,imported_last_result,notes,enabled)
    VALUES(substr(md5(lower(label)),1,16),label,coalesce(c->>'location',''),career,career,ats,identifier,0,'Medium','','',coalesce(c->>'notes',''),0)
    ON CONFLICT(id) DO NOTHING;
   GET DIAGNOSTICS changed=ROW_COUNT; added_companies:=added_companies+changed;
 END LOOP;
 FOR j IN SELECT * FROM jsonb_array_elements(coalesce(payload->'jobs','[]')) LOOP
   IF length(coalesce(j->>'title','')) NOT BETWEEN 1 AND 250 OR length(coalesce(j->>'notes',''))>4000 OR length(coalesce(j->>'location',''))>250 THEN RAISE EXCEPTION 'Invalid job finding'; END IF;
   target_url:=private.clean_source_url(j->>'url');
   SELECT id INTO target_id FROM public.companies WHERE lower(btrim(name))=lower(btrim(j->>'company')) ORDER BY id LIMIT 1;
   INSERT INTO public.job_discoveries(id,company_id,company_name,title,url,location_hint,notes,added_at)
    VALUES(substr(md5(target_url),1,24),target_id,btrim(j->>'company'),btrim(j->>'title'),target_url,coalesce(j->>'location',''),coalesce(j->>'notes',''),to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"+00:00"'))
    ON CONFLICT(url) DO NOTHING;
   GET DIAGNOSTICS changed=ROW_COUNT; added_jobs:=added_jobs+changed;
 END LOOP;
 RETURN jsonb_build_object('companies_added',added_companies,'jobs_added',added_jobs);
END;
$$;
REVOKE ALL ON FUNCTION public.ofir_add_discoveries(JSONB) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.ofir_add_discoveries(JSONB) TO authenticated,service_role;

CREATE OR REPLACE FUNCTION public.ofir_set_monitor(target_id TEXT,monitor BOOLEAN)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NOT coalesce(public.ofir_is_owner(),false) THEN RAISE EXCEPTION 'Forbidden'; END IF;
 IF monitor AND NOT EXISTS(SELECT 1 FROM public.companies WHERE id=target_id AND career_url<>'') THEN RAISE EXCEPTION 'Add a career URL first'; END IF;
 UPDATE public.companies SET enabled=CASE WHEN monitor THEN 1 ELSE 0 END WHERE id=target_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Company not found'; END IF;
 INSERT INTO public.company_monitor_controls(company_id,opted_out) VALUES(target_id,CASE WHEN monitor THEN 0 ELSE 1 END)
 ON CONFLICT(company_id) DO UPDATE SET opted_out=excluded.opted_out;
END;
$$;
REVOKE ALL ON FUNCTION public.ofir_set_monitor(TEXT,BOOLEAN) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.ofir_set_monitor(TEXT,BOOLEAN) TO authenticated;

CREATE OR REPLACE FUNCTION public.ofir_enable_sources(ids JSONB)
RETURNS JSONB LANGUAGE SQL SET search_path='' AS $$
 WITH activated AS (UPDATE public.companies SET enabled=1 WHERE id IN (SELECT jsonb_array_elements_text(ids)) AND enabled=0 AND last_checked IS NULL
  AND NOT EXISTS(SELECT 1 FROM public.company_monitor_controls m WHERE m.company_id=companies.id AND m.opted_out=1) RETURNING id)
 SELECT coalesce(jsonb_agg(id),'[]'::jsonb) FROM activated;
$$;
REVOKE ALL ON FUNCTION public.ofir_enable_sources(JSONB) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ofir_enable_sources(JSONB) TO service_role;

CREATE OR REPLACE FUNCTION public.ofir_link_discoveries()
RETURNS VOID LANGUAGE SQL SET search_path='' AS $$
 UPDATE public.job_discoveries d SET linked_job_id=j.id,status='linked',last_checked=j.last_verified_at,
  last_result='הממצא קושר למשרה שנאספה ואומתה במקור הרשמי'
 FROM public.jobs j WHERE d.company_id=j.company_id AND d.url=j.url AND j.status='open' AND j.last_verified_at IS NOT NULL;
$$;
REVOKE ALL ON FUNCTION public.ofir_link_discoveries() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ofir_link_discoveries() TO service_role;

-- Narrow, transaction-safe write operations for the trusted collector only.
CREATE OR REPLACE FUNCTION public.ofir_sync(payload JSONB)
RETURNS VOID LANGUAGE plpgsql SET search_path='' AS $$
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
     content_hash=excluded.content_hash,version=excluded.version
     WHERE excluded.last_seen_at>=jobs.last_seen_at;
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
$$;

CREATE OR REPLACE FUNCTION public.ofir_reserve_digest(digest_day TEXT, stamp TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql SET search_path='' AS $$
DECLARE changed INTEGER;
BEGIN
 INSERT INTO public.digest_runs(day,status,created_at) VALUES(digest_day,'sending',stamp)
 ON CONFLICT(day) DO NOTHING;
 GET DIAGNOSTICS changed=ROW_COUNT;
 RETURN changed=1;
END;
$$;

CREATE OR REPLACE FUNCTION public.ofir_finish_digest(digest_day TEXT, outcome TEXT, stamp TEXT, events JSONB)
RETURNS VOID LANGUAGE plpgsql SET search_path='' AS $$
DECLARE e JSONB;
BEGIN
 IF outcome NOT IN ('sent','uncertain') THEN RAISE EXCEPTION 'Invalid digest outcome'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.digest_runs WHERE day=digest_day AND status='sending') THEN
   RAISE EXCEPTION 'Digest is not reserved';
 END IF;
 IF outcome='sent' THEN
   FOR e IN SELECT * FROM jsonb_array_elements(events) LOOP
     UPDATE public.job_events SET notified_at=stamp WHERE job_id=e->>'job_id' AND version=(e->>'version')::INTEGER;
   END LOOP;
 END IF;
 UPDATE public.digest_runs SET status=outcome,sent_at=CASE WHEN outcome='sent' THEN stamp ELSE NULL END WHERE day=digest_day;
END;
$$;

CREATE OR REPLACE FUNCTION public.ofir_import_applications(records JSONB)
RETURNS VOID LANGUAGE plpgsql SET search_path='' AS $$
DECLARE i public.imports;
BEGIN
 FOR i IN SELECT * FROM jsonb_populate_recordset(NULL::public.imports,records) LOOP
   IF i.application_status NOT IN ('not_applied','planned','applied','interviewing','rejected','withdrawn')
     OR i.canonical_url NOT LIKE 'https://%' THEN RAISE EXCEPTION 'Invalid import record'; END IF;
   INSERT INTO public.imports SELECT i.* ON CONFLICT(canonical_url) DO UPDATE SET
    application_status=excluded.application_status,applied_at=excluded.applied_at,imported_at=excluded.imported_at;
   UPDATE public.jobs SET application_status=i.application_status,familiar=1,user_updated_at=i.imported_at
    WHERE url=i.canonical_url;
 END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION public.ofir_sync(JSONB),public.ofir_reserve_digest(TEXT,TEXT),
 public.ofir_finish_digest(TEXT,TEXT,TEXT,JSONB),public.ofir_import_applications(JSONB)
 FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ofir_sync(JSONB),public.ofir_reserve_digest(TEXT,TEXT),
 public.ofir_finish_digest(TEXT,TEXT,TEXT,JSONB),public.ofir_import_applications(JSONB) TO service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
