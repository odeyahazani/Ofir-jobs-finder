import "server-only";
import { supabase } from "./auth";
import type { Company, Job } from "./types";

function storage() {
  const mode = process.env.OFIR_STORAGE || (process.env.NODE_ENV === "production" ? "supabase" : "sqlite");
  if (!["sqlite", "supabase"].includes(mode) || (process.env.VERCEL && mode !== "supabase")) {
    throw new Error("Vercel requires OFIR_STORAGE=supabase");
  }
  return mode;
}

// PostgREST normally caps responses at 1,000 rows; paginate with a stable unique order.
async function remoteRows(table: "jobs" | "companies") {
  const client = await supabase();
  const rows: Record<string, unknown>[] = [];
  let start = 0;
  while (start < 100_000) {
    const { data, error } = await client.from(table).select("*").order("id").range(start, start + 499);
    if (error) throw new Error("לא ניתן לקרוא את הנתונים. יש לבדוק את הגדרת Supabase והרשאות החשבון.");
    if (!data?.length) return rows;
    rows.push(...data);
    start += data.length;
  }
  throw new Error("כמות הנתונים חורגת מהמגבלה הנתמכת.");
}

export async function listCompanies(): Promise<Company[]> {
  if (storage() === "sqlite") return (await import("./local-db")).listCompanies();
  return (await remoteRows("companies")).map(row => ({ ...row, enabled: Boolean(row.enabled) }) as Company)
    .sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.name.localeCompare(b.name));
}

export async function listJobs(): Promise<Job[]> {
  if (storage() === "sqlite") return (await import("./local-db")).listJobs();
  const [rows, companies] = await Promise.all([remoteRows("jobs"), listCompanies()]);
  const names = new Map(companies.map(c => [c.id, c.name]));
  return rows.map(row => ({ ...row, company: names.get(String(row.company_id)) || "",
    eligible: Boolean(row.eligible), familiar: Boolean(row.familiar),
    breakdown: JSON.parse(String(row.breakdown)), reasons: JSON.parse(String(row.reasons)), gaps: JSON.parse(String(row.gaps)),
  }) as Job);
}

export async function updateJob(id: string, patch: Record<string, string | number>) {
  const fields = ["fit", "familiar", "application_status", "personal_note"];
  const safe = Object.fromEntries(Object.entries(patch).filter(([key]) => fields.includes(key)));
  if (!Object.keys(safe).length) return false;
  if (storage() === "sqlite") return (await import("./local-db")).updateJob(id, safe);
  const client = await supabase();
  const { data, error } = await client.from("jobs").update({ ...safe, user_updated_at: new Date().toISOString() }).eq("id", id).select("id");
  if (error) throw new Error("שמירת הסימונים נכשלה. יש לבדוק את החיבור והרשאות החשבון.");
  return Boolean(data?.length);
}
