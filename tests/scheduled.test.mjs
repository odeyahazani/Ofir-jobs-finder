import { before, beforeEach, after, test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { PGlite } from '@electric-sql/pglite';

const db = new PGlite();
const token = 'worker-token-00000001', other = 'worker-token-00000002';
let companies;
const sql = fs.readFileSync('supabase/upgrade-scheduling.sql', 'utf8');
async function rpc(name, args = []) {
  return (await db.query(`SELECT public.${name}(${args.map((_, i) => '$' + (i + 1)).join(',')}) AS value`, args)).rows[0].value;
}
async function claim(t = token) { return rpc('ofir_claim_scheduled', [t, 'test-run', 'fixture-sha']); }
async function report(id = 'test/morning') { return rpc('ofir_scheduled_report', [id]); }
async function fixture(id = 'test/morning', selected = [companies[0].id], target = '-2 hours') {
  await db.query(`INSERT INTO public.scheduled_slots(id,local_day,slot_name,target_at,deadline_at,company_ids)
    VALUES($1,$2,'morning',clock_timestamp()+$3::interval,clock_timestamp()+interval '22 hours',$4::jsonb)`,
  [id, id === 'test/morning' ? '2000-01-01' : '2000-01-02', target, selected === null ? null : JSON.stringify(selected)]);
}
async function begin(company = companies[0].id, id = 'test/morning', t = token) {
  return rpc('ofir_begin_scheduled_company', [id, t, company]);
}
async function checkpoint(status = 'ok', retryable = false, payload = {}, company = companies[0].id, t = token) {
  return rpc('ofir_checkpoint_scheduled', ['test/morning', t, company,
    { status, retryable, fetched_count: 0, new_count: 0, eligible_count: 0, message: 'fixture' }, payload]);
}
const job = company => ({id: 'scheduled-fixture', company_id: company, source_id: 'fixture', title: 'Fixture', location: 'Haifa',
 work_model: '', url: 'https://example.com/scheduled-fixture', description: 'Fixture description', published_at: null, updated_at: null,
 first_seen_at: '2026-01-01T00:00:00+00:00', last_seen_at: '2026-01-01T00:00:00+00:00', last_verified_at: '2026-01-01T00:00:00+00:00',
 status: 'open', score: 70, breakdown: '{}', reasons: '[]', gaps: '[]', experience: '', eligible: 1, exclusion_reason: null,
 content_hash: 'fixture', version: 1, fit: 'unrated', familiar: 0, application_status: 'not_applied', personal_note: '', user_updated_at: null,
 match_category: 'review', match_version: 'fixture', match_details: '{}'});

before(async () => {
 await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
 CREATE SCHEMA auth; CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT NULL::uuid $$;
 CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$;`);
 await db.exec(fs.readFileSync('supabase/setup.sql','utf8').replaceAll('REPLACE_WITH_OFIR_GOOGLE_EMAIL','owner@example.com'));
 companies = (await db.query('SELECT * FROM companies ORDER BY id LIMIT 3')).rows;
});
beforeEach(async () => {
 await db.exec('DELETE FROM job_events; DELETE FROM job_discoveries; DELETE FROM jobs; DELETE FROM scans; DELETE FROM scheduled_slots; DELETE FROM company_monitor_controls; UPDATE companies SET enabled=0;');
 await db.query('UPDATE companies SET enabled=1 WHERE id=ANY($1::text[])', [companies.map(c => c.id)]);
 // Mark real civil targets complete so fixture scheduling tests are independent of wall-clock hour.
 for (const t of [token, other, 'worker-token-00000003', 'worker-token-00000004']) {
  const c = await claim(t);
  if (c.outcome === 'claimed') await db.query("UPDATE scheduled_slots SET state='completed',lease_until=NULL WHERE id=$1", [c.slot.id]);
 }
});
after(async () => db.close());

test('additive migration is repeatable and browser roles cannot use scheduling RPCs', async () => {
 await db.exec(sql); await db.exec(sql);
 await db.exec('SET ROLE authenticated');
 try { await assert.rejects(claim(), /permission denied/); await assert.rejects(db.query('SELECT * FROM scheduled_slots'), /permission denied/); }
 finally { await db.exec('RESET ROLE'); }
 await db.exec('SET ROLE service_role');
 try { assert.equal((await claim()).outcome, 'skipped'); } finally { await db.exec('RESET ROLE'); }
});

test('delayed slot claims are atomic/idempotent; concurrent callers have one owner', async () => {
 await fixture();
 const results = await Promise.all([claim(), claim(other)]);
 assert.equal(results.filter(r => r.outcome === 'claimed').length, 1);
 assert.equal(results.find(r => r.outcome === 'skipped').reason, 'lease_owned');
 const original = results.find(r => r.outcome === 'claimed');
 const owner = original.slot.attempt_token;
 assert.equal((await claim(owner)).slot.claims, 1);
});

test('selection freezes at 20 and prepare replay cannot expand twice', async () => {
 await fixture('test/morning', null); await db.exec('UPDATE companies SET enabled=1'); await claim();
 const first = await rpc('ofir_prepare_scheduled',['test/morning', token, []]);
 assert.equal(first.selected, 20); assert.equal(first.deferred_count, 118);
 await db.exec('UPDATE companies SET last_checked=clock_timestamp()::text');
 const second = await rpc('ofir_prepare_scheduled',['test/morning', token, [companies[0].id]]);
 assert.deepEqual(second.company_ids, first.company_ids);
});

test('successful company remains checked while failed sources wait for bounded backoff', async () => {
 await fixture('test/morning', companies.slice(0,2).map(c=>c.id)); await claim();
 await begin(); await checkpoint();
 await begin(companies[1].id); await checkpoint('error',true,{},companies[1].id);
 let r = await rpc('ofir_finish_scheduled',['test/morning',token]);
 assert.equal(r.state,'retry_wait'); assert.equal(r.checked,1); assert.equal(r.pending_retry,1);
 assert.equal(r.source_failures,1); assert.equal(r.companies[1].state,'pending_retry');
 assert.ok(Date.parse(r.companies[1].retry_at) >= Date.now()+3500_000);
 assert.equal((await claim(other)).outcome,'skipped');
 await db.exec("UPDATE scans SET retry_after=clock_timestamp()-interval '1 second'");
 await claim(other);
 assert.equal((await begin(companies[0].id,'test/morning',other)).status,'skipped');
 await begin(companies[1].id,'test/morning',other); await checkpoint('error',true,{},companies[1].id,other);
 r = await report();
 assert.ok(Date.parse(r.companies[1].retry_at) >= Date.now()+10700_000);
 await rpc('ofir_finish_scheduled',['test/morning',other]);
 await db.exec("UPDATE scans SET retry_after=clock_timestamp()-interval '1 second'");
 const third='worker-token-00000003'; await claim(third); await begin(companies[1].id,'test/morning',third);
 await checkpoint('error',true,{},companies[1].id,third);
 r = await rpc('ofir_finish_scheduled',['test/morning',third]);
 assert.equal(r.state,'failed'); assert.equal(r.exhausted,1); assert.equal(r.checked,1);
});

test('unsupported/restricted sources exhaust without automatic retries', async () => {
 await fixture(); await claim(); await begin(); await checkpoint('blocked');
 const r=await rpc('ofir_finish_scheduled',['test/morning',token]);
 assert.equal(r.state,'failed'); assert.equal(r.exhausted,1);
 assert.equal((await claim(other)).outcome,'skipped');
});

test('lease takeover rejects stale checkpoints and marks abandoned source attempts', async () => {
 await fixture(); await claim(); await begin();
 await db.exec("UPDATE scheduled_slots SET lease_until=clock_timestamp()-interval '1 second' WHERE id='test/morning'");
 // First recovery records abandonment/backoff rather than instantly refetching.
 assert.equal((await claim(other)).outcome,'skipped');
 assert.equal((await report()).companies[0].attempts,1);
 await db.exec("UPDATE scans SET retry_after=clock_timestamp()-interval '1 second'");
 await claim(other); await begin(companies[0].id,'test/morning',other);
 await assert.rejects(checkpoint(), /lease lost/);
 await assert.rejects(rpc('ofir_prepare_scheduled',['test/morning',token,[]]), /lease lost/);
 await checkpoint('ok',false,{},companies[0].id,other);
 assert.equal((await rpc('ofir_finish_scheduled',['test/morning',other])).state,'completed');
});

test('checkpoint replay resolves lost acknowledgements and completion is idempotent', async () => {
 await fixture(); await claim(); await begin();
 const data={jobs:[job(companies[0].id)]};
 const receipt=await checkpoint('ok',false,data);
 assert.equal(receipt.inserted,1);
 assert.deepEqual(await checkpoint('ok',false,data),receipt);
 assert.equal((await db.query('SELECT count(*)::int AS n FROM jobs')).rows[0].n,1);
 const first=await rpc('ofir_finish_scheduled',['test/morning',token]);
 assert.equal(first.state,'completed'); assert.equal(first.jobs_inserted,1);
 assert.deepEqual(await rpc('ofir_finish_scheduled',['test/morning',token]),first);
});

test('checkpoint transaction rollback leaves no jobs or success acknowledgement', async () => {
 await fixture(); await claim(); await begin();
 const invalid={...job(companies[0].id),score:999};
 await assert.rejects(checkpoint('ok',false,{jobs:[invalid]}), /check constraint/);
 assert.equal((await db.query('SELECT count(*)::int AS n FROM jobs')).rows[0].n,0);
 assert.equal((await report()).companies[0].source_status,'running');
 assert.equal((await db.query('SELECT checkpoint_receipt FROM scans')).rows[0].checkpoint_receipt,null);
});

test('checkpoint preserves feedback/application history and rejects unrelated company payloads', async () => {
 const original={...job(companies[0].id),fit:'yes',familiar:1,application_status:'interviewing',personal_note:'הערה אישית',user_updated_at:'2026-01-02'};
 await rpc('ofir_sync',[{jobs:[original],imports:[{canonical_url:original.url,application_status:'applied',applied_at:'2025-12-31',imported_at:'2026-01-01'}]}]);
 await fixture(); await claim(); await begin();
 await assert.rejects(checkpoint('ok',false,{jobs:[job(companies[1].id)]}),/company mismatch/);
 const changed={...job(companies[0].id),title:'Updated',last_seen_at:'2026-02-01T00:00:00+00:00'};
 const receipt=await checkpoint('ok',false,{jobs:[changed],imports:[{canonical_url:original.url,application_status:'withdrawn'}]});
 assert.equal(receipt.updated,1);
 const stored=(await db.query('SELECT * FROM jobs')).rows[0];
 for (const key of ['fit','familiar','application_status','personal_note','user_updated_at','first_seen_at','last_verified_at','match_version','score']) assert.equal(stored[key],original[key],key);
 assert.equal((await db.query('SELECT application_status FROM imports')).rows[0].application_status,'applied');
});

test('new initial slot wins over old ready retries and expired slots are explicit', async () => {
 await fixture(); await claim(); await begin(); await checkpoint('error',true);
 await rpc('ofir_finish_scheduled',['test/morning',token]);
 await db.exec("UPDATE scans SET retry_after=clock_timestamp()-interval '1 second'");
 await fixture('test/new',null,'-1 hour');
 assert.equal((await claim(other)).slot.id,'test/new');
 await db.exec("UPDATE scheduled_slots SET lease_until=NULL,deadline_at=clock_timestamp()-interval '1 second' WHERE state<>'completed'");
 const r=await claim('worker-token-00000003');
 assert.equal(r.outcome,'skipped'); assert.equal(r.expired_slots.length,2);
 assert.equal((await report()).state,'failed');
});

test('pause after freezing selection waives rather than falsely counts as checked', async () => {
 await fixture(); await claim(); await db.query('UPDATE companies SET enabled=0 WHERE id=$1',[companies[0].id]);
 assert.equal((await begin()).status,'skipped');
 const r=await rpc('ofir_finish_scheduled',['test/morning',token]);
 assert.equal(r.waived,1); assert.equal(r.checked,0); assert.equal(r.state,'completed');
});

test('SQL civil targets follow Israeli DST and elapsed 24h deadlines', async () => {
 const r=await db.query(`SELECT '2026-10-24 08:17'::timestamp AT TIME ZONE 'Asia/Jerusalem' AS summer,
 '2026-10-25 08:17'::timestamp AT TIME ZONE 'Asia/Jerusalem' AS winter`);
 assert.equal(r.rows[0].summer.toISOString(),'2026-10-24T05:17:00.000Z');
 assert.equal(r.rows[0].winter.toISOString(),'2026-10-25T06:17:00.000Z');
});

test('two exhausted slots impose cooldown, then only one recovery probe', async () => {
 // Prior source history is reused; no independent retry table is populated.
 for (const [id,day,hours] of [['old/1','1999-12-30',-5],['old/2','1999-12-31',-4]]) {
  await db.query(`INSERT INTO scheduled_slots(id,local_day,slot_name,target_at,deadline_at,state,company_ids)
   VALUES($1,$2,'morning',clock_timestamp()+make_interval(hours=>$3),clock_timestamp()+interval '20 hours','failed',$4)`,[id,day,hours,JSON.stringify([companies[0].id])]);
  for (let n=0;n<3;n++) await db.query(`INSERT INTO scans(company_id,started_at,finished_at,status,scheduled_slot_id,scheduled_attempt,retry_kind)
    VALUES($1,(clock_timestamp()-make_interval(secs=>$4))::text,clock_timestamp()::text,'error',$2,$3,'transient')`,[companies[0].id,id,`old-${id}-${n}`, n+1+Math.abs(hours)*3600]);
 }
 await fixture(); const cooling=await claim(); assert.equal(cooling.outcome,'skipped');
 let r=await report(); assert.equal(r.companies[0].state,'exhausted');
 // Cooldown is later than this slot's recovery deadline: do not call that completion.
 assert.equal(r.state,'failed');
 await db.exec("UPDATE scans SET finished_at=(clock_timestamp()-interval '25 hours')::text WHERE scheduled_slot_id LIKE 'old/%'; UPDATE scheduled_slots SET state='retry_wait' WHERE id='test/morning'");
 await claim(other); await begin(companies[0].id,'test/morning',other); await checkpoint('error',true,{},companies[0].id,other);
 r=await rpc('ofir_finish_scheduled',['test/morning',other]); assert.equal(r.state,'failed'); assert.equal(r.exhausted,1);
});

test('claim limit cannot strand a cancelled slot forever', async () => {
 await fixture(); await db.exec("UPDATE scheduled_slots SET claims=24 WHERE id='test/morning'");
 const c=await claim(); assert.ok(c.expired_slots.includes('test/morning'));
 const r=await report(); assert.equal(r.state,'failed'); assert.equal(r.reason,'claim_limit_exceeded');
});

test('checkpoint updates count excludes untouched jobs and stale snapshots', async () => {
 const original=job(companies[0].id);
 await rpc('ofir_sync',[{jobs:[original]}]); await fixture(); await claim(); await begin();
 const r=await checkpoint('ok',false,{jobs:[original]}); assert.equal(r.updated,0); assert.equal(r.inserted,0);
});

test('cancellation after last checkpoint recovers completion even after the deadline', async () => {
 await fixture(); await claim(); await begin(); await checkpoint();
 await db.exec("UPDATE scheduled_slots SET lease_until=clock_timestamp()-interval '1 second',deadline_at=clock_timestamp()-interval '1 second' WHERE id='test/morning'");
 const c=await claim(other); assert.ok(!c.expired_slots.includes('test/morning'));
 const r=await report(); assert.equal(r.state,'completed'); assert.equal(r.reason,'completion_recovered');
});

test('migration preserves existing job/user history byte-for-byte', async () => {
 const original={...job(companies[0].id),fit:'yes',personal_note:'לשמור',application_status:'applied'};
 await rpc('ofir_sync',[{jobs:[original]}]);
 const before=(await db.query('SELECT * FROM jobs')).rows;
 const owner=(await db.query('SELECT * FROM private.ofir_owner')).rows;
 await db.exec(sql); await db.exec(sql);
 assert.deepEqual((await db.query('SELECT * FROM jobs')).rows,before);
 assert.deepEqual((await db.query('SELECT * FROM private.ofir_owner')).rows,owner);
});

test('missed events older than recovery horizon are recorded as failed, never fetched', async () => {
 await db.exec('DELETE FROM scans; DELETE FROM scheduled_slots;');
 await db.exec(`INSERT INTO scheduled_slots(id,local_day,slot_name,target_at,deadline_at,state)
 VALUES('last-seen',(clock_timestamp() AT TIME ZONE 'Asia/Jerusalem')::date-3,'evening',
 clock_timestamp()-interval '3 days',clock_timestamp()-interval '2 days','completed')`);
 const c=await claim();
 assert.ok(c.expired_slots.length>=2);
 const expired=(await db.query("SELECT * FROM scheduled_slots WHERE reason='recovery_deadline_exceeded'")).rows;
 assert.ok(expired.every(s=>s.state==='failed' && s.claims===0));
});
