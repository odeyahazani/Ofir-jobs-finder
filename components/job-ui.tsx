import { CircleHelp, CircleMinus, Clock3, ShieldAlert, ShieldCheck, Sparkles } from "lucide-react";
import type { ApplicationStatus, Fit, Job } from "@/lib/types";
import { currentMatch, matchLabels } from "@/lib/matching";
export const applicationLabels: Record<ApplicationStatus, string> = { not_applied: "טרם הגשתי", planned: "מתכנן להגיש", applied: "הגשתי", interviewing: "בתהליך", rejected: "נדחיתי", withdrawn: "ויתרתי" };
export const fitLabels: Record<Fit, string> = { unrated: "טרם דירגתי", yes: "מתאים לי", maybe: "אולי מתאים", no: "לא מתאים" };
export function date(value: string | null) { return !value || !Number.isFinite(Date.parse(value)) ? "לא ידוע" : new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short", timeZone: "Asia/Jerusalem" }).format(new Date(value)); }
export function verifiedRecently(job: Job) { const age = Date.now() - Date.parse(job.last_verified_at || ""); return job.status === "open" && age >= 0 && age < 30 * 3600000; }
export function safeLink(value: string) { try { const url = new URL(value); return url.protocol === "https:" ? url.href : undefined; } catch { return undefined; } }
export function VerificationBadge({ job }: { job: Job }) {
  const fresh = verifiedRecently(job);
  const Icon = fresh ? ShieldCheck : job.status === "closed" ? CircleMinus : job.status === "open" ? Clock3 : ShieldAlert;
  return <span className={`badge ${fresh ? "success" : job.status === "closed" ? "neutral" : "warning"}`}><Icon size={14}/>{fresh ? "אומתה במקור" : job.status === "closed" ? "נסגרה" : job.status === "open" ? "האימות דורש רענון" : "טרם אומתה"}</span>;
}
export function MatchScore({ job }: { job: Job }) { return <div className="match-score"><strong><bdi>{job.score}<small>/100</small></bdi></strong><span>התאמה מקצועית</span></div>; }
export function CompanyMark({ name }: { name: string }) {
  const words = name.trim().split(/\s+/);
  const letters = (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2)).toUpperCase();
  const tone = [...name].reduce((sum, letter) => sum + letter.charCodeAt(0), 0) % 4;
  return <span className="company-avatar" data-tone={tone} aria-hidden="true"><bdi>{letters}</bdi></span>;
}
export function MatchingBadge({ job }: { job: Job }) {
  const category = currentMatch(job) ? job.match_category : "unassessed";
  return <span className={`badge matching-badge ${category === "priority" ? "info" : category === "review" ? "warning" : "neutral"}`}>{category === "priority" ? <Sparkles size={13}/> : category === "review" ? <CircleHelp size={13}/> : null}{matchLabels[category]}</span>;
}
