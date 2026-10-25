export type GrowthCompany = { name: string; career_url: string; location: string; notes: string };
export type GrowthJob = { company: string; title: string; url: string; location: string; notes: string };
export type GrowthPayload = { companies: GrowthCompany[]; jobs: GrowthJob[] };

export function publicUrl(value: unknown, optional = false): string {
  if (optional && (value === undefined || value === "")) return "";
  if (typeof value !== "string" || value.length > 2000) throw new Error("נדרש קישור HTTPS תקין");
  let url: URL;
  try { url = new URL(value.trim()); } catch { throw new Error("אחד הקישורים אינו תקין"); }
  if (url.protocol !== "https:" || url.username || url.password || url.port ||
    !/^(?:[a-z0-9-]+\.)+[a-z]{2,}$/i.test(url.hostname) || /\.(local|internal|localhost|test|invalid)$/i.test(url.hostname)) {
    throw new Error("הקישורים חייבים להפנות לאתר HTTPS ציבורי");
  }
  url.hash = "";
  for (const key of [...url.searchParams.keys()]) if (/^utm_/i.test(key) || ["source", "ref", "gh_src", "fbclid", "gclid"].includes(key.toLowerCase())) url.searchParams.delete(key);
  url.searchParams.sort();
  url.pathname = url.pathname.replace(/\/+$/, "") || "/";
  return url.toString().replace(/\/$/, "");
}
function text(value: unknown, name: string, maximum: number, required = false) {
  if (value === undefined && !required) return "";
  if (typeof value !== "string" || value.trim().length > maximum || (required && !value.trim())) throw new Error(`השדה ${name} חסר או ארוך מדי`);
  return value.trim();
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("כל ממצא צריך להיות רשומה");
  return value as Record<string, unknown>;
}
export function validateGrowth(value: unknown): GrowthPayload {
  const root = record(value);
  const companies = root.companies ?? [], jobs = root.jobs ?? [];
  if (!Array.isArray(companies) || !Array.isArray(jobs) || companies.length + jobs.length < 1 || companies.length + jobs.length > 100) throw new Error("אפשר לייבא בין ממצא אחד ל־100 ממצאים בכל פעם");
  return {
    companies: companies.map(value => { const c = record(value); return { name: text(c.name, "שם החברה", 200, true), career_url: publicUrl(c.career_url, true), location: text(c.location, "מיקום", 250), notes: text(c.notes, "הערות", 4000) }; }),
    jobs: jobs.map(value => { const j = record(value); return { company: text(j.company, "שם החברה", 200, true), title: text(j.title, "שם המשרה", 250, true), url: publicUrl(j.url), location: text(j.location, "מיקום", 250), notes: text(j.notes, "הערות", 4000) }; }),
  };
}
function csvRows(input: string): string[][] {
  const rows: string[][] = []; let row: string[] = [], field = "", quoted = false;
  for (let i = 0; i < input.length; i++) {
    const ch = input[i];
    if (ch === '"') { if (quoted && input[i + 1] === '"') { field += '"'; i++; } else quoted = !quoted; }
    else if (ch === "," && !quoted) { row.push(field); field = ""; }
    else if ((ch === "\n" || ch === "\r") && !quoted) { if (ch === "\r" && input[i + 1] === "\n") i++; row.push(field); if (row.some(Boolean)) rows.push(row); row = []; field = ""; }
    else field += ch;
  }
  if (quoted) throw new Error("המרכאות בקובץ CSV אינן סגורות");
  row.push(field); if (row.some(Boolean)) rows.push(row);
  return rows;
}
export function parseGrowth(input: string): GrowthPayload {
  if (input.length > 500_000) throw new Error("הקובץ גדול מדי; פצלו למנות של עד 100 ממצאים");
  input = input.trim().replace(/^\uFEFF/, "");
  if (input.startsWith("{")) { try { return validateGrowth(JSON.parse(input)); } catch (error) { if (error instanceof SyntaxError) throw new Error("קובץ JSON אינו תקין"); throw error; } }
  const [headers, ...rows] = csvRows(input);
  if (!headers?.includes("kind") || !headers.includes("company")) throw new Error("CSV צריך לכלול עמודות kind ו־company; אפשר גם להדביק JSON");
  const data: { companies: unknown[]; jobs: unknown[] } = { companies: [], jobs: [] };
  for (const values of rows) {
    const row = Object.fromEntries(headers.map((h, i) => [h.trim(), values[i] || ""]));
    if (row.kind.trim() === "company") data.companies.push({ ...row, name: row.company });
    else if (row.kind.trim() === "job") data.jobs.push(row);
    else throw new Error("kind חייב להיות company או job");
  }
  return validateGrowth(data);
}
