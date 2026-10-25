import { test } from "node:test";
import assert from "node:assert/strict";
import { parseGrowth, publicUrl, validateGrowth } from "../lib/discovery.ts";

test("shared JSON normalizes links and never accepts supplied verification or score", () => {
  const input = { companies: [{ name: " A ", career_url: "https://example.com/careers/?utm_source=chat#jobs", notes: "medical" }], jobs: [{ company: "A", title: "Test", url: "https://example.com/jobs/1?ref=chat&jobId=2", verified: true, score: 100 }] };
  const parsed = parseGrowth(JSON.stringify(input));
  assert.equal(parsed.companies[0].career_url, "https://example.com/careers");
  assert.equal(parsed.jobs[0].url, "https://example.com/jobs/1?jobId=2");
  assert.equal(parsed.jobs[0].verified, undefined);
  assert.equal(parsed.jobs[0].score, undefined);
});
test("CSV accepts quoted commas and multiple kinds", () => {
  const parsed = parseGrowth('kind,company,career_url,title,url,location,notes\r\ncompany,Acme,https://example.com/careers,,,"Haifa, Israel",medical\r\njob,Acme,,"Test, Engineer",https://example.com/jobs/2,Haifa,"line one\nline two"');
  assert.equal(parsed.companies.length, 1);
  assert.equal(parsed.jobs[0].title, "Test, Engineer");
  assert.match(parsed.jobs[0].notes, /\n/);
});
test("malformed and excessive imports are rejected before writing", () => {
  for (const value of ["{broken", "", "kind,company\nother,Acme", 'kind,company\ncompany,"unfinished']) assert.throws(() => parseGrowth(value));
  assert.throws(() => validateGrowth({ companies: Array(101).fill({ name: "Acme" }) }));
  assert.throws(() => validateGrowth({ jobs: [{ company: "Acme", title: "Test" }] }));
});
test("only public HTTPS URLs without credentials are accepted", () => {
  for (const url of ["http://example.com", "https://127.0.0.1/jobs", "https://[::1]/", "https://localhost/", "https://example.internal", "https://user:pass@example.com", "https://example.com:444"]) assert.throws(() => publicUrl(url));
  assert.equal(publicUrl(undefined, true), "");
});
