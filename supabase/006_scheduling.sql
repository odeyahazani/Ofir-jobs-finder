-- Additive scheduling only: no job reseed, deletion, rescore, or owner change.
CREATE TABLE IF NOT EXISTS public.scheduled_slots (
 id TEXT PRIMARY KEY, local_day DATE NOT NULL, slot_name TEXT NOT NULL CHECK(slot_name IN ('morning','evening')),
 target_at TIMESTAMPTZ NOT NULL, deadline_at TIMESTAMPTZ NOT NULL,
 state TEXT NOT NULL DEFAULT 'retry_wait' CHECK(state IN ('running','retry_wait','completed','failed')),
 company_ids JSONB CHECK(company_ids IS NULL OR jsonb_typeof(company_ids)='array'), deferred_count INTEGER NOT NULL DEFAULT 0,
 attempt_token TEXT, lease_until TIMESTAMPTZ, claims INTEGER NOT NULL DEFAULT 0,
 run_id TEXT, commit_sha TEXT, actual_start TIMESTAMPTZ, finished_at TIMESTAMPTZ,
 reason TEXT, UNIQUE(local_day,slot_name)
);
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS scheduled_slot_id TEXT REFERENCES public.scheduled_slots(id);
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS scheduled_attempt TEXT;
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS retry_kind TEXT;
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS retry_after TIMESTAMPTZ;
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS checkpoint_receipt JSONB;
CREATE UNIQUE INDEX IF NOT EXISTS scans_scheduled_attempt ON public.scans(scheduled_slot_id,company_id,scheduled_attempt)
 WHERE scheduled_slot_id IS NOT NULL;
ALTER TABLE public.scheduled_slots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.scheduled_slots FROM PUBLIC,anon,authenticated;
GRANT ALL ON public.scheduled_slots TO service_role;

-- The existing per-company scans are the retry ledger; no second work queue.
CREATE OR REPLACE FUNCTION public.ofir_scheduled_report(slot_id TEXT)
RETURNS JSONB LANGUAGE plpgsql SET search_path='' AS $$
DECLARE slot public.scheduled_slots; company TEXT; c public.companies; latest public.scans;
 n INTEGER; successes INTEGER; streak INTEGER; cooldown TIMESTAMPTZ; ready TIMESTAMPTZ;
 kind TEXT; details JSONB:='[]'; item JSONB; totals JSONB;
BEGIN
 SELECT * INTO STRICT slot FROM public.scheduled_slots WHERE id=slot_id;
 FOR company IN SELECT jsonb_array_elements_text(coalesce(slot.company_ids,'[]')) LOOP
  SELECT * INTO c FROM public.companies WHERE id=company;
  SELECT count(*),count(*) FILTER(WHERE status IN ('ok','empty')) INTO n,successes
   FROM public.scans WHERE scheduled_slot_id=slot_id AND company_id=company;
  SELECT * INTO latest FROM public.scans WHERE scheduled_slot_id=slot_id AND company_id=company ORDER BY id DESC LIMIT 1;
  -- Two consecutive exhausted slots cause a 24h cooldown, then one recovery probe.
  SELECT count(*) FILTER(WHERE exhausted),max(ended) FILTER(WHERE exhausted)+interval '24 hours'
   INTO streak,cooldown FROM (
    SELECT (count(*)>=3 OR bool_or(s.retry_kind='permanent') OR bool_or(t.state='failed'))
     AND NOT bool_or(s.status IN ('ok','empty')) AS exhausted,
     max(s.finished_at::timestamptz) AS ended
    FROM public.scans s JOIN public.scheduled_slots t ON t.id=s.scheduled_slot_id
    WHERE s.company_id=company AND t.target_at<slot.target_at
    GROUP BY t.id,t.target_at ORDER BY t.target_at DESC LIMIT 2
   ) history;
  ready:=CASE WHEN streak=2 THEN cooldown ELSE NULL END;
  IF latest.retry_after IS NOT NULL THEN ready:=greatest(ready,latest.retry_after); END IF;
  kind:=CASE
   WHEN successes>0 THEN 'checked'
   WHEN c.enabled<>1 OR EXISTS(SELECT 1 FROM public.company_monitor_controls m WHERE m.company_id=company AND m.opted_out=1) THEN 'waived'
   WHEN latest.status='running' THEN 'running'
   WHEN n>=CASE WHEN streak=2 THEN 1 ELSE 3 END OR latest.retry_kind='permanent' THEN 'exhausted'
   WHEN ready>=slot.deadline_at THEN 'exhausted'
   WHEN ready>clock_timestamp() THEN 'pending_retry'
   ELSE 'ready' END;
  item:=jsonb_build_object('company_id',company,'company',c.name,'state',kind,'attempts',n,
    'last_scan_id',latest.id,'checkpoint_confirmed',latest.checkpoint_receipt IS NOT NULL,
    'retry_at',ready,'source_status',latest.status,'message',latest.message,'retry_kind',latest.retry_kind);
  details:=details||jsonb_build_array(item);
 END LOOP;
 SELECT jsonb_build_object(
  'jobs_extracted',coalesce(sum(fetched_count),0),'jobs_discovered',coalesce(sum(new_count),0),
  'jobs_inserted',coalesce(sum((checkpoint_receipt->>'inserted')::integer),0),
  'jobs_updated',coalesce(sum((checkpoint_receipt->>'updated')::integer),0),
  'source_failures',count(*) FILTER(WHERE status NOT IN ('ok','empty','running')),
  'companies_attempted',count(DISTINCT company_id), 'source_attempts',count(*)) INTO totals
 FROM public.scans WHERE scheduled_slot_id=slot_id;
 RETURN to_jsonb(slot)||totals||jsonb_build_object('companies',details,
  'selected',jsonb_array_length(coalesce(slot.company_ids,'[]')),
  'checked',(SELECT count(*) FROM jsonb_array_elements(details) d WHERE d->>'state'='checked'),
  'unsupported',(SELECT count(*) FROM jsonb_array_elements(details) d WHERE d->>'source_status'='unsupported'),
  'blocked',(SELECT count(*) FROM jsonb_array_elements(details) d WHERE d->>'source_status'='blocked'),
  'waived',(SELECT count(*) FROM jsonb_array_elements(details) d WHERE d->>'state'='waived'),
  'exhausted',(SELECT count(*) FROM jsonb_array_elements(details) d WHERE d->>'state'='exhausted'),
  'pending_retry',(SELECT count(*) FROM jsonb_array_elements(details) d WHERE d->>'state' IN ('ready','running','pending_retry')),
  'persistence','confirmed');
END;
$$;

CREATE OR REPLACE FUNCTION public.ofir_claim_scheduled(worker_token TEXT, workflow_run TEXT, sha TEXT)
RETURNS JSONB LANGUAGE plpgsql SET search_path='' AS $$
DECLARE slot public.scheduled_slots; observed_at TIMESTAMPTZ:=clock_timestamp(); expired JSONB;
 candidate RECORD; report JSONB;
BEGIN
 IF coalesce(length(worker_token),0) NOT BETWEEN 16 AND 100 THEN RAISE EXCEPTION 'Invalid attempt token'; END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(4801740);
 observed_at:=clock_timestamp();
 -- Targets are civil Israeli times; elapsed horizon uses timestamptz, including DST days.
 FOR candidate IN
  SELECT day::date AS day,name,((day::date+hour::time) AT TIME ZONE 'Asia/Jerusalem') AS target
  FROM generate_series(coalesce((SELECT max(local_day) FROM public.scheduled_slots),
   (observed_at AT TIME ZONE 'Asia/Jerusalem')::date-1),
   (observed_at AT TIME ZONE 'Asia/Jerusalem')::date,interval '1 day') day
  CROSS JOIN (VALUES ('morning','08:17'),('evening','17:17')) hours(name,hour)
 LOOP
  IF candidate.target<=observed_at THEN
   INSERT INTO public.scheduled_slots(id,local_day,slot_name,target_at,deadline_at)
    VALUES(candidate.day||'/'||candidate.name,candidate.day,candidate.name,candidate.target,candidate.target+interval '24 hours')
    ON CONFLICT DO NOTHING;
  END IF;
 END LOOP;
 -- A cancelled finalizer must not turn fully checkpointed work into a missed slot.
 UPDATE public.scheduled_slots t SET state='completed',reason='completion_recovered',finished_at=observed_at,lease_until=NULL
 WHERE state IN ('running','retry_wait') AND (lease_until IS NULL OR lease_until<=observed_at)
  AND jsonb_array_length(coalesce(company_ids,'[]'))>0
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(public.ofir_scheduled_report(t.id)->'companies') d
   WHERE d->>'state' NOT IN ('checked','waived'));
 WITH changed AS (
  UPDATE public.scheduled_slots SET state='failed',reason=CASE WHEN deadline_at<=observed_at THEN 'recovery_deadline_exceeded' ELSE 'claim_limit_exceeded' END,finished_at=observed_at,
   lease_until=NULL WHERE (deadline_at<=observed_at OR claims>=24) AND state IN ('running','retry_wait')
   AND (lease_until IS NULL OR lease_until<=observed_at) RETURNING id
 ) SELECT coalesce(jsonb_agg(id),'[]') INTO expired FROM changed;
 -- Lost claim acknowledgements replay the same token without creating a new attempt.
 SELECT * INTO slot FROM public.scheduled_slots WHERE attempt_token=worker_token AND state='running' AND lease_until>observed_at FOR UPDATE;
 IF FOUND THEN RETURN jsonb_build_object('outcome','claimed','slot',public.ofir_scheduled_report(slot.id),'expired_slots',expired); END IF;
 IF EXISTS(SELECT 1 FROM public.scheduled_slots WHERE state='running' AND lease_until>observed_at) THEN
  RETURN jsonb_build_object('outcome','skipped','reason','lease_owned','slot',public.ofir_scheduled_report((SELECT id FROM public.scheduled_slots WHERE state='running' AND lease_until>observed_at ORDER BY target_at DESC LIMIT 1)),'expired_slots',expired);
 END IF;
 -- Initial slots before retries; a newly due slot cannot be starved by old failures.
 FOR slot IN SELECT * FROM public.scheduled_slots WHERE state IN ('running','retry_wait') AND deadline_at>observed_at
  AND claims<24 ORDER BY (company_ids IS NULL) DESC,target_at DESC FOR UPDATE LOOP
  -- Cancelled workers consumed an attempt, but cannot overwrite a successor's result.
  UPDATE public.scans SET status='error',retry_kind='transient',message='Worker lease expired before checkpoint',
   finished_at=observed_at::text,retry_after=observed_at+interval '1 hour'
   WHERE scheduled_slot_id=slot.id AND status='running';
  report:=public.ofir_scheduled_report(slot.id);
  IF slot.company_ids IS NOT NULL AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(report->'companies') d WHERE d->>'state'='ready') THEN
   IF (report->>'pending_retry')::integer=0 THEN
    UPDATE public.scheduled_slots SET state=CASE WHEN (report->>'exhausted')::integer>0 OR (report->>'selected')::integer=0 THEN 'failed' ELSE 'completed' END,
     lease_until=NULL,finished_at=observed_at WHERE id=slot.id;
   ELSE
    UPDATE public.scheduled_slots SET state='retry_wait',lease_until=NULL WHERE id=slot.id;
   END IF;
   CONTINUE;
  END IF;
  UPDATE public.scheduled_slots SET state='running',attempt_token=worker_token,lease_until=clock_timestamp()+interval '30 minutes',
   claims=claims+1,actual_start=coalesce(actual_start,clock_timestamp()),run_id=workflow_run,commit_sha=sha WHERE id=slot.id;
  RETURN jsonb_build_object('outcome','claimed','slot',public.ofir_scheduled_report(slot.id),'expired_slots',expired);
 END LOOP;
 RETURN jsonb_build_object('outcome','skipped','reason','no_eligible_work','slot',CASE WHEN EXISTS(SELECT 1 FROM public.scheduled_slots) THEN public.ofir_scheduled_report((SELECT id FROM public.scheduled_slots ORDER BY target_at DESC LIMIT 1)) END,'expired_slots',expired);
END;
$$;

CREATE OR REPLACE FUNCTION public.ofir_prepare_scheduled(slot_id TEXT, worker_token TEXT, expansion_ids JSONB)
RETURNS JSONB LANGUAGE plpgsql SET search_path='' AS $$
DECLARE slot public.scheduled_slots; selected JSONB; enabled_count INTEGER;
BEGIN
 SELECT * INTO STRICT slot FROM public.scheduled_slots WHERE id=slot_id FOR UPDATE;
 PERFORM pg_catalog.pg_advisory_xact_lock(4801739);
 IF slot.attempt_token IS DISTINCT FROM worker_token OR slot.state<>'running' OR slot.lease_until<=clock_timestamp() OR slot.deadline_at<=clock_timestamp() THEN RAISE EXCEPTION 'Scheduled lease lost'; END IF;
 IF slot.company_ids IS NULL THEN
  IF jsonb_array_length(expansion_ids)>1 THEN RAISE EXCEPTION 'Expand by at most one source'; END IF;
  PERFORM public.ofir_enable_sources(expansion_ids);
  SELECT coalesce(jsonb_agg(id),'[]') INTO selected FROM (
   SELECT c.id FROM public.companies c WHERE enabled=1 AND NOT EXISTS(
    SELECT 1 FROM public.company_monitor_controls m WHERE m.company_id=c.id AND m.opted_out=1)
   ORDER BY (last_checked IS NOT NULL),last_checked,id LIMIT 20
  ) choices;
  SELECT count(*) INTO enabled_count FROM public.companies WHERE enabled=1;
  UPDATE public.scheduled_slots SET company_ids=selected,deferred_count=greatest(0,enabled_count-jsonb_array_length(selected)) WHERE id=slot_id;
 END IF;
 RETURN public.ofir_scheduled_report(slot_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.ofir_begin_scheduled_company(slot_id TEXT, worker_token TEXT, company TEXT)
RETURNS JSONB LANGUAGE plpgsql SET search_path='' AS $$
DECLARE slot public.scheduled_slots; item JSONB; scan public.scans;
BEGIN
 SELECT * INTO STRICT slot FROM public.scheduled_slots WHERE id=slot_id FOR UPDATE;
 IF slot.attempt_token IS DISTINCT FROM worker_token OR slot.state<>'running' OR slot.lease_until<=clock_timestamp() OR slot.deadline_at<=clock_timestamp() THEN RAISE EXCEPTION 'Scheduled lease lost'; END IF;
 SELECT * INTO scan FROM public.scans WHERE scheduled_slot_id=slot_id AND company_id=company AND scheduled_attempt=worker_token;
 IF FOUND THEN RETURN to_jsonb(scan); END IF;
 SELECT d INTO item FROM jsonb_array_elements(public.ofir_scheduled_report(slot_id)->'companies') d WHERE d->>'company_id'=company;
 IF item IS NULL OR item->>'state'<>'ready' THEN RETURN jsonb_build_object('status','skipped'); END IF;
 INSERT INTO public.scans(company_id,started_at,status,scheduled_slot_id,scheduled_attempt)
 VALUES(company,clock_timestamp()::text,'running',slot_id,worker_token) RETURNING * INTO scan;
 UPDATE public.scheduled_slots SET lease_until=clock_timestamp()+interval '30 minutes' WHERE id=slot_id;
 RETURN to_jsonb(scan);
END;
$$;

CREATE OR REPLACE FUNCTION public.ofir_checkpoint_scheduled(slot_id TEXT, worker_token TEXT, company TEXT,
 result JSONB, payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SET search_path='' AS $$
DECLARE slot public.scheduled_slots; scan public.scans; inserted INTEGER; updated INTEGER; receipt JSONB;
 attempt_count INTEGER; stamp TIMESTAMPTZ; next_retry TIMESTAMPTZ; is_retryable BOOLEAN;
BEGIN
 SELECT * INTO STRICT slot FROM public.scheduled_slots WHERE id=slot_id FOR UPDATE;
 SELECT * INTO STRICT scan FROM public.scans WHERE scheduled_slot_id=slot_id AND company_id=company AND scheduled_attempt=worker_token;
 IF scan.checkpoint_receipt IS NOT NULL THEN RETURN scan.checkpoint_receipt; END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(4801739);
 stamp:=clock_timestamp();
 IF slot.attempt_token IS DISTINCT FROM worker_token OR slot.state<>'running' OR slot.lease_until<=stamp OR slot.deadline_at<=stamp THEN RAISE EXCEPTION 'Scheduled lease lost'; END IF;
 IF scan.status<>'running' OR result->>'status' NOT IN ('ok','empty','error','blocked','unsupported') OR result->>'status' IS NULL THEN RAISE EXCEPTION 'Invalid scheduled result'; END IF;
 -- Only this company's collection data may be written. Never replay application imports or restored feedback.
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(payload->'companies','[]')) r WHERE r->>'id' IS DISTINCT FROM company)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(payload->'jobs','[]')) r WHERE r->>'company_id' IS DISTINCT FROM company)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(payload->'job_events','[]')) e WHERE NOT EXISTS(
   SELECT 1 FROM jsonb_array_elements(coalesce(payload->'jobs','[]')) j WHERE j->>'id'=e->>'job_id')) THEN RAISE EXCEPTION 'Checkpoint company mismatch'; END IF;
 -- Count actual accepted inserts/updates using the same guards as ofir_sync, under its advisory lock.
 SELECT count(*) FILTER(WHERE old.id IS NULL), count(*) FILTER(WHERE old.id IS NOT NULL
   AND j.last_seen_at>=old.last_seen_at AND (coalesce(old.match_version,'')='' OR coalesce(j.match_version,'')<>'')
   AND (to_jsonb(old)-ARRAY['fit','familiar','application_status','personal_note','user_updated_at','first_seen_at']) IS DISTINCT FROM
       ((to_jsonb(j)||jsonb_build_object(
         'match_category',coalesce(j.match_category,old.match_category),
         'match_version',coalesce(j.match_version,old.match_version),
         'match_details',coalesce(j.match_details,old.match_details)))
         -ARRAY['fit','familiar','application_status','personal_note','user_updated_at','first_seen_at']))
 INTO inserted,updated FROM jsonb_populate_recordset(NULL::public.jobs,coalesce(payload->'jobs','[]')) j LEFT JOIN public.jobs old ON old.id=j.id;
 PERFORM public.ofir_sync(jsonb_build_object('companies',coalesce(payload->'companies','[]'),
  'jobs',coalesce(payload->'jobs','[]'),'job_events',coalesce(payload->'job_events','[]')));
 PERFORM public.ofir_link_discoveries();
 SELECT count(*) INTO attempt_count FROM public.scans WHERE scheduled_slot_id=slot_id AND company_id=company;
 is_retryable:=coalesce((result->>'retryable')::boolean,false);
 next_retry:=CASE WHEN is_retryable THEN stamp+make_interval(secs=>greatest(
  CASE WHEN attempt_count=1 THEN 3600 ELSE 10800 END,least(86400,greatest(0,coalesce((result->>'retry_after_seconds')::integer,0))))) END;
 receipt:=jsonb_build_object('inserted',inserted,'updated',updated,'persistence','confirmed','company_id',company,'attempt',worker_token);
 UPDATE public.scans SET finished_at=stamp::text,status=result->>'status',fetched_count=(result->>'fetched_count')::integer,
  eligible_count=(result->>'eligible_count')::integer,new_count=(result->>'new_count')::integer,message=result->>'message',
  retry_kind=CASE WHEN result->>'status' IN ('ok','empty') THEN 'success' WHEN is_retryable THEN 'transient' ELSE 'permanent' END,
  retry_after=next_retry,checkpoint_receipt=receipt WHERE id=scan.id;
 UPDATE public.scheduled_slots SET lease_until=stamp+interval '30 minutes' WHERE id=slot_id;
 RETURN receipt;
END;
$$;

CREATE OR REPLACE FUNCTION public.ofir_finish_scheduled(slot_id TEXT, worker_token TEXT)
RETURNS JSONB LANGUAGE plpgsql SET search_path='' AS $$
DECLARE slot public.scheduled_slots; report JSONB; outcome TEXT;
BEGIN
 SELECT * INTO STRICT slot FROM public.scheduled_slots WHERE id=slot_id FOR UPDATE;
 IF slot.attempt_token IS DISTINCT FROM worker_token THEN RAISE EXCEPTION 'Scheduled lease lost'; END IF;
 IF slot.state IN ('completed','failed','retry_wait') THEN RETURN public.ofir_scheduled_report(slot_id); END IF;
 IF slot.lease_until<=clock_timestamp() THEN RAISE EXCEPTION 'Scheduled lease lost'; END IF;
 report:=public.ofir_scheduled_report(slot_id);
 outcome:=CASE WHEN slot.deadline_at<=clock_timestamp() THEN 'failed'
  WHEN (report->>'pending_retry')::integer>0 THEN 'retry_wait'
  WHEN (report->>'exhausted')::integer>0 OR slot.company_ids IS NULL OR (report->>'selected')::integer=0 THEN 'failed' ELSE 'completed' END;
 UPDATE public.scheduled_slots SET state=outcome,lease_until=NULL,
  finished_at=CASE WHEN outcome IN ('completed','failed') THEN clock_timestamp() END WHERE id=slot_id;
 RETURN public.ofir_scheduled_report(slot_id);
END;
$$;

REVOKE ALL ON FUNCTION public.ofir_scheduled_report(TEXT),public.ofir_claim_scheduled(TEXT,TEXT,TEXT),
 public.ofir_prepare_scheduled(TEXT,TEXT,JSONB),public.ofir_begin_scheduled_company(TEXT,TEXT,TEXT),
 public.ofir_checkpoint_scheduled(TEXT,TEXT,TEXT,JSONB,JSONB),public.ofir_finish_scheduled(TEXT,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ofir_scheduled_report(TEXT),public.ofir_claim_scheduled(TEXT,TEXT,TEXT),
 public.ofir_prepare_scheduled(TEXT,TEXT,JSONB),public.ofir_begin_scheduled_company(TEXT,TEXT,TEXT),
 public.ofir_checkpoint_scheduled(TEXT,TEXT,TEXT,JSONB,JSONB),public.ofir_finish_scheduled(TEXT,TEXT) TO service_role;
