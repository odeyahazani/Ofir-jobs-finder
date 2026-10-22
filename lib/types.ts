export type Fit = "unrated" | "yes" | "maybe" | "no";
export type ApplicationStatus = "not_applied" | "planned" | "applied" | "interviewing" | "rejected" | "withdrawn";
export type Job = {
  id: string; company_id: string; company: string; title: string; location: string;
  work_model: string; url: string; description: string;
  published_at: string | null; updated_at: string | null; first_seen_at: string;
  last_verified_at: string | null; status: string; score: number;
  breakdown: Record<string, number>; reasons: string[]; gaps: string[];
  experience: string; eligible: boolean; exclusion_reason: string | null;
  fit: Fit; familiar: boolean; application_status: ApplicationStatus; personal_note: string;
};
export type Company = {
  id: string; name: string; location_hint: string; career_url: string;
  ats_hint: string; notes: string; enabled: boolean; source_status: string;
  last_checked: string | null; last_result: string; job_count: number | null;
  imported_last_checked: string; imported_last_result: string;
};
