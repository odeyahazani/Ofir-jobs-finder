-- Narrow, transaction-safe write operations for the trusted collector only.
CREATE OR REPLACE FUNCTION public.ofir_sync(payload JSONB)
RETURNS VOID LANGUAGE plpgsql SET search_path='' AS $$
DECLARE c public.companies; j public.jobs; s public.scans; e public.job_events; i public.imports; d public.digest_runs;
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
