"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUpLeft, Bookmark, BriefcaseBusiness, Check, CheckCheck, ChevronLeft, ChevronRight, ExternalLink, MapPin, X } from "lucide-react";
import { currentMatch } from "@/lib/matching";
import type { ApplicationStatus, Fit, Job } from "@/lib/types";
import { applicationLabels, CompanyMark, date, fitLabels, MatchScore, MatchingBadge, safeLink, VerificationBadge } from "./job-ui";

export type JobPatch = Partial<Pick<Job, "fit" | "familiar" | "application_status" | "personal_note">>;
export type UpdateJob = (job: Job, patch: JobPatch) => Promise<boolean>;
const tabs = [{ id: "source", label: "תיאור המשרה" }, { id: "fit", label: "התאמה ופערים" }, { id: "tracking", label: "המעקב שלי" }] as const;
type DetailTab = typeof tabs[number]["id"];
const breakdownLabels: Record<string, string> = { professional: "משימות התפקיד", experience: "רמת ניסיון", technical: "כישורים טכניים", sector: "תחום החברה", location: "מיקום ונסיעה", growth: "התפתחות" };
const maximums: Record<string, number> = { professional: 30, experience: 25, technical: 20, sector: 10, location: 10, growth: 5 };

function SourceText({ text }: { text: string }) {
  // Keep the source wording; React escapes it. No inferred requirements or generated HTML.
  const blocks = text.split(/\n+/).filter(block => block.trim());
  return <div className="source-copy" dir="auto">{blocks.map((block, index) => {
    const value = block.trim();
    const heading = /^(description|requirements|responsibilities|qualifications|position responsibilities|what you.ll do|what you bring|about the role|תיאור התפקיד|דרישות|תחומי אחריות)\s*:?$/i.test(value);
    return heading ? <h4 key={index} dir="auto">{value}</h4> : <p key={index} dir="auto">{value}</p>;
  })}</div>;
}

export default function JobDetails({ job, jobs, busy, error, message, note, onNoteChange, onNoteSaved, onClose, onNavigate, update }: {
  job: Job; jobs: Job[]; busy: boolean; error: string; message: string; note: string;
  onNoteChange: (value: string) => void; onNoteSaved: () => void; onClose: () => void; onNavigate: (job: Job) => void; update: UpdateJob;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const outsideStart = useRef(false);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [tab, setTab] = useState<DetailTab>("source");
  const dirty = note !== job.personal_note;
  const index = jobs.findIndex(item => item.id === job.id);
  const saved = job.fit === "yes" || job.application_status === "planned";
  const sourceUrl = safeLink(job.url);
  const profileMatch = currentMatch(job);
  const scoreMaximums = profileMatch ? { professional: 45, technical: 35, sector: 20 } as Record<string, number> : maximums;

  useEffect(() => {
    const dialog = dialogRef.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    dialog?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = overflow;
      if (opener?.isConnected) opener.focus();
      else document.getElementById("main-content")?.focus();
    };
  }, []);
  useEffect(() => { scrollRef.current?.scrollTo({ top: 0 }); }, [job.id, tab]);

  function changeTab(next: DetailTab) { setTab(next); }
  async function saveNote() { if (await update(job, { personal_note: note })) onNoteSaved(); }

  return <dialog ref={dialogRef} className="job-dialog" aria-labelledby="detail-title" onCancel={event => { event.preventDefault(); onClose(); }}
    onKeyDown={event => {
      if (event.key !== "Tab") return;
      const elements = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]'))
        .filter(element => element.tabIndex >= 0 && element.getClientRects().length > 0);
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }}
    onPointerDown={event => { outsideStart.current = event.target === event.currentTarget; }}
    onPointerCancel={() => { outsideStart.current = false; }}
    onClick={event => { if (event.target === event.currentTarget && outsideStart.current) onClose(); outsideStart.current = false; }}>
    <div className="detail-panel">
      <div className="detail-topbar"><span className="detail-context">פרטי ההזדמנות</span><div className="detail-topbar-actions">
        {index >= 0 && <><span className="detail-position"><bdi>{index + 1} / {jobs.length}</bdi></span><button className="icon-button" aria-label="המשרה הקודמת" disabled={busy || index === 0} onClick={() => onNavigate(jobs[index - 1])}><ChevronRight size={18}/></button><button className="icon-button" aria-label="המשרה הבאה" disabled={busy || index === jobs.length - 1} onClick={() => onNavigate(jobs[index + 1])}><ChevronLeft size={18}/></button><span className="toolbar-divider"/></>}
        <button autoFocus className="icon-button close-modal" aria-label="סגירה" onClick={onClose}><X size={20}/></button>
      </div></div>
      <header className="detail-header">
        <div className="company-line"><CompanyMark name={job.company}/><span dir="auto">{job.company}</span><VerificationBadge job={job}/></div>
        <h2 id="detail-title" dir="auto">{job.title}</h2>
        <div className="detail-meta"><span><MapPin size={15}/><bdi>{job.location || "מיקום לא ידוע"}</bdi></span><span><BriefcaseBusiness size={15}/><bdi>{job.work_model || "סוג העסקה לא צוין"}</bdi></span><span>{job.experience || "ניסיון לא צוין"}</span></div>
        <div className="detail-status-line"><span className="status-caption">הסטטוס שלי</span><button className="status-shortcut" onClick={() => changeTab("tracking")}>{applicationLabels[job.application_status]}<ChevronLeft size={14}/></button>{dirty && <span className="draft-indicator">הערה בטיוטה</span>}</div>
      </header>
      <div className="detail-tabs" role="tablist" aria-label="מידע על המשרה" onKeyDown={event => {
        const current = tabs.findIndex(item => item.id === tab);
        let next = current;
        if (event.key === "ArrowLeft") next = (current + 1) % tabs.length;
        else if (event.key === "ArrowRight") next = (current + tabs.length - 1) % tabs.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = tabs.length - 1;
        else return;
        event.preventDefault(); setTab(tabs[next].id); tabRefs.current[next]?.focus();
      }}>{tabs.map((item, i) => <button key={item.id} ref={element => { tabRefs.current[i] = element; }} role="tab" id={`detail-tab-${item.id}`} aria-controls={`detail-section-${item.id}`} aria-selected={tab === item.id} tabIndex={tab === item.id ? 0 : -1} onClick={() => changeTab(item.id)}>{item.label}{item.id === "tracking" && dirty && <span className="draft-dot" aria-label="טיוטה לא נשמרה"/>}</button>)}</div>
      <div className="detail-scroll" ref={scrollRef}>
        <section role="tabpanel" id="detail-section-source" aria-labelledby="detail-tab-source" hidden={tab !== "source"} tabIndex={0}>
          <div className="section-kicker"><span>מתוך אתר החברה</span><span>אימות אחרון: {date(job.last_verified_at)}</span></div>
          {job.description.trim() ? <SourceText text={job.description}/> : <p className="notice">תיאור המשרה אינו זמין. אפשר לבדוק אותו באתר החברה.</p>}
          <details className="source-dates"><summary>פרטי המקור ותאריכים</summary><dl><div><dt>תאריך פרסום</dt><dd>{date(job.published_at)}</dd></div><div><dt>עדכון במקור</dt><dd>{date(job.updated_at)}</dd></div><div><dt>גילוי במאגר</dt><dd>{date(job.first_seen_at)}</dd></div><div><dt>אימות אחרון</dt><dd>{date(job.last_verified_at)}</dd></div></dl></details>
        </section>
        <section role="tabpanel" id="detail-section-fit" aria-labelledby="detail-tab-fit" hidden={tab !== "fit"} tabIndex={0}>
          <div className="fit-summary"><MatchScore job={job}/><div><MatchingBadge job={job}/><h3>מה עומד מאחורי ההתאמה?</h3><p>הציון מסייע לתעדף. תנאי הסף וזמינות המשרה נבדקים בנפרד.</p></div></div>
          {profileMatch && <p className="notice">מבוסס על תארים, פרויקטי SFDI ופלואורסצנציה ומעבדות. לא מתועד ניסיון הנדסי תעשייתי. הציון הוא כלי לתעדוף ואינו תחזית קבלה לעבודה.</p>}
          {!profileMatch && <p className="notice">הערכה קודמת: המשרה עדיין לא נבדקה מול הפרופיל המפורט של אופיר.</p>}
          {!job.eligible && <div className="notice warning-notice"><strong>דרישות לבדיקה</strong><p>{job.exclusion_reason || "המשרה לא עברה את תנאי הסף הראשוניים."}</p></div>}
          <div className="insight-section"><h3><Check size={18}/>נקודות חיבור לרקע שלך</h3>{job.reasons.length ? <ul>{job.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul> : <p>טרם זוהו נקודות התאמה מפורשות.</p>}</div>
          <div className="insight-section"><h3>פערים ומה כדאי לבדוק</h3>{job.gaps.length ? <ul>{job.gaps.map(gap => <li key={gap}>{gap}</li>)}</ul> : <p>לא תועדו פערים. מומלץ לקרוא את הדרישות במקור.</p>}</div>
          {profileMatch && job.match_details.evidence.length > 0 && <div className="insight-section evidence-list"><h3>הראיות מאחורי ההתאמה</h3>{job.match_details.evidence.map(item => <details key={item.capability} className="evidence-item"><summary>{item.label}<span>{item.level === "academic" ? "רקע אקדמי" : "ניסיון מפרויקט"}</span></summary><div>{item.profile_evidence.map((proof, i) => <p key={i}>{proof}</p>)}<span className="evidence-caption">הניסוח במשרה</span><blockquote dir="auto">{item.job_quote}</blockquote></div></details>)}</div>}
          {profileMatch && job.match_details.requirements.length > 0 && <details className="requirement-details"><summary>דרישות שזוהו במקור</summary>{job.match_details.requirements.map((item, i) => <div key={i}><span className={`badge ${item.optional ? "neutral" : "warning"}`}>{item.optional ? "יתרון לפי הניסוח" : "נדרש לפי הניסוח"}</span><blockquote dir="auto">{item.quote}</blockquote></div>)}<p>הפענוח אוטומטי. במקרה של ניסוח עמום, יש לבדוק את הסעיף המלא באתר החברה.</p></details>}
          <details className="score-details"><summary>פירוט ציון ההתאמה</summary><div className="score-breakdown">{Object.entries(job.breakdown).map(([key, value]) => <div key={key}><div><span>{breakdownLabels[key] || key}</span><strong><bdi>{value}/{scoreMaximums[key] || 100}</bdi></strong></div><meter min={0} max={scoreMaximums[key] || 100} value={value} aria-label={breakdownLabels[key] || key}/></div>)}</div></details>
        </section>
        <section role="tabpanel" id="detail-section-tracking" aria-labelledby="detail-tab-tracking" hidden={tab !== "tracking"} tabIndex={0}>
          <div className="tracking-heading"><h3>ההתרשמות וההתקדמות שלך</h3><p>הסימונים נשמרים אוטומטית. הערות נשמרות בלחיצה על שמירה.</p></div>
          <div className="tracking-fields"><label>מצב מועמדות<select aria-label="מצב מועמדות" value={job.application_status} disabled={busy} onChange={e => update(job, { application_status: e.target.value as ApplicationStatus })}>{Object.entries(applicationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>מידת ההתאמה בעיניי<select aria-label="מידת ההתאמה בעיניי" value={job.fit} disabled={busy} onChange={e => update(job, { fit: e.target.value as Fit })}>{Object.entries(fitLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
          <label className="familiar-toggle"><span><strong>המשרה כבר מוכרת לי</strong><small>למעקב אישי אחר משרות שכבר ראית</small></span><input type="checkbox" checked={job.familiar} disabled={busy} aria-label="המשרה כבר מוכרת לי" onChange={e => update(job, { familiar: e.target.checked })}/></label>
          <div className="note-editor"><label htmlFor="personal-note">הערה אישית <span>{dirty ? "טיוטה לא נשמרה" : ""}</span></label><textarea id="personal-note" aria-label="הערה אישית" dir="auto" maxLength={2000} disabled={busy} value={note} placeholder="מה חשוב לזכור? איש קשר, שאלות או הצעד הבא…" onChange={e => onNoteChange(e.target.value)}/><div><span>{note.length}/2000</span><button className="secondary-button" disabled={busy || !dirty} onClick={saveNote}><CheckCheck size={16}/>שמירת הערה</button></div><p className="draft-help">טיוטה נשמרת במרחב הזה עד לרענון הדף. לחצו על שמירה כדי לשמור אותה במאגר.</p></div>
        </section>
      </div>
      <footer className="detail-footer">
        {error && <p className="error" role="alert">{error} — אפשר לנסות שוב.</p>}
        <div className="detail-footer-actions">{sourceUrl && <a className="primary-button" href={sourceUrl} target="_blank" rel="noreferrer">{job.status === "open" ? "למשרה באתר החברה" : "בדיקת המשרה במקור"}<ArrowUpLeft size={17}/></a>}<button className={`secondary-button save-job ${saved ? "is-saved" : ""}`} disabled={busy || job.application_status === "planned"} aria-pressed={saved} onClick={() => update(job, { fit: saved ? "unrated" : "yes" })}><Bookmark size={17}/>{saved ? "שמורה" : "שמירה להמשך"}</button><span className="detail-save-state" role="status">{busy ? "שומר…" : message}</span></div>
        <p className="source-link-hint">פתיחת המקור אינה מסמנת שהוגשה מועמדות <ExternalLink size={11}/></p>
      </footer>
    </div>
  </dialog>;
}
