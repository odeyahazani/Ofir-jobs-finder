import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Ofir · ההזדמנות הבאה שלך", description: "חיפוש משרות אישי לאופיר — הנדסה, פיזיקה ומה שביניהם", robots: { index: false, follow: false } };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="he" dir="rtl"><body>{children}</body></html>;
}
