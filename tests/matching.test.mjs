import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { MATCH_VERSION, normalizeMatching, currentMatch, priorityMatch } from "../lib/matching.ts";

test("matching version is shared with the reviewed candidate profile", () => {
  assert.equal(MATCH_VERSION, JSON.parse(fs.readFileSync("data/candidate-profile.json")).version);
});
test("legacy and missing cloud fields remain explicitly unassessed", () => {
  for (const row of [{}, { match_category: null, match_details: null }, { match_category: "bad", match_details: "broken" }]) {
    const job = { ...normalizeMatching(row), eligible: true, score: 80 };
    assert.equal(job.match_category, "unassessed");
    assert.equal(currentMatch(job), false);
    assert.equal(priorityMatch(job), true);
    assert.deepEqual(job.match_details.evidence, []);
  }
});
test("a high score does not turn a review or gap into a priority", () => {
  for (const category of ["review", "gap"]) {
    const job = { ...normalizeMatching({ match_version: MATCH_VERSION, match_category: category }), eligible: true, score: 95 };
    assert.equal(currentMatch(job), true);
    assert.equal(priorityMatch(job), false);
  }
  assert.equal(priorityMatch({ match_category: "priority", match_version: MATCH_VERSION, eligible: false, score: 95 }), false);
  assert.equal(priorityMatch({ match_category: "priority", match_version: MATCH_VERSION, eligible: true, score: 69 }), false);
  assert.equal(priorityMatch({ match_category: "priority", match_version: MATCH_VERSION, eligible: true, score: 80 }), true);
});
