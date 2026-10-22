"use client";
export default function Error({ reset }: { reset: () => void }) {
  return <main className="login-shell"><div className="login-card"><h1>לא הצלחנו לטעון את הנתונים</h1>
    <p>אפשר לנסות שוב בעוד רגע. אם זו ההפעלה הראשונה, יש להשלים את הגדרת מסד הנתונים והחשבון המורשה.</p>
    <button className="primary-button" onClick={reset}>נסה שוב</button></div></main>;
}
