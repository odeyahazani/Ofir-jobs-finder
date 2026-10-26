"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpLeft, Bookmark, BriefcaseBusiness, Building2, CircleHelp, LayoutGrid, Search, ShieldCheck, SlidersHorizontal, Sparkles, X } from "lucide-react";
import type { Company, Discovery, Job } from "@/lib/types";
import { classifyLocation, type JobRegion } from "@/lib/location";
import { currentMatch, priorityMatch } from "@/lib/matching";
import ImportPanel from "./import-panel";
import CompaniesList from "./companies-list";
import { JobCard, ApplicationTracker } from "./job-views";
import { applicationLabels, verifiedRecently } from "./job-ui";
import JobDetails, { type JobPatch } from "./job-details";

function isFresh(job: Job) { const age = Date.now() - Date.parse(job.first_seen_at); return age >= 0 && age < 86400000; }
function recommendedJob(job: Job) { return classifyLocation(job.location) === "israel" && priorityMatch(job) && verifiedRecently(job) && job.fit !== "no" && job.application_status === "not_applied"; }
function reviewJob(job: Job) { return currentMatch(job) && job.match_category === "review" && job.status !== "closed" && job.fit !== "no" && job.application_status === "not_applied"; }
function defaultFilter(jobs: Job[]) {
  return jobs.some(recommendedJob) ? "recommended" : jobs.some(j => classifyLocation(j.location) === "israel" && reviewJob(j)) ? "review" : "recommended";
}
const filters = [["recommended", "מומלצות"], ["review", "שוות בדיקה"], ["saved", "שמורות"], ["new", "חדשות ב־24 שעות"], ["all", "כל המשרות"], ["gap", "פערים בדרישות"]];

export default function Dashboard({ jobs: initialJobs, companies, discoveries, importReady, local }: { jobs: Job[]; companies: Company[]; discoveries: Discovery[]; importReady: boolean; local: boolean }) {
  const [jobs, setJobs] = useState(initialJobs);
  const [tab, setTab] = useState("jobs");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState(() => defaultFilter(initialJobs));
  const [region, setRegion] = useState<JobRegion | "all">("israel");
  const [sort, setSort] = useState("fit");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [applicationFilter, setApplicationFilter] = useState("all");
  const savingRef = useRef(false);
  const filterBarRef = useRef<HTMLDivElement>(null);
  useEffect(() => { setJobs(initialJobs); }, [initialJobs]);
  useEffect(() => {
    const bar = filterBarRef.current;
    if (!bar) return;
    const revealSelection = () => {
      const active = bar.querySelector<HTMLElement>('[aria-pressed="true"]');
      if (!active || bar.scrollWidth <= bar.clientWidth) return;
      const bounds = bar.getBoundingClientRect(), selected = active.getBoundingClientRect();
      if (selected.left < bounds.left + 8) bar.scrollLeft += selected.left - bounds.left - 8;
      else if (selected.right > bounds.right - 8) bar.scrollLeft += selected.right - bounds.right + 8;
    };
    revealSelection();
    const observer = new ResizeObserver(revealSelection);
    observer.observe(bar);
    return () => observer.disconnect();
  }, [filter, tab]);
  const locatedJobs = useMemo(() => jobs.map(job => ({ ...job, region: classifyLocation(job.location) })), [jobs]);
  const regionCounts = { israel: 0, abroad: 0, unknown: 0 };
  for (const job of locatedJobs) regionCounts[job.region]++;
  const recommended = locatedJobs.filter(recommendedJob);
  const review = locatedJobs.filter(j => j.region === "israel" && reviewJob(j));
  const unassessed = jobs.filter(j => !currentMatch(j)).length;
  const selected = jobs.find(j => j.id === selectedId);

  function matchesFilter(job: Job, value: string) {
    return value === "recommended" ? recommendedJob(job) : value === "review" ? reviewJob(job) :
      value === "gap" ? currentMatch(job) && job.match_category === "gap" :
      value === "new" ? isFresh(job) && !job.familiar && job.eligible && job.status === "open" :
      value === "saved" ? job.fit === "yes" || job.application_status === "planned" : true;
  }
  const normalizedQuery = query.toLowerCase().trim();
  function matchesQuery(job: Job) { return `${job.title} ${job.company} ${job.location}`.toLowerCase().includes(normalizedQuery); }
  const filterCounts = Object.fromEntries(filters.map(([value]) => [value, locatedJobs.filter(j => (region === "all" || j.region === region) && matchesQuery(j) && matchesFilter(j, value)).length]));
  const visible = locatedJobs.filter(job => {
    const matchesTab = tab !== "applications" || (job.application_status !== "not_applied" && (applicationFilter === "all" || job.application_status === applicationFilter));
    const matchesRegion = tab === "applications" || region === "all" || job.region === region;
    return matchesQuery(job) && matchesTab && matchesRegion && (tab === "applications" || matchesFilter(job, filter));
  }).sort((a, b) => sort === "newest" ? Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at) :
    b.score - a.score || (Date.parse(b.published_at || "") || 0) - (Date.parse(a.published_at || "") || 0) || Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at));

  async function update(job: Job, patch: JobPatch) {
    if (savingRef.current) return false;
    savingRef.current = true;
    setSaving(true); setError(""); setSaveMessage("");
    setJobs(current => current.map(j => j.id === job.id ? { ...j, ...patch } : j));
    try {
      const response = await fetch(`/api/jobs/${job.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
      if (!response.ok) throw new Error((await response.json()).error || "השמירה נכשלה");
      setSaveMessage("השינויים נשמרו"); return true;
    } catch (e) {
      setJobs(current => current.map(j => j.id === job.id ? job : j));
      setError(e instanceof Error ? e.message : "לא ניתן לשמור כרגע"); return false;
    } finally { savingRef.current = false; setSaving(false); }
  }
  function open(job: Job) { setSelectedId(job.id); setError(""); setSaveMessage(""); }
  function navigate(value: string) { setTab(value); setQuery(""); setError(""); setSaveMessage(""); }
  function chooseFilter(value: string) { navigate("jobs"); setFilter(value); setRegion("israel"); }
  const titles: Record<string, string> = { jobs: "הזדמנויות", applications: "המועמדויות שלי", companies: "חברות במעקב", import: "ייבוא ממצאים" };
  const descriptions: Record<string, string> = {
    jobs: "הצעד הבא שלך בהנדסה ובפיזיקה. כל משרה, עם התמונה המלאה.",
    applications: "כל התהליכים שלך, מהשמירה הראשונה ועד לשלב הבא.",
    companies: "מגדילים את החיפוש, חברה אחת בכל פעם.",
    import: "ממצאים שמצאת בדרך, עם בדיקה לפני שהם מצטרפים למאגר.",
  };
  const localJobs = locatedJobs.filter(j => j.region === "israel");
  const metrics = [
    { id: "recommended", label: "מומלצות בישראל", value: recommended.length, icon: Sparkles, action: () => chooseFilter("recommended") },
    { id: "review", label: "שוות בדיקה בישראל", value: review.length, icon: CircleHelp, action: () => chooseFilter("review") },
    { id: "saved", label: "שמורות בישראל", value: localJobs.filter(j => j.fit === "yes" || j.application_status === "planned").length, icon: Bookmark, action: () => chooseFilter("saved") },
    { id: "applications", label: "מועמדויות פעילות", value: jobs.filter(j => ["applied", "interviewing"].includes(j.application_status)).length, icon: BriefcaseBusiness, action: () => navigate("applications") },
  ];
  const reviewSuggestion = tab === "jobs" && filter === "recommended" && !query.trim() && (region === "israel" || region === "all") && review.length > 0;
  const resultTitle = tab === "applications" ? "מעקב מועמדויות" : filter === "recommended" ? "משרות מומלצות" : filter === "review" ? "שוות בדיקה" : filter === "saved" ? "המשרות ששמרת" : filter === "gap" ? "פערים בדרישות או במיקוד" : "תוצאות החיפוש";

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">דילוג לתוכן</a>
    <aside className="sidebar">
      <a href="/" className="brand" aria-label="Ofir ראשי"><span className="brand-mark">of</span><span>ofir<span className="brand-dot">.</span></span></a>
      <p className="workspace-label">המרחב האישי של אופיר</p>
      <span className="nav-caption" aria-hidden="true">החיפוש שלך</span>
      <nav aria-label="ניווט ראשי">{[
        ["jobs", "הזדמנויות", LayoutGrid, recommended.length + review.length],
        ["applications", "המועמדויות שלי", BriefcaseBusiness, jobs.filter(j => j.application_status !== "not_applied").length],
        ["companies", "חברות במעקב", Building2, companies.length],
        ["import", "ייבוא ממצאים", Sparkles, discoveries.filter(d => d.status === "pending").length],
      ].map(([value, label, Icon, count]) => {
        const NavIcon = Icon as typeof LayoutGrid;
        return <button key={String(value)} aria-label={String(label)} className={`nav-item ${tab === value ? "active" : ""}`} aria-current={tab === value ? "page" : undefined} onClick={() => navigate(String(value))}><NavIcon size={19}/><span>{String(label)}</span><span className="nav-count">{Number(count)}</span></button>;
      })}</nav>
      <div className="sidebar-bottom"><div className="profile-avatar">אכ</div><div><strong>אופיר כהן</strong><span>הנדסת חשמל ופיזיקה</span></div><ShieldCheck size={16} aria-label="מרחב פרטי"/></div>
      {!local && <form action="/auth/logout" method="post"><button className="logout">יציאה מהחשבון</button></form>}
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb">המרחב שלי <span>/</span><strong>{titles[tab]}</strong></div><div className="workspace-identity"><span className="private-label"><ShieldCheck size={14}/> מרחב פרטי</span><span className="workspace-avatar">אכ</span><span>{local ? "סביבת פיתוח" : "אופיר כהן"}</span></div></header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        <div className="page-heading"><div><p className="page-eyebrow">{tab === "jobs" ? "למצוא את המקום שלך" : "המרחב האישי שלך"}</p><h1>{titles[tab]}</h1><p>{descriptions[tab]}</p></div>{tab === "jobs" && <span className="page-caption"><ShieldCheck size={16}/> מקורות רשמיים<br/>התאמה עם הסבר</span>}</div>
        {tab === "jobs" && <section className="summary-metrics" aria-label="סיכום החיפוש">{metrics.map(m => <button key={m.id} data-active={filter === m.id && region === "israel"} onClick={m.action}><span className="metric-icon"><m.icon size={18}/></span><span className="metric-copy"><strong>{m.value}</strong><span>{m.label}</span></span><ArrowUpLeft className="metric-arrow" size={16}/></button>)}</section>}
        {tab === "import" ? <ImportPanel discoveries={discoveries} available={importReady}/> : tab === "companies" ? <CompaniesList companies={companies} importReady={importReady}/> : <>
          {tab === "jobs" && unassessed > 0 && <p className="notice matching-pending">{unassessed} משרות טרם הותאמו לפרופיל המפורט. הדירוג הקודם שלהן מוצג עד לחישוב מחדש, ומסומן בכל משרה.</p>}
          <section className="content-panel discovery-toolbar" aria-label="חיפוש וסינון">
            <div className="search-controls"><div className="search-row"><Search size={18}/><input dir="auto" aria-label="חיפוש משרות" placeholder="תפקיד, חברה או מקום שעובדים בו…" value={query} onChange={e => setQuery(e.target.value)}/>{query && <button aria-label="ניקוי חיפוש" onClick={() => setQuery("")}><X size={16}/></button>}</div>
              {tab === "jobs" && <label className="select-control">מיקום<select aria-label="מיקום המשרה" value={region} onChange={e => setRegion(e.target.value as JobRegion | "all")}><option value="israel">בישראל ({regionCounts.israel})</option><option value="abroad">בחו״ל ({regionCounts.abroad})</option><option value="unknown">מיקום לבדיקה ({regionCounts.unknown})</option><option value="all">כל המיקומים ({jobs.length})</option></select></label>}
              <label className="select-control">מיון<select aria-label="מיון משרות" value={sort} onChange={e => setSort(e.target.value)}><option value="fit">לפי ציון התאמה</option><option value="newest">לפי גילוי אחרון</option></select></label>
            </div>
            {tab === "jobs" ? <div ref={filterBarRef} className="filter-tabs" aria-label="סינון משרות">{filters.map(([value, label]) => <button key={value} aria-label={label} aria-pressed={filter === value} className={filter === value ? "selected" : ""} onClick={() => setFilter(value)}>{label}<span aria-hidden="true">{filterCounts[value]}</span></button>)}</div> : <label className="application-filter">מצב מועמדות<select aria-label="סינון מצב מועמדות" value={applicationFilter} onChange={e => setApplicationFilter(e.target.value)}><option value="all">כל המועמדויות</option>{Object.entries(applicationLabels).filter(([v]) => v !== "not_applied").map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label>}
          </section>
          <div className="results-heading"><h2 aria-live="polite">{resultTitle}<span>{visible.length}</span></h2><span>{tab === "jobs" ? `${jobs.length} משרות במאגר · מוצגות לפי הסינון שלך` : "מוצגות מועמדויות מכל המיקומים"}</span></div>
          {error && !selected && <p role="alert" className="error">{error} — אפשר לנסות שוב.</p>}
          <p role="status" className="save-status">{saving ? "שומר…" : saveMessage}</p>
          {visible.length ? tab === "applications" ? <ApplicationTracker jobs={visible} busy={saving} open={open} update={update}/> : <div className="job-list">{visible.map(job => <JobCard key={job.id} job={job} busy={saving} open={open} update={update}/>)}</div> : <div className="empty-state"><span className="empty-icon">{filter === "recommended" && !query ? <Sparkles size={25}/> : <Search size={25}/>}</span><h2>{!jobs.length ? "עדיין אין משרות במאגר" : query.trim() ? "לא נמצאו משרות לחיפוש הזה" : tab === "applications" ? "התהליך הבא שלך מתחיל כאן" : filter === "recommended" ? "כרגע אין משרות בעדיפות גבוהה" : "אין משרות שתואמות לסינון הנוכחי"}</h2>
            <p>{tab === "applications" ? "משרה שסימנת לתכנון הגשה או להמשך תהליך תופיע כאן." : !jobs.length ? "אפשר להתחיל מהחברות שבמעקב ולבדוק את מקורות החיפוש." : reviewSuggestion ? `יש ${review.length} משרות עם חיבור מקצועי ושאלות שכדאי לברר. אפשר להתחיל מהן.` : filter === "recommended" && !query.trim() ? "מומלצות משלבות חיבור מקצועי, התאמה לדרישות ואימות עדכני במקור. אפשר לעיין גם בשאר המשרות." : "אפשר לשנות את החיפוש או להציג את כל המשרות במיקום שנבחר."}</p>
            {reviewSuggestion && <button className="primary-button" onClick={() => chooseFilter("review")}>למשרות ששוות בדיקה<ArrowUpLeft size={16}/></button>}
            <button className={reviewSuggestion ? "empty-secondary" : "secondary-button"} onClick={() => { if (tab === "applications") { navigate("jobs"); setFilter("all"); } else if (jobs.length) { setFilter("all"); setQuery(""); } else navigate("companies"); }}>{tab === "applications" ? "לעיון במשרות" : jobs.length ? "כל המשרות במיקום שנבחר" : "לצפייה בחברות במעקב"}<ArrowUpLeft size={16}/></button>
          </div>}
          {tab === "jobs" && <p className="bottom-note"><SlidersHorizontal size={13}/> הציון מתאר חיבור מקצועי. דרישות ניסיון ואימות המקור נבדקים בנפרד.</p>}
        </>}
      </main><footer className="page-footer"><span><bdi>ofir.</bdi> מרחב אישי לקריירה</span><span>הנדסה, פיזיקה וההזדמנות הבאה.</span></footer>
    </div>
    {selected && <JobDetails job={selected} jobs={visible} busy={saving} error={error} message={saveMessage} update={update}
      note={noteDrafts[selected.id] ?? selected.personal_note}
      onNoteChange={value => setNoteDrafts(drafts => ({ ...drafts, [selected.id]: value }))}
      onNoteSaved={() => setNoteDrafts(drafts => { const next = { ...drafts }; delete next[selected.id]; return next; })}
      onNavigate={open} onClose={() => setSelectedId(null)}/>}
  </div>;
}
