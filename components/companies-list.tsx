"use client";
import { useState } from "react";
import { ExternalLink, Search } from "lucide-react";
import type { Company } from "@/lib/types";
import { MonitorToggle } from "./import-panel";
import { CompanyMark, date, safeLink } from "./job-ui";
const labels: Record<string, string> = { pending: "טרם נבדק", ok: "נסרק בהצלחה", empty: "הרשימה שנבדקה ריקה", blocked: "הגישה חסומה", unsupported: "מקור לא נתמך", error: "שגיאה בבדיקה" };

export default function CompaniesList({ companies, importReady }: { companies: Company[]; importReady: boolean }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const active = companies.filter(c => c.enabled);
  const healthy = active.filter(c => ["ok", "empty"].includes(c.source_status));
  const checked = companies.filter(c => c.last_checked).length;
  const visible = companies.filter(c => `${c.name} ${c.location_hint}`.toLowerCase().includes(query.toLowerCase().trim()) &&
    (filter === "all" || filter === "active" && c.enabled || filter === "disabled" && !c.enabled || filter === "healthy" && ["ok", "empty"].includes(c.source_status) || filter === "attention" && c.enabled && !["ok", "empty"].includes(c.source_status)));
  return <>
    <section className="summary-metrics" aria-label="מצב מקורות">
      <div><strong>{companies.length}</strong><span>חברות במאגר</span></div>
      <div><strong>{active.length}</strong><span>במעקב פעיל</span></div>
      <div><strong>{healthy.length}</strong><span>מקורות פעילים שנסרקו בהצלחה</span></div>
      <div><strong>{active.length - healthy.length}</strong><span>מקורות פעילים לבדיקה</span></div>
    </section>
    <section className="coverage-panel" aria-label="כיסוי החברות">
      <div><strong>מרחיבים את מעגל ההזדמנויות</strong><p>{checked} מתוך {companies.length} חברות נבדקו לפחות פעם אחת. הוספת חברה למאגר אינה מפעילה את הסריקה שלה.</p></div>
      <div className="coverage-progress"><span>{checked} / {companies.length} נבדקו</span><progress aria-label="חברות שנבדקו מתוך המאגר" value={checked} max={companies.length || 1}/></div>
    </section>
    <section className="content-panel">
      <div className="search-controls"><div className="search-row"><Search size={18}/><input dir="auto" aria-label="חיפוש חברות" placeholder="שם החברה או המיקום שלה…" value={query} onChange={e => setQuery(e.target.value)}/></div>
        <label className="select-control">הצגה<select aria-label="סינון חברות" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">כל החברות</option><option value="active">מעקב פעיל</option><option value="disabled">מעקב מושבת</option><option value="healthy">סריקה הצליחה</option><option value="attention">דורשות תשומת לב</option></select></label>
      </div>
      <div className="section-heading"><h2>החברות במאגר <span>{visible.length}</span></h2></div>
      <div className="company-list">{visible.map(c => <article className="company-row" key={c.id}>
        <CompanyMark name={c.name}/>
        <div className="company-info"><h3><bdi>{c.name}</bdi></h3><p><bdi>{c.location_hint || "מיקום לא אומת"}</bdi> · {c.ats_hint || "מקור לא ידוע"}</p><small>בדיקה אחרונה: {date(c.last_checked)}</small></div>
        <div className="company-status"><span className={`badge ${["ok", "empty"].includes(c.source_status) ? "success" : ["error", "blocked"].includes(c.source_status) ? "danger" : "warning"}`}>{labels[c.source_status] || c.source_status}</span><span className="subtle">{c.enabled ? "במעקב פעיל" : "מעקב מושבת"}</span></div>
        {importReady && <MonitorToggle company={c}/>}
        <details><summary>תוצאות ומקור</summary><p dir="auto">{c.last_result || "טרם התקבלה תוצאת סריקה"}</p>{c.career_url && <a href={safeLink(c.career_url)} target="_blank" rel="noreferrer">אתר הקריירה <ExternalLink size={14}/></a>}<p className="subtle">בדיקה היסטורית מהייבוא: {c.imported_last_checked || "לא צוינה"} · {c.imported_last_result || "ללא תוצאה"}</p></details>
      </article>)}{!visible.length && <p className="empty-state">אין חברות שתואמות לסינון.</p>}</div>
    </section>
  </>;
}
