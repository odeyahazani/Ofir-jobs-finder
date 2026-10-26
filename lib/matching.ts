import type { Job, MatchCategory, MatchDetails } from "./types";

export const MATCH_VERSION = "ofir-profile-v1";
export const matchLabels: Record<MatchCategory, string> = {
  priority: "בעדיפות גבוהה", review: "שווה בדיקה", gap: "פער בדרישות או במיקוד", unassessed: "טרם הותאמה לפרופיל החדש",
};
export function currentMatch(job: Pick<Job, "match_version" | "match_category">) {
  return job.match_version === MATCH_VERSION && ["priority", "review", "gap"].includes(job.match_category);
}
export function priorityMatch(job: Job) {
  return job.eligible && job.score >= 70 && (!currentMatch(job) || job.match_category === "priority");
}
export function normalizeMatching(row: Record<string, unknown>) {
  let raw: Partial<MatchDetails> = {};
  try { raw = (typeof row.match_details === "string" ? JSON.parse(row.match_details) : row.match_details) || {}; } catch { /* Older rows have no assessment metadata. */ }
  const category = String(row.match_category || "unassessed");
  return {
    match_category: (["priority", "review", "gap"].includes(category) ? category : "unassessed") as MatchCategory,
    match_version: String(row.match_version || ""),
    match_details: {
      evidence: Array.isArray(raw.evidence) ? raw.evidence : [], requirements: Array.isArray(raw.requirements) ? raw.requirements : [],
      blockers: Array.isArray(raw.blockers) ? raw.blockers : [], checks: Array.isArray(raw.checks) ? raw.checks : [],
    },
  };
}
