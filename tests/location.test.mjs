import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyLocation } from "../lib/location.ts";

test("Israeli country and city names support the source formats in both languages", () => {
  for (const location of ["Israel", "ישראל", "Haifa District, Israel", "Tel Aviv-Yafo", "Caesarea", "Remote (Israel)", "Yokneam", "Yokne'am", "הרצליה", "תל־אביב", "Be'er Sheva"]) {
    assert.equal(classifyLocation(location), "israel", location);
  }
});

test("foreign countries and known foreign cities remain separate from missing locations", () => {
  for (const location of ["San Jose, California, United States", "US", "U.S.A.", "Bengaluru, Karnataka, India", "Germany/Austria/Switzerland", "Chicago", "Beijing", "Toronto, Ontario, Canada"]) {
    assert.equal(classifyLocation(location), "abroad", location);
  }
});

test("remote, ambiguous, mixed and unrecognized locations require review", () => {
  for (const location of [null, undefined, "", "לא צוין", "Remote", "Worldwide", "Multiple Locations", "Worldwide, including Israel", "EMEA", "EMEA (Israel)", "IL", "CA", "Israel / US", "Haifa or Berlin", "Outside Israel", "Remote, excluding Israel", "מחוץ לישראל", "Unrecognized City"]) {
    assert.equal(classifyLocation(location), "unknown", String(location));
  }
});

test("country and city matches use complete words", () => {
  for (const location of ["Israelite", "Israeli company, location unknown", "Haifaville", "Ramat Gantry", "Australiawide", "RUS", "Business"]) {
    assert.equal(classifyLocation(location), "unknown", location);
  }
});
