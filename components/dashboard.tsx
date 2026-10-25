"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpLeft, BriefcaseBusiness, Building2, CheckCheck, ExternalLink, LayoutGrid, Search, ShieldCheck, Sparkles, X } from "lucide-react";
import type { ApplicationStatus, Company, Discovery, Fit, Job } from "@/lib/types";
import { classifyLocation, type JobRegion } from "@/lib/location";

import ImportPanel from "./import-panel";
import CompaniesList from "./companies-list";
import { JobCard, ApplicationTracker } from "./job-views";
import { applicationLabels, fitLabels, date, verifiedRecently, safeLink } from "./job-ui";

const breakdownLabels: Record<string, string> = { professional: "משימות התפקיד", experience: "רמת ניסיון", technical: "כישורים טכניים", sector: "תחום החברה", location: "מיקום ונסיעה", growth: "התפתחות" };
const maximums: Record<string, number> = { professional: 30, experience: 25, technical: 20, sector: 10, location: 10, growth: 5 };
function isFresh(job: Job) { const age = Date.now() - Date.parse(job.first_seen_at); return age >= 0 && age < 86400000; }

export default function Dashboard({ jobs: initialJobs, companies, discoveries, importReady, local }: { jobs: Job[]; companies: Company[]; discoveries: Discovery[]; importReady: boolean; local: boolean }) {
  const [jobs, setJobs] = useState(initialJobs);
  const [tab, setTab] = useState("jobs");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("recommended");
  const [region, setRegion] = useState<JobRegion | "all">("israel");
  const [sort, setSort] = useState("fit");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [note, setNote] = useState("");
  const [applicationFilter, setApplicationFilter] = useState("all");
  useEffect(() => { setJobs(initialJobs); }, [initialJobs]);
  const savingRef = useRef(false);
  const openerRef = useRef<HTMLElement | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!selectedId) return;
    const dialog = dialogRef.current;
    dialog?.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { dialog?.close(); document.body.style.overflow = previous; openerRef.current?.focus(); };
  }, [selectedId]);
  const locatedJobs = useMemo(() => jobs.map(job => ({ ...job, region: classifyLocation(job.location) })), [jobs]);
  const regionCounts = { israel: 0, abroad: 0, unknown: 0 };
  for (const job of locatedJobs) regionCounts[job.region]++;
  const recommended = locatedJobs.filter(j => j.region === "israel" && j.eligible && verifiedRecently(j) && j.score >= 70 && j.fit !== "no" && j.application_status === "not_applied");
  const selected = jobs.find(j => j.id === selectedId);
  const visible = useMemo(() => {
    const filtered = locatedJobs.filter(job => {
      const matchesQuery = `${job.title} ${job.company} ${job.location}`.toLowerCase().includes(query.toLowerCase());
      const matchesTab = tab !== "applications" || (job.application_status !== "not_applied" && (applicationFilter === "all" || job.application_status === applicationFilter));
      const matchesRegion = tab === "applications" || region === "all" || job.region === region;
      const matchesFilter = tab === "applications" || (filter === "recommended" ? job.region === "israel" && job.eligible && verifiedRecently(job) && job.score >= 70 && job.fit !== "no" && job.application_status === "not_applied" :
        filter === "new" ? isFresh(job) && !job.familiar && job.eligible && job.status === "open" :
        filter === "saved" ? job.fit === "yes" || job.application_status === "planned" : true);
      return matchesQuery && matchesTab && matchesRegion && matchesFilter;
    });
    return filtered.sort((a, b) => sort === "newest" ? (Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at)) :
      b.score - a.score || (Date.parse(b.published_at || "") || 0) - (Date.parse(a.published_at || "") || 0) || Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at));
  }, [locatedJobs, query, filter, region, sort, tab, applicationFilter]);

  async function update(job: Job, patch: Partial<Pick<Job, "fit" | "familiar" | "application_status" | "personal_note">>) {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true); setError(""); setSaveMessage("");
    setJobs(current => current.map(j => j.id === job.id ? { ...j, ...patch } : j));
    try {
      const response = await fetch(`/api/jobs/${job.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
      if (!response.ok) throw new Error((await response.json()).error || "השמירה נכשלה");
      setSaveMessage("השינויים נשמרו");
    } catch (e) {
      setJobs(current => current.map(j => j.id === job.id ? job : j));
      setError(e instanceof Error ? e.message : "לא ניתן לשמור כרגע");
    }
    finally { savingRef.current = false; setSaving(false); }
  }
  function open(job: Job) { openerRef.current = document.activeElement as HTMLElement; setSelectedId(job.id); setNote(job.personal_note); setError(""); setSaveMessage(""); }

  const titles: Record<string, string> = { jobs: "הזדמנויות", applications: "המועמדויות שלי", companies: "חברות במעקב", import: "ייבוא ממצאים" };
  const descriptions: Record<string, string> = { jobs: "משרות הנדסה ופיזיקה שנמצאו עבורך", applications: "מהתכנון להגשה ועד לשלב הבא בתהליך", companies: "מקורות האיסוף, תוצאות הבדיקה והחברות שבמעקב", import: "מוסיפים חברות ומשרות מהחיפוש שלך, עם בדיקה לפני ייבוא" };
  function navigate(value: string) { setTab(value); setQuery(""); setError(""); setSaveMessage(""); }
  const localJobs = locatedJobs.filter(j => j.region === "israel");
  const metrics = [
    { label: "מומלצות בישראל", value: recommended.length, action: () => { navigate("jobs"); setFilter("recommended"); setRegion("israel"); } },
    { label: "חדשות ב־24 שעות · בישראל", value: localJobs.filter(j => isFresh(j) && !j.familiar && j.eligible && j.status === "open").length, action: () => { navigate("jobs"); setFilter("new"); setRegion("israel"); } },
    { label: "שמורות בישראל", value: localJobs.filter(j => j.fit === "yes" || j.application_status === "planned").length, action: () => { navigate("jobs"); setFilter("saved"); setRegion("israel"); } },
    { label: "מועמדויות פעילות", value: jobs.filter(j => ["applied", "interviewing"].includes(j.application_status)).length, action: () => navigate("applications") },
  ];
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">דילוג לתוכן</a>
    <aside className="sidebar">
      <a href="/" className="brand" aria-label="Ofir ראשי"><span className="brand-mark">of</span><span>ofir<span className="brand-dot">.</span></span></a>
      <p className="workspace-label">חיפוש העבודה של אופיר</p>
      <nav aria-label="ניווט ראשי">{[
        ["jobs", "הזדמנויות", LayoutGrid, recommended.length], ["applications", "המועמדויות שלי", BriefcaseBusiness, jobs.filter(j => j.application_status !== "not_applied").length],
        ["companies", "חברות במעקב", Building2, companies.length], ["import", "ייבוא ממצאים", Sparkles, discoveries.filter(d => d.status === "pending").length],
      ].map(([value, label, Icon, count]) => { const NavIcon = Icon as typeof LayoutGrid; return <button key={String(value)} aria-label={String(label)} className={`nav-item ${tab === value ? "active" : ""}`} aria-current={tab === value ? "page" : undefined} onClick={() => navigate(String(value))}><NavIcon size={19}/><span>{String(label)}</span><span className="nav-count">{Number(count)}</span></button>; })}</nav>
      <div className="sidebar-bottom"><div className="profile-avatar">אכ</div><div><strong>אופיר כהן</strong><span>הנדסת חשמל ופיזיקה</span></div></div>
      {!local && <form action="/auth/logout" method="post"><button className="logout">יציאה מהחשבון</button></form>}
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb">המרחב שלי <span>/</span> <strong>{titles[tab]}</strong></div><span className="subtle">{local ? "סביבת פיתוח מקומית" : "המרחב האישי של אופיר"}</span></header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        <div className="page-heading"><div><h1>{titles[tab]}</h1><p>{descriptions[tab]}</p></div>{tab === "jobs" && <span className="page-caption"><ShieldCheck size={16}/> מקורות רשמיים · דירוג מוסבר</span>}</div>
        {tab === "jobs" && <section className="summary-metrics" aria-label="סיכום החיפוש">{metrics.map(m => <button key={m.label} onClick={m.action}><strong>{m.value}</strong><span>{m.label}</span><ArrowUpLeft size={16}/></button>)}</section>}
        {tab === "import" ? <ImportPanel discoveries={discoveries} available={importReady}/> : tab === "companies" ? <CompaniesList companies={companies} importReady={importReady}/> : <>
          <section className="content-panel discovery-toolbar" aria-label="חיפוש וסינון">
            {tab === "jobs" ? <div className="filter-tabs" aria-label="סינון משרות">{[["recommended", "מומלצות"], ["new", "חדשות ב־24 שעות"], ["saved", "שמורות"], ["all", "כל המשרות"]].map(([value,label]) => <button key={value} aria-pressed={filter === value} className={filter === value ? "selected" : ""} onClick={() => setFilter(value)}>{label}</button>)}</div> : <label className="application-filter">מצב מועמדות<select aria-label="סינון מצב מועמדות" value={applicationFilter} onChange={e => setApplicationFilter(e.target.value)}><option value="all">כל המועמדויות</option>{Object.entries(applicationLabels).filter(([v]) => v !== "not_applied").map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label>}
            <div className="search-controls"><div className="search-row"><Search size={18}/><input dir="auto" aria-label="חיפוש משרות" placeholder="חיפוש לפי תפקיד, חברה או מיקום..." value={query} onChange={e => setQuery(e.target.value)}/>{query && <button aria-label="ניקוי חיפוש" onClick={() => setQuery("")}><X size={16}/></button>}</div>
            {tab === "jobs" && <label className="select-control">מיקום<select aria-label="מיקום המשרה" value={region} onChange={e => setRegion(e.target.value as JobRegion | "all")}><option value="israel">בישראל ({regionCounts.israel})</option><option value="abroad">בחו״ל ({regionCounts.abroad})</option><option value="unknown">מיקום לבדיקה ({regionCounts.unknown})</option><option value="all">כל המיקומים ({jobs.length})</option></select></label>}
            <label className="select-control">מיון<select aria-label="מיון משרות" value={sort} onChange={e => setSort(e.target.value)}><option value="fit">לפי ציון התאמה</option><option value="newest">לפי גילוי אחרון</option></select></label></div>
          </section>
          <div className="results-heading"><h2>{tab === "applications" ? "מעקב מועמדויות" : filter === "recommended" ? "משרות מומלצות" : "תוצאות החיפוש"} <span>{visible.length}</span></h2><span>{tab === "jobs" ? `${jobs.length} רשומות במאגר · מומלצות: בישראל, מאומתות וציון 70 ומעלה` : "מוצגות מועמדויות מכל המיקומים"}</span></div>
          {error && !selected && <p role="alert" className="error">{error} — אפשר לנסות שוב.</p>}
          <p role="status" className="save-status">{saving ? "שומר…" : saveMessage}</p>
          {visible.length ? tab === "applications" ? <ApplicationTracker jobs={visible} busy={saving} open={open} update={update}/> : <div className="job-list">{visible.map(job => <JobCard key={job.id} job={job} busy={saving} open={open} update={update}/>)}</div> : <div className="empty-state"><Search size={25}/><h2>{jobs.length ? "אין משרות שתואמות לסינון הנוכחי" : "עדיין אין משרות במאגר"}</h2><p>{tab === "applications" ? "כאן יופיעו משרות שסימנת לתכנון הגשה או להמשך תהליך." : jobs.length ? "אפשר לשנות מיקום או להציג את כל המשרות במיקום שנבחר." : "בדקו את מקורות האיסוף במסך החברות."}</p><button className="secondary-button" onClick={() => { if (tab === "applications") { navigate("jobs"); setFilter("all"); } else if (jobs.length) { setFilter("all"); setQuery(""); } else navigate("companies"); }}>{tab === "applications" ? "לעיון במשרות" : jobs.length ? "כל המשרות במיקום שנבחר" : "לצפייה בחברות במעקב"}<ArrowUpLeft size={16}/></button></div>}
          {tab === "jobs" && <p className="bottom-note">הדירוג מסייע לתעדוף. התאמה מקצועית, תנאי סף וזמינות המשרה נבדקים בנפרד.</p>}
        </>}
      </main><footer className="page-footer"><span>ofir. · חיפוש עבודה אישי</span><span>מידע לא ידוע נשאר מסומן לבדיקה</span></footer>
    </div>
    {selected && <div className="modal-backdrop" onClick={() => !saving && setSelectedId(null)}><dialog ref={dialogRef} className="detail-modal" aria-labelledby="detail-title" onCancel={e => { e.preventDefault(); if (!saving) setSelectedId(null); }} onClick={e => e.stopPropagation()}><button autoFocus className="close-modal" aria-label="סגירה" onClick={() => setSelectedId(null)} disabled={saving}><X size={20} /></button><span className="eyebrow" dir="auto">{selected.company}</span><h2 id="detail-title" dir="auto">{selected.title}</h2><p className="subtle">{selected.location} · {selected.work_model} · {selected.experience}</p><a className="primary-button" href={safeLink(selected.url)} target="_blank" rel="noreferrer">{selected.status === "open" ? "למשרה באתר החברה" : "בדיקת המשרה במקור"}<ExternalLink size={16} /></a><p className="subtle">פתיחת הקישור אינה מסמנת שהוגשה מועמדות.</p><div className="detail-dates"><span>פרסום: {date(selected.published_at)}</span><span>עדכון מקור: {date(selected.updated_at)}</span><span>גילוי: {date(selected.first_seen_at)}</span><span>אימות: {date(selected.last_verified_at)}</span></div>
    <div className="notice">רמת ביטחון באימות: {verifiedRecently(selected) ? "אומתה במקור ב־30 השעות האחרונות" : selected.status === "closed" ? "המשרה מסומנת כסגורה" : "נדרש אימות עדכני; בדקו את המקור"}. ציון ההתאמה מבוסס על כללים ראשוניים ואינו מבטיח קבלה.</div>
    {!selected.eligible && <div className="error">{selected.exclusion_reason}</div>}
    <h3>למה היא עשויה להתאים</h3><ul>{selected.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul><h3>פערים ומה צריך לבדוק</h3><ul>{selected.gaps.map(gap => <li key={gap}>{gap}</li>)}</ul><div className="score-breakdown">{Object.entries(selected.breakdown).map(([key, value]) => <div key={key}><span>{breakdownLabels[key]}</span><strong>{value}/{maximums[key]}</strong></div>)}</div>
    <section className="personal-controls"><h3>ההתרשמות וההתקדמות שלך</h3><label>מידת ההתאמה בעיניי<select aria-label="מידת ההתאמה בעיניי" value={selected.fit} disabled={saving} onChange={e => update(selected, { fit: e.target.value as Fit })}>{Object.entries(fitLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>מצב מועמדות<select aria-label="מצב מועמדות" value={selected.application_status} disabled={saving} onChange={e => update(selected, { application_status: e.target.value as ApplicationStatus })}>{Object.entries(applicationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="checkbox-row"><input type="checkbox" checked={selected.familiar} disabled={saving} onChange={e => update(selected, { familiar: e.target.checked })} />המשרה כבר מוכרת לי</label><label>הערה אישית<textarea aria-label="הערה אישית" maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></label><button className="secondary-button" disabled={saving} onClick={() => update(selected, { personal_note: note })}>{saving ? "שומר…" : "שמירת הערה"}<CheckCheck size={15} /></button>{error && <p role="alert" className="error">{error}</p>}<p role="status" className="save-status">{saveMessage}</p></section><details className="description"><summary>תיאור התפקיד במקור</summary><p dir="auto">{selected.description}</p></details></dialog></div>}
  </div>;
}
