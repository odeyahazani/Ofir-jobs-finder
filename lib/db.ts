import "server-only";
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import path from "node:path";
import companies from "@/data/companies.json";
import type { Company, Job } from "./types";

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
