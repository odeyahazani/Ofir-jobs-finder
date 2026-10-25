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
