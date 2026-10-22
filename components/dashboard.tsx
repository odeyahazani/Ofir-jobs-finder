"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownWideNarrow, ArrowUpLeft, Bell, BriefcaseBusiness, Building2, Check, CheckCheck, ChevronDown, Clock3, Compass, ExternalLink, FlaskConical, LayoutGrid, MapPin, Search, ShieldCheck, SlidersHorizontal, Sparkles, Target, X } from "lucide-react";
import type { ApplicationStatus, Company, Fit, Job } from "@/lib/types";

const applicationLabels: Record<ApplicationStatus, string> = { not_applied: "טרם הגשתי", planned: "מתכנן להגיש", applied: "הגשתי", interviewing: "בתהליך", rejected: "נדחיתי", withdrawn: "ויתרתי" };
const fitLabels: Record<Fit, string> = { unrated: "טרם דירגתי", yes: "מתאים לי", maybe: "אולי מתאים", no: "לא מתאים" };
const sourceLabels: Record<string, string> = { pending: "טרם נבדק", ok: "נסרק בהצלחה", empty: "אין משרות במקור", blocked: "הגישה חסומה", unsupported: "נדרשת התאמת איסוף", error: "שגיאה בבדיקה" };
const breakdownLabels: Record<string, string> = { professional: "משימות התפקיד", experience: "רמת ניסיון", technical: "כישורים טכניים", sector: "תחום החברה", location: "מיקום ונסיעה", growth: "התפתחות" };
const maximums: Record<string, number> = { professional: 30, experience: 25, technical: 20, sector: 10, location: 10, growth: 5 };
function date(value: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return "לא ידוע";
  return new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "short", timeZone: "Asia/Jerusalem" }).format(new Date(value));
}
function isFresh(job: Job) { return Date.now() - Date.parse(job.first_seen_at) < 86400000; }
function verifiedRecently(job: Job) { return job.status === "open" && !!job.last_verified_at && Date.now() - Date.parse(job.last_verified_at) < 30 * 3600000; }

export default function Dashboard({ jobs: initialJobs, companies, local }: { jobs: Job[]; companies: Company[]; local: boolean }) {
  const [jobs, setJobs] = useState(initialJobs);
  const [tab, setTab] = useState("jobs");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("recommended");
  const [sort, setSort] = useState("fit");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [note, setNote] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!selectedId) return;
    const dialog = dialogRef.current;
    dialog?.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { dialog?.close(); document.body.style.overflow = previous; };
  }, [selectedId]);
  const active = companies.filter(c => c.enabled);
  const healthy = active.filter(c => ["ok", "empty"].includes(c.source_status));
  const recommended = jobs.filter(j => j.eligible && verifiedRecently(j) && j.score >= 70 && j.fit !== "no" && j.application_status === "not_applied");
  const applied = jobs.filter(j => ["applied", "interviewing", "rejected"].includes(j.application_status));
  const selected = jobs.find(j => j.id === selectedId);
  const visible = useMemo(() => {
    const filtered = jobs.filter(job => {
      const matchesQuery = `${job.title} ${job.company} ${job.location}`.toLowerCase().includes(query.toLowerCase());
      const matchesTab = tab !== "applications" || job.application_status !== "not_applied";
      const matchesFilter = tab === "applications" || (filter === "recommended" ? job.eligible && verifiedRecently(job) && job.score >= 70 && job.fit !== "no" && job.application_status === "not_applied" :
        filter === "new" ? isFresh(job) && !job.familiar && job.eligible && job.status === "open" :
        filter === "saved" ? job.fit === "yes" || job.application_status === "planned" : true);
      return matchesQuery && matchesTab && matchesFilter;
    });
    return filtered.sort((a, b) => sort === "newest" ? (Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at)) :
      Math.floor(b.score / 10) - Math.floor(a.score / 10) || (Date.parse(b.published_at || "") || 0) - (Date.parse(a.published_at || "") || 0) || Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at));
  }, [jobs, query, filter, sort, tab]);

  async function update(job: Job, patch: Partial<Pick<Job, "fit" | "familiar" | "application_status" | "personal_note">>) {
    if (saving) return;
    setSaving(true); setError(""); setSaveMessage("");
    try {
      const response = await fetch(`/api/jobs/${job.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
      if (!response.ok) throw new Error((await response.json()).error || "השמירה נכשלה");
      setJobs(current => current.map(j => j.id === job.id ? { ...j, ...patch } : j));
      setSaveMessage("השינויים נשמרו");
    } catch (e) { setError(e instanceof Error ? e.message : "לא ניתן לשמור כרגע"); }
    finally { setSaving(false); }
  }
  function open(job: Job) { setSelectedId(job.id); setNote(job.personal_note); setError(""); setSaveMessage(""); }

  return <div className="app-shell">
    <aside className="sidebar">
      <a href="/" className="brand" aria-label="Ofir ראשי"><span className="brand-mark">o<span>f</span></span><span>ofir<span className="brand-dot">.</span></span></a>
      <div className="workspace-label">המרחב האישי שלך</div>
      <nav aria-label="ניווט ראשי">
        <button className={tab === "jobs" ? "nav-item active" : "nav-item"} onClick={() => setTab("jobs")}><LayoutGrid size={19} />הזדמנויות<span className="nav-count">{recommended.length}</span></button>
        <button className={tab === "applications" ? "nav-item active" : "nav-item"} onClick={() => setTab("applications")}><BriefcaseBusiness size={19} />המועמדויות שלי</button>
        <button className={tab === "companies" ? "nav-item active" : "nav-item"} onClick={() => setTab("companies")}><Building2 size={19} />חברות במעקב<span className="plain-count">{companies.length}</span></button>
      </nav>
      <div className="sidebar-insight"><span className="mini-icon"><FlaskConical size={19} /></span><strong>המקום שבו תחומים נפגשים</strong><p>הנדסת חשמל, פיזיקה וסקרנות.<br />מחפשים את השילוב שמתאים לך.</p><span className="tiny-tag">בנוי סביבך <Sparkles size={12} /></span></div>
      <div className="sidebar-bottom"><div className="profile-avatar">אכ</div><div><strong>אופיר כהן</strong><span>Electrical Engineering & Physics</span></div><span className="online-dot" /></div>
      {!local && <form action="/auth/logout" method="post"><button className="logout">יציאה מהחשבון</button></form>}
    </aside>

    <div className="main-shell"><header className="topbar"><div className="breadcrumb">המרחב שלי <span>/</span> <strong>{tab === "companies" ? "חברות במעקב" : tab === "applications" ? "המועמדויות שלי" : "הזדמנויות"}</strong></div><div className="topbar-status"><span className="status-dot" />{local ? "מצב פיתוח מקומי" : "החשבון האישי שלך"}<span className="header-divider" /><Bell size={18} /></div></header>
    <main className="main-content">
      <div className="page-heading"><div><div className="eyebrow"><span className="little-line" />הצעד הבא מתחיל כאן</div><h1>{tab === "companies" ? "מגלים איפה ההזדמנות הבאה." : tab === "applications" ? "כל התהליך, במקום אחד." : <>היי אופיר, <span>בוא נמצא את הדבר הבא.</span></>}</h1><p>{tab === "companies" ? "מאגר החברות שלך, מצב האיסוף ומה עוד צריך לבדוק." : tab === "applications" ? "המשרות ששמרת להמשך ואלה שכבר עשית לקראתן צעד." : "הזדמנויות בהנדסה ובפיזיקה, שנבחרות לפי מה שחשוב לך."}</p></div><div className="date-chip"><Clock3 size={15} />שעון ישראל</div></div>

      <section className="stats-grid" aria-label="סיכום החיפוש">
        <Stat label="הזדמנויות מומלצות" value={recommended.length} sub="מאומתות · ציון 70 ומעלה" icon={<Target size={21} />} color="purple" />
        <Stat label="חברות במאגר" value={companies.length} sub={`${active.length} בקבוצת הבדיקה הראשונה`} icon={<Building2 size={21} />} color="blue" />
        <Stat label="מקורות שנבדקו בהצלחה" value={`${healthy.length}/${active.length}`} sub="חסימה אינה היעדר משרות" icon={<ShieldCheck size={21} />} color="green" />
        <Stat label="מועמדויות שהוגשו" value={applied.length} sub="צעד נוסף בדרך לתפקיד הראשון" icon={<BriefcaseBusiness size={21} />} color="peach" />
      </section>

      <div className="focus-banner"><div className="focus-symbol"><Compass size={26} /></div><div><strong>המצפן שלך: תפקיד עם עומק, ועשייה בידיים</strong><p>מכשור רפואי · אופטיקה · אינטגרציה ו־V&V · מחקר ופיתוח</p></div><span className="focus-pill">מעבדה + קוד</span></div>

      {tab === "companies" ? <section className="content-panel"><div className="section-heading"><h2>החברות במאגר <span>{companies.length}</span></h2><span className="subtle">נתוני הייבוא נשמרו כמידע היסטורי</span></div><div className="search-row"><Search size={18} /><input aria-label="חיפוש חברות" placeholder="חיפוש לפי חברה או מיקום…" value={query} onChange={e => setQuery(e.target.value)} /></div><div className="company-list">{companies.filter(c => `${c.name} ${c.location_hint}`.toLowerCase().includes(query.toLowerCase())).map(c => <article className="company-row" key={c.id}><div className="company-monogram">{c.name.slice(0, 1)}</div><div className="company-info"><strong dir="auto">{c.name}</strong><span>{c.location_hint || "מיקום לא אומת"} · {c.ats_hint}</span></div><div className="company-status"><span className={`source-badge ${c.source_status}`}>{sourceLabels[c.source_status] || c.source_status}</span><small>{c.enabled ? "בקבוצת הבדיקה" : "במאגר להמשך"} · {c.last_checked ? date(c.last_checked) : "טרם נבדק"}</small></div><details><summary>פרטים</summary><p>{c.last_result}</p>{c.career_url && <a href={safeLink(c.career_url)} target="_blank" rel="noreferrer">קישור מהייבוא — {c.source_status === "pending" ? "טרם אומת מחדש" : "לבדיקה"} <ExternalLink size={12} /></a>}<p className="subtle">בדיקה קודמת מהקובץ: {c.imported_last_checked || "לא צוינה"}<br />{c.imported_last_result || "אין תוצאה היסטורית"}</p></details></article>)}</div></section> : <section className="content-panel">
        <div className="section-heading"><div><h2>{tab === "applications" ? "המועמדויות שלי" : "ההזדמנויות שלך"} <span>{visible.length}</span></h2><p className="section-description">{tab === "applications" ? "עדכן את ההתקדמות שלך בכל משרה." : "התאמה מקצועית קודם, עדכניות אחר כך."}</p></div><span className="subtle desktop-only"><ShieldCheck size={14} /> מקור ורמת אימות בכל משרה</span></div>
        <div className="filter-toolbar"><div className="filter-tabs" aria-label="סינון משרות">{[["recommended", "מומלצות"], ["new", "התגלו היום"], ["saved", "שמרתי להמשך"], ["all", "כל המשרות"]].map(([value, label]) => <button key={value} disabled={tab === "applications"} className={filter === value ? "selected" : ""} onClick={() => setFilter(value)}>{label}</button>)}</div><label className="sort-control"><ArrowDownWideNarrow size={15} /><select aria-label="מיון משרות" value={sort} onChange={e => setSort(e.target.value)}><option value="fit">לפי התאמה</option><option value="newest">לפי גילוי אחרון</option></select></label></div>
        <div className="search-row"><Search size={18} /><input aria-label="חיפוש משרות" placeholder="חיפוש תפקיד, חברה או מיקום…" value={query} onChange={e => setQuery(e.target.value)} /><SlidersHorizontal size={17} /></div>
        {error && <div role="alert" className="error">{error}</div>}
        <div role="status" className="sr-only">{saving ? "שומר…" : saveMessage}</div>
        {visible.length ? <div className="job-list">{visible.map(job => <article className="job-card" key={job.id}><div className="job-top"><div className="company-monogram">{job.company.slice(0, 1)}</div><div className="job-identity"><span className="company-name" dir="auto">{job.company}</span><h3 dir="auto"><button onClick={() => open(job)}>{job.title}</button></h3><div className="job-meta"><span><MapPin size={13} />{job.location}</span><span><BriefcaseBusiness size={13} />{job.experience}</span></div></div><div className={`score ${job.score >= 80 ? "high" : ""}`}><strong>{job.score}</strong><span>התאמה / 100</span></div></div><div className="job-tags"><span className={`verification ${job.status === "open" ? "verified" : ""}`}><ShieldCheck size={12} />{job.status === "open" ? "אומתה במקור" : job.status === "closed" ? "נסגרה" : "טרם אומתה"}</span>{job.familiar && <span>מוכרת לי</span>}{job.application_status !== "not_applied" && <span>{applicationLabels[job.application_status]}</span>}{job.fit !== "unrated" && <span>{fitLabels[job.fit]}</span>}{!job.eligible && <span className="warning-tag">מחוץ לתנאי ההתאמה</span>}</div><p className="job-reason">{job.reasons[0] || "נדרשת בחינה של תיאור התפקיד"}</p><div className="job-footer"><span>פורסמה: {date(job.published_at)} <i>·</i> התגלתה: {date(job.first_seen_at)}</span><button className="text-button" onClick={() => open(job)}>לפרטים ולסימון <ArrowUpLeft size={16} /></button></div></article>)}</div> : <div className="empty-state"><div className="empty-illustration"><div className="empty-ring" /><Search size={34} /><span><Sparkles size={15} /></span></div><h3>{jobs.length ? "אין משרות שתואמות לסינון הזה" : "מכינים את הקרקע להזדמנות הבאה"}</h3><p>{jobs.length ? "אפשר לשנות את החיפוש או לעבור לכל המשרות." : "רשימת החברות כבר כאן. משרות יופיעו אחרי סריקה מוצלחת ואימות במקור הרשמי."}</p>{!jobs.length && <div className="empty-steps"><span><Check size={13} />138 חברות יובאו</span><span><Clock3 size={13} />אימות המקורות בתהליך</span></div>}<button className="secondary-button" onClick={() => jobs.length ? setFilter("all") : setTab("companies")}>{jobs.length ? "לכל המשרות" : "לצפייה בחברות במעקב"}<ArrowUpLeft size={16} /></button></div>}
      </section>}
      <div className="bottom-note"><ShieldCheck size={14} /><span>הדירוג עוזר לתעדף. לפני הגשה, כדאי לקרוא את הדרישות ואת פערי ההתאמה.</span></div>
      <section className="schedule-strip"><div><Clock3 size={17} /><span>התכנון: סריקות ב־08:00 וב־17:00</span></div><div><Bell size={17} /><span>סיכום יומי בטלגרם ב־18:00</span><span className="setup-badge">ממתין לחיבור ולהפעלה</span></div></section>
    </main><footer className="page-footer"><span>ofir. <i>ההזדמנות הבאה שלך.</i></span><span>נבנה בשביל הדרך שלך <Sparkles size={12} /></span></footer></div>

    {selected && <div className="modal-backdrop" onClick={() => !saving && setSelectedId(null)}><dialog ref={dialogRef} className="detail-modal" aria-labelledby="detail-title" onCancel={e => { e.preventDefault(); if (!saving) setSelectedId(null); }} onClick={e => e.stopPropagation()}><button autoFocus className="close-modal" aria-label="סגירה" onClick={() => setSelectedId(null)} disabled={saving}><X size={20} /></button><span className="eyebrow" dir="auto">{selected.company}</span><h2 id="detail-title" dir="auto">{selected.title}</h2><p className="subtle">{selected.location} · {selected.work_model} · {selected.experience}</p><div className="detail-dates"><span>פרסום: {date(selected.published_at)}</span><span>עדכון מקור: {date(selected.updated_at)}</span><span>גילוי: {date(selected.first_seen_at)}</span><span>אימות: {date(selected.last_verified_at)}</span></div>
    <div className="notice">רמת ביטחון באימות: {selected.status === "open" ? "גבוהה — נבדקה במקור הרשמי בזמן המצוין" : "נמוכה — אין כרגע אימות למשרה פעילה"}. ציון ההתאמה מבוסס על כללים ראשוניים ואינו מבטיח קבלה.</div>
    {!selected.eligible && <div className="error">{selected.exclusion_reason}</div>}
    <h3>למה היא עשויה להתאים</h3><ul>{selected.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul><h3>פערים ומה צריך לבדוק</h3><ul>{selected.gaps.map(gap => <li key={gap}>{gap}</li>)}</ul><div className="score-breakdown">{Object.entries(selected.breakdown).map(([key, value]) => <div key={key}><span>{breakdownLabels[key]}</span><strong>{value}/{maximums[key]}</strong></div>)}</div>
    <section className="personal-controls"><h3>ההתרשמות וההתקדמות שלך</h3><label>מידת ההתאמה בעיניי<select aria-label="מידת ההתאמה בעיניי" value={selected.fit} disabled={saving} onChange={e => update(selected, { fit: e.target.value as Fit })}>{Object.entries(fitLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>מצב מועמדות<select aria-label="מצב מועמדות" value={selected.application_status} disabled={saving} onChange={e => update(selected, { application_status: e.target.value as ApplicationStatus })}>{Object.entries(applicationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="checkbox-row"><input type="checkbox" checked={selected.familiar} disabled={saving} onChange={e => update(selected, { familiar: e.target.checked })} />המשרה כבר מוכרת לי</label><label>הערה אישית<textarea aria-label="הערה אישית" maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></label><button className="secondary-button" disabled={saving} onClick={() => update(selected, { personal_note: note })}>{saving ? "שומר…" : "שמירת הערה"}<CheckCheck size={15} /></button>{error && <p role="alert" className="error">{error}</p>}<p role="status" className="save-status">{saveMessage}</p></section><details className="description"><summary>תיאור התפקיד במקור</summary><p dir="auto">{selected.description}</p></details><a className="primary-button" href={safeLink(selected.url)} target="_blank" rel="noreferrer">{selected.status === "open" ? "למשרה באתר החברה" : "בדיקת המשרה במקור"}<ExternalLink size={16} /></a><p className="subtle">פתיחת הקישור אינה מסמנת שהוגשה מועמדות.</p></dialog></div>}
  </div>;
}
function Stat({ label, value, sub, icon, color }: { label: string; value: number | string; sub: string; icon: React.ReactNode; color: string }) {
  return <article className="stat-card"><div className="stat-header"><span>{label}</span><span className={`stat-icon ${color}`}>{icon}</span></div><strong className="stat-value">{value}</strong><p>{sub}</p></article>;
}
function safeLink(value: string) { try { const url = new URL(value); return url.protocol === "https:" ? url.href : undefined; } catch { return undefined; } }
