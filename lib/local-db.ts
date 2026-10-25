import "server-only";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import path from "node:path";
import companies from "@/data/companies.json";
import type { Company, Job } from "./types";
import type { Discovery } from "./types";
import type { GrowthPayload } from "./discovery";
import { createHash } from "node:crypto";

let connection: DatabaseSync | undefined;
function database() {
  if (connection) return connection;
  const filename = process.env.OFIR_DB_PATH || path.join(process.cwd(), ".local/ofir.sqlite");
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  const db = new DatabaseSync(filename);
  db.exec("PRAGMA busy_timeout=15000");
  db.exec(fs.readFileSync(path.join(process.cwd(), "data/schema.sql"), "utf8"));
  db.exec("BEGIN");
  try {
    for (const company of companies) {
      const keys = Object.keys(company);
      const statement = db.prepare(`INSERT OR IGNORE INTO companies (${keys.join(",")}) VALUES (${keys.map(() => "?").join(",")})`);
      statement.run(...Object.values(company).map(value => typeof value === "boolean" ? Number(value) : value));
    }
    db.exec("COMMIT");
  } catch (error) {
    db.exec("ROLLBACK");
    db.close();
    throw error;
  }
  connection = db;
  return db;
}

export function listJobs(): Job[] {
  const rows = database().prepare(`SELECT j.*, c.name AS company FROM jobs j JOIN companies c ON c.id=j.company_id
    ORDER BY (j.score / 10) DESC, j.published_at DESC, j.first_seen_at DESC, j.id`).all();
  return rows.map(row => ({ ...row, eligible: Boolean(row.eligible), familiar: Boolean(row.familiar),
    breakdown: JSON.parse(String(row.breakdown)), reasons: JSON.parse(String(row.reasons)), gaps: JSON.parse(String(row.gaps)),
  })) as Job[];
}

export function listCompanies(): Company[] {
  return database().prepare("SELECT * FROM companies ORDER BY enabled DESC, name COLLATE NOCASE").all().map(row => ({ ...row, enabled: Boolean(row.enabled) })) as Company[];
}

export function updateJob(id: string, patch: Record<string, string | number>) {
  const fields = ["fit", "familiar", "application_status", "personal_note"];
  const entries = Object.entries(patch).filter(([key]) => fields.includes(key));
  if (!entries.length) return false;
  return database().prepare(`UPDATE jobs SET ${entries.map(([key]) => `${key}=?`).join(",")}, user_updated_at=? WHERE id=?`)
    .run(...entries.map(([, value]) => value), new Date().toISOString(), id).changes > 0;
}

export function listDiscoveries(): Discovery[] {
  return database().prepare("SELECT * FROM job_discoveries ORDER BY added_at DESC,id").all().map(row => ({ ...row })) as Discovery[];
}
export function importDiscoveries(payload: GrowthPayload) {
  const db = database(); let companiesAdded = 0, jobsAdded = 0;
  db.exec("BEGIN");
  try {
    for (const c of [...payload.companies, ...payload.jobs.map(j => ({ name: j.company, career_url: "", location: "", notes: "" }))]) {
      const existing = db.prepare("SELECT id,career_url FROM companies WHERE lower(trim(name))=lower(?) ORDER BY id LIMIT 1").get(c.name);
      const greenhouse = c.career_url.match(/^https:\/\/(?:job-boards(?:\.eu)?|boards)\.greenhouse\.io\/([^/?]+)/);
      const ats = greenhouse ? "Greenhouse" : /^https:\/\/(?:www\.)?comeet\.(?:com|co)\/jobs\//.test(c.career_url) ? "Comeet" : "Generic HTML";
      if (existing) {
        if (!existing.career_url && c.career_url) db.prepare("UPDATE companies SET career_url=?,ats_hint=?,ats_identifier=? WHERE id=?").run(c.career_url, ats, greenhouse?.[1] || "", String(existing.id));
        continue;
      }
      const id = createHash("md5").update(c.name.toLowerCase()).digest("hex").slice(0, 16);
      companiesAdded += Number(db.prepare(`INSERT OR IGNORE INTO companies(id,name,location_hint,suggested_url,career_url,ats_hint,ats_identifier,imported_active,imported_priority,imported_last_checked,imported_last_result,notes,enabled)
        VALUES(?,?,?,?,?,?,?,0,'Medium','','',?,0)`).run(id, c.name, c.location, c.career_url, c.career_url, ats, greenhouse?.[1] || "", c.notes).changes);
    }
    for (const job of payload.jobs) {
      const company = db.prepare("SELECT id FROM companies WHERE lower(trim(name))=lower(?) ORDER BY id LIMIT 1").get(job.company)!;
      const id = createHash("md5").update(job.url).digest("hex").slice(0, 24);
      jobsAdded += Number(db.prepare("INSERT OR IGNORE INTO job_discoveries(id,company_id,company_name,title,url,location_hint,notes,added_at) VALUES(?,?,?,?,?,?,?,?)")
        .run(id, String(company.id), job.company, job.title, job.url, job.location, job.notes, new Date().toISOString()).changes);
    }
    db.exec("COMMIT");
  } catch (error) { db.exec("ROLLBACK"); throw error; }
  return { companies_added: companiesAdded, jobs_added: jobsAdded };
}
export function setMonitor(id: string, enabled: boolean) {
  const db = database();
  const company = db.prepare("SELECT career_url FROM companies WHERE id=?").get(id);
  if (!company) throw new Error("החברה לא נמצאה");
  if (enabled && !company.career_url) throw new Error("יש להוסיף קישור קריירה לפני הפעלת מעקב");
  db.exec("BEGIN");
  try {
    db.prepare("UPDATE companies SET enabled=? WHERE id=?").run(Number(enabled), id);
    db.prepare("INSERT INTO company_monitor_controls(company_id,opted_out) VALUES(?,?) ON CONFLICT(company_id) DO UPDATE SET opted_out=excluded.opted_out").run(id, Number(!enabled));
    db.exec("COMMIT");
  } catch (error) { db.exec("ROLLBACK"); throw error; }
}
