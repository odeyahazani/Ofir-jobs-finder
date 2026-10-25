import { authConfigured } from "@/lib/auth";
import { ArrowUpLeft, Sparkles } from "lucide-react";
export const dynamic = "force-dynamic";
export default async function Login({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <main className="login-shell"><div className="login-card"><div className="brand"><span className="brand-mark">of</span><span>ofir<span className="brand-dot">.</span></span></div>
    <span className="eyebrow"><Sparkles size={15} /> חיפוש העבודה של אופיר</span>
    <h1>הנדסה. פיזיקה.<br /><em>הזדמנויות חדשות.</em></h1>
    <p>גילוי משרות, בחינת התאמה ומעקב מועמדויות במקום אחד.</p>
    {error && <p role="alert" className="error">ההתחברות לא הושלמה או שהחשבון אינו מורשה.</p>}
    {authConfigured() ? <a className="primary-button" href="/auth/login">המשך באמצעות Google <ArrowUpLeft size={18} /></a> : <div className="notice">הכניסה עדיין לא הוגדרה. יש לחבר את Google ולהגדיר את החשבון המורשה לפני פתיחת האתר לשימוש.</div>}
    <small>מרחב אישי לאופיר כהן</small>
  </div></main>;
}
