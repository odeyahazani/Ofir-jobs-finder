"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { parseGrowth, type GrowthPayload } from "@/lib/discovery";
import type { Company, Discovery } from "@/lib/types";

export function MonitorToggle({ company }: { company: Company }) {
  const [enabled, setEnabled] = useState(company.enabled), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const router = useRouter();
  useEffect(() => { setEnabled(company.enabled); }, [company.enabled]);
  async function change(value: boolean) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/companies/${company.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: value }) });
      if (!response.ok) throw new Error((await response.json()).error);
      setEnabled(value); router.refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "השינוי לא נשמר"); }
    finally { setBusy(false); }
  }
  return <div className="monitor-control"><label><input type="checkbox" checked={enabled} disabled={busy || !company.career_url} aria-label={`מעקב אחר ${company.name}`} onChange={e => change(e.target.checked)} />לכלול בסריקות</label>{error && <small role="alert">{error}</small>}</div>;
}

export default function ImportPanel({ discoveries, available }: { discoveries: Discovery[]; available: boolean }) {
  const [input, setInput] = useState(""), [preview, setPreview] = useState<GrowthPayload | null>(null), [error, setError] = useState(""), [result, setResult] = useState(""), [busy, setBusy] = useState(false);
  const router = useRouter();
  function inspect() {
    setError(""); setResult("");
    try { setPreview(parseGrowth(input)); } catch (e) { setPreview(null); setError(e instanceof Error ? e.message : "קובץ לא תקין"); }
  }
  async function save() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/discoveries", { method: "POST", headers: { "Content-Type": "application/json" }, body: input });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error);
      setResult(`נוספו ${body.companies_added} חברות ו־${body.jobs_added} ממצאי משרות. כפילויות קיימות נשמרו ללא שינוי.`);
      setPreview(null); setInput(""); router.refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "הייבוא לא הושלם"); }
    finally { setBusy(false); }
  }
  return <section className="content-panel import-panel"><div className="section-heading"><div><h2>מגדילים את המאגר</h2><p className="section-description">ממצאים מהחיפוש בצ׳אט או מחיפוש עצמאי, עם אימות לפני המלצה.</p></div></div>
    {!available && <div className="notice">חיבור ייבוא הממצאים עדיין לא הושלם. אפשר להמשיך לצפות במשרות ובחברות הקיימות.</div>}
    <div className="import-body"><p>הדביקו JSON או העלו CSV/JSON. חברות חדשות מתווספות למאגר; אפשר להפעיל להן מעקב במסך החברות. משרות שמגיעות מבחוץ נשמרות כממתינות לאימות.</p>
    <label className="file-input">בחירת קובץ<input type="file" accept=".json,.csv,application/json,text/csv" aria-label="בחירת קובץ ממצאים" disabled={!available || busy} onChange={async e => {
      const file = e.target.files?.[0]; if (!file) return;
      if (file.size > 500_000) { setPreview(null); setError("הקובץ גדול מדי"); return; }
      setInput(await file.text()); setPreview(null); setError("");
    }} /></label>
    <label>תוכן הממצאים<textarea dir="ltr" aria-label="תוכן הממצאים" value={input} maxLength={500_000} disabled={!available || busy} onChange={e => { setInput(e.target.value); setPreview(null); }} placeholder={'{"companies": [], "jobs": []}'} /></label>
    <details><summary>מה צריך להופיע בקובץ?</summary><p dir="auto">ב־JSON: מערך companies עם name, career_url, location, notes; ומערך jobs עם company, title, url, location, notes. ב־CSV: כותרות kind,company,career_url,title,url,location,notes, כאשר kind הוא company או job.</p><p>שם חברה וקישור קריירה עוזרים לסורק לבדוק אותה. משרה חייבת לכלול חברה, שם וקישור ספציפי. תאריך פרסום וציון אינם מוסקים מטקסט מיובא.</p></details>
    <button className="secondary-button" disabled={!available || busy || !input.trim()} onClick={inspect}>בדיקת הממצאים לפני ייבוא</button>
    {preview && <div className="import-preview"><strong>ייבוא של {preview.companies.length} חברות ו־{preview.jobs.length} ממצאי משרות</strong><ul>{preview.companies.map((c,i) => <li key={`c${i}`}>{c.name} · {c.career_url || "דרוש קישור קריירה"}</li>)}{preview.jobs.map((j,i) => <li key={`j${i}`}>{j.company} · {j.title}</li>)}</ul><button className="primary-button" disabled={busy} onClick={save}>{busy ? "מייבא…" : "אישור ייבוא למאגר"}</button></div>}
    {error && <p role="alert" className="error">{error}</p>}{result && <p role="status" className="notice">{result}</p>}
    <h3>ממצאי משרות שיובאו <span>({discoveries.length})</span></h3>
    {!discoveries.length && <p className="subtle">עדיין לא יובאו ממצאים חיצוניים.</p>}
    {discoveries.map(d => <article className="discovery-row" key={d.id}><strong dir="auto">{d.company_name} · {d.title}</strong><span className={`source-badge ${d.status === "linked" ? "ok" : "pending"}`}>{d.status === "linked" ? "קושרה למשרה במאגר" : "ממתינה לאימות"}</span><p>{d.last_result}</p><a href={d.url} target="_blank" rel="noreferrer">פתיחת המקור שצורף</a></article>)}
    </div></section>;
}
