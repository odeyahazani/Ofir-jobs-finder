import { before, after, test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "@electric-sql/pglite";

const db = new PGlite();
const owner = "ofir-test@example.com";
const stamp = "2026-10-22T12:00:00+00:00";
let company;
const job = { id: "abcdef000000000000000001", company_id: "", source_id: "test-only", title: "TEST ONLY Integration Engineer", location: "Haifa, Israel", work_model: "לא צוין", url: "https://example.com/test-job", description: "Fixture, not a real job", published_at: null, updated_at: null, first_seen_at: stamp, last_seen_at: stamp, last_verified_at: stamp, status: "open", score: 80, breakdown: "{}", reasons: "[]", gaps: "[]", experience: "0–2", eligible: 1, exclusion_reason: null, content_hash: "test-hash", version: 1, fit: "unrated", familiar: 0, application_status: "not_applied", personal_note: "", user_updated_at: null };

async function as(role, email, callback, provider = "google") {
  await db.query("SELECT set_config('request.jwt.claims',$1,false)", [JSON.stringify(email ? { email, sub: "00000000-0000-0000-0000-000000000001", app_metadata: { provider } } : {})]);
  await db.exec(`SET ROLE ${role}`);
  try { return await callback(); } finally { await db.exec("RESET ROLE"); }
}
async function sync(payload) {
  return as("service_role", null, () => db.query("SELECT public.ofir_sync($1::jsonb)", [JSON.stringify(payload)]));
}

before(async () => {
  await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
    CREATE SCHEMA auth; GRANT USAGE ON SCHEMA auth TO PUBLIC;
    CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql AS $$ SELECT coalesce(nullif(current_setting('request.jwt.claims',true),''),'{}')::jsonb $$;
    CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT (auth.jwt()->>'sub')::uuid $$;`);
  const setup = fs.readFileSync("supabase/setup.sql", "utf8").replaceAll("REPLACE_WITH_OFIR_GOOGLE_EMAIL", owner);
  try { await db.exec(setup); } catch (error) { throw new Error(error.message); }
  company = (await db.query("SELECT * FROM public.companies ORDER BY id LIMIT 1")).rows[0];
  job.company_id = company.id;
  await sync({ jobs: [job], job_events: [{ job_id: job.id, version: 1, kind: "new", created_at: stamp, notified_at: null }] });
});
after(async () => { await db.close(); });

test("setup seeds 138 companies and can be reapplied without losing data", async () => {
  const setup = fs.readFileSync("supabase/setup.sql", "utf8").replaceAll("REPLACE_WITH_OFIR_GOOGLE_EMAIL", owner);
  await db.exec(setup);
  assert.equal((await db.query("SELECT COUNT(*)::int AS n FROM public.companies")).rows[0].n, 138);
  assert.equal((await db.query("SELECT COUNT(*)::int AS n FROM public.jobs")).rows[0].n, 1);
});

test("anonymous role has no direct table access and cannot invoke worker operations", async () => {
  await as("anon", null, async () => {
    await assert.rejects(db.query("SELECT * FROM public.jobs"), /permission denied/);
    await assert.rejects(db.query("SELECT public.ofir_sync('{}')"), /permission denied/);
  });
});

test("all application tables, including the private allowlist, explicitly enable RLS", async () => {
  const result = await db.query(`SELECT n.nspname,c.relname,c.relrowsecurity FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE (n.nspname='public' AND c.relname IN ('companies','jobs','scans','job_events','imports','digest_runs'))
       OR (n.nspname='private' AND c.relname='ofir_owner')`);
  assert.equal(result.rows.length, 7);
  assert.ok(result.rows.every(row => row.relrowsecurity));
});

test("another authenticated user sees no rows and cannot change feedback or the owner", async () => {
  await as("authenticated", "someone-else@example.com", async () => {
    assert.equal((await db.query("SELECT * FROM public.jobs")).rows.length, 0);
    assert.equal((await db.query("SELECT * FROM public.companies")).rows.length, 0);
    assert.equal((await db.query("UPDATE public.jobs SET fit='yes' RETURNING id")).rows.length, 0);
    await assert.rejects(db.query("SELECT * FROM private.ofir_owner"), /permission denied/);
    await assert.rejects(db.query("SELECT private.configure_owner('someone-else@example.com')"), /permission denied/);
    await assert.rejects(db.query("SELECT public.ofir_reserve_digest('2026-10-22','now')"), /permission denied/);
  });
});

test("Ofir can read and update personal feedback but cannot edit scores or insert jobs", async () => {
  await as("authenticated", owner.toUpperCase(), async () => {
    assert.equal((await db.query("SELECT * FROM public.jobs")).rows.length, 1);
    await db.query("UPDATE public.jobs SET fit='yes',familiar=1,application_status='applied',personal_note='keep my note',user_updated_at=$1 WHERE id=$2", [stamp, job.id]);
    await assert.rejects(db.query("UPDATE public.jobs SET score=100"), /permission denied/);
    await assert.rejects(db.query("DELETE FROM public.jobs"), /permission denied/);
    await assert.rejects(db.query("INSERT INTO public.jobs(id) VALUES('fake')"), /permission denied/);
  });
});

test("an email/password session is rejected even for the allowed email", async () => {
  await as("authenticated", owner, async () => {
    assert.equal((await db.query("SELECT * FROM public.jobs")).rows.length, 0);
  }, "email");
});

test("rescan changes job content, preserves all personal feedback, and deduplicates events", async () => {
  await sync({ jobs: [{ ...job, title: "Updated fixture title", last_seen_at: "2026-10-22T13:00:00+00:00" }], job_events: [{ job_id: job.id, version: 1, kind: "new", created_at: stamp }] });
  const stored = (await db.query("SELECT * FROM public.jobs WHERE id=$1", [job.id])).rows[0];
  assert.equal(stored.title, "Updated fixture title");
  assert.equal(stored.fit, "yes");
  assert.equal(stored.familiar, 1);
  assert.equal(stored.application_status, "applied");
  assert.equal(stored.personal_note, "keep my note");
  assert.equal(stored.first_seen_at, stamp);
  assert.equal((await db.query("SELECT COUNT(*)::int AS n FROM public.job_events")).rows[0].n, 1);
});

test("stale cloud snapshots cannot overwrite newer collected content", async () => {
  await sync({ jobs: [job] });
  assert.equal((await db.query("SELECT title FROM public.jobs")).rows[0].title, "Updated fixture title");
});

test("full snapshot transfer preserves source health, history and original notifications on retry", async () => {
  const payload = { companies: [{ ...company, source_status: "ok", last_checked: stamp, last_result: "Fixture scan", job_count: 1 }],
    scans: [{ company_id: company.id, started_at: stamp, finished_at: stamp, status: "ok", fetched_count: 1, eligible_count: 1, new_count: 1, message: "Fixture scan" }],
    imports: [{ canonical_url: "https://example.com/future-role", application_status: "applied", applied_at: null, imported_at: stamp }],
    digest_runs: [{ day: "2026-10-20", status: "sent", created_at: stamp, sent_at: stamp }] };
  await sync(payload);
  await sync(payload);
  assert.equal((await db.query("SELECT source_status FROM public.companies WHERE id=$1", [company.id])).rows[0].source_status, "ok");
  assert.equal((await db.query("SELECT COUNT(*)::int AS n FROM public.scans")).rows[0].n, 1);
  assert.equal((await db.query("SELECT COUNT(*)::int AS n FROM public.digest_runs WHERE day='2026-10-20'")).rows[0].n, 1);
});

test("cloud digest reservation is durable and confirmation marks the matching version only", async () => {
  await as("service_role", null, async () => {
    assert.equal((await db.query("SELECT public.ofir_reserve_digest('2026-10-22',$1) AS ok", [stamp])).rows[0].ok, true);
    assert.equal((await db.query("SELECT public.ofir_reserve_digest('2026-10-22',$1) AS ok", [stamp])).rows[0].ok, false);
    await db.query("SELECT public.ofir_finish_digest('2026-10-22','sent',$1,$2::jsonb)", [stamp, JSON.stringify([{ job_id: job.id, version: 1 }])]);
  });
  assert.equal((await db.query("SELECT status FROM public.digest_runs WHERE day='2026-10-22'")).rows[0].status, "sent");
  assert.equal((await db.query("SELECT notified_at FROM public.job_events")).rows[0].notified_at, stamp);
});

test("application import is atomic and applies to both existing and future discovery", async () => {
  await as("service_role", null, async () => {
    const records = [{ canonical_url: job.url, application_status: "interviewing", applied_at: null, imported_at: stamp }];
    await db.query("SELECT public.ofir_import_applications($1::jsonb)", [JSON.stringify(records)]);
    await db.query("SELECT public.ofir_import_applications($1::jsonb)", [JSON.stringify(records)]);
    await assert.rejects(db.query("SELECT public.ofir_import_applications($1::jsonb)", [JSON.stringify([...records, { ...records[0], canonical_url: "https://example.com/other", application_status: "bad" }])]), /Invalid import record/);
  });
  assert.equal((await db.query("SELECT application_status FROM public.jobs")).rows[0].application_status, "interviewing");
  assert.equal((await db.query("SELECT COUNT(*)::int AS n FROM public.imports WHERE canonical_url=$1", [job.url])).rows[0].n, 1);
});

test("incomplete owner configuration aborts setup without granting access", async () => {
  await assert.rejects(db.query("SELECT private.configure_owner('REPLACE_WITH_OFIR_GOOGLE_EMAIL')"), /Set a valid Google email/);
  assert.equal((await db.query("SELECT email FROM private.ofir_owner")).rows[0].email, owner);
});
