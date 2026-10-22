-- Run as the Supabase database owner. No application/browser role can edit the allowlist.
CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM PUBLIC, anon, authenticated;
CREATE TABLE IF NOT EXISTS private.ofir_owner (
 singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
 email TEXT NOT NULL CHECK (email=lower(email))
);
REVOKE ALL ON private.ofir_owner FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION private.configure_owner(owner_email TEXT)
RETURNS VOID LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
 IF owner_email IS NULL OR owner_email NOT LIKE '%@%.%' OR owner_email LIKE '%example.invalid%' THEN
   RAISE EXCEPTION 'Set a valid Google email for the app owner before running setup';
 END IF;
 INSERT INTO private.ofir_owner(singleton,email) VALUES(true,lower(trim(owner_email)))
 ON CONFLICT(singleton) DO UPDATE SET email=excluded.email;
END;
$$;
REVOKE ALL ON FUNCTION private.configure_owner(TEXT) FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.ofir_is_owner()
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path='' AS $$
 SELECT auth.uid() IS NOT NULL AND auth.jwt()->'app_metadata'->>'provider'='google' AND EXISTS (
   SELECT 1 FROM private.ofir_owner WHERE email=lower(auth.jwt()->>'email')
 );
$$;
REVOKE ALL ON FUNCTION public.ofir_is_owner() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.ofir_is_owner() TO authenticated;

ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.digest_runs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.companies,public.jobs,public.scans,public.job_events,public.imports,public.digest_runs
 FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.companies,public.jobs TO authenticated;
GRANT UPDATE(fit,familiar,application_status,personal_note,user_updated_at) ON public.jobs TO authenticated;
GRANT ALL ON public.companies,public.jobs,public.scans,public.job_events,public.imports,public.digest_runs TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.scans_id_seq,public.job_events_id_seq,public.digest_runs_id_seq TO service_role;

DROP POLICY IF EXISTS ofir_read_companies ON public.companies;
CREATE POLICY ofir_read_companies ON public.companies FOR SELECT TO authenticated USING ((SELECT public.ofir_is_owner()));
DROP POLICY IF EXISTS ofir_read_jobs ON public.jobs;
CREATE POLICY ofir_read_jobs ON public.jobs FOR SELECT TO authenticated USING ((SELECT public.ofir_is_owner()));
DROP POLICY IF EXISTS ofir_update_feedback ON public.jobs;
CREATE POLICY ofir_update_feedback ON public.jobs FOR UPDATE TO authenticated
 USING ((SELECT public.ofir_is_owner())) WITH CHECK ((SELECT public.ofir_is_owner()));
