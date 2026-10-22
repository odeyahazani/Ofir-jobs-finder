import { authConfigured } from "@/lib/auth";
import { ArrowUpLeft, Sparkles } from "lucide-react";
export const dynamic = "force-dynamic";
export default async function Login({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <main className="login-shell"><div className="login-card"><div className="brand"><span className="brand-mark">o<span>f</span></span><span>ofir<span className="brand-dot">.</span></span></div>
    <span className="eyebrow"><Sparkles size={15} /> הצעד הבא בקריירה שלך</span>
    <h1>הנדסה. פיזיקה.<br /><em>הזדמנויות חדשות.</em></h1>
    <p>משרות שנבחרו לפי מה שמעניין אותך, במקום אחד אישי.</p>
    {error && <p role="alert" className="error">ההתחברות לא הושלמה או שהחשבון אינו מורשה.</p>}
    {authConfigured() ? <a className="primary-button" href="/auth/login">המשך באמצעות Google <ArrowUpLeft size={18} /></a> : <div className="notice">הכניסה עדיין לא הוגדרה. יש לחבר את Google ולהגדיר את החשבון המורשה לפני פתיחת האתר לשימוש.</div>}
    <small>מרחב אישי לאופיר כהן</small>
  </div><div className="login-art" aria-hidden="true"><div className="orbit one" /><div className="orbit two" /><div className="orbit three" /><span>YOUR NEXT<br />GREAT THING.</span></div></main>;
}
