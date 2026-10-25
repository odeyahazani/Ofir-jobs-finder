import type { Metadata } from "next";
import "./globals.css";
import localFont from "next/font/local";
const heebo = localFont({ src: "./fonts/Heebo-Variable.ttf", weight: "100 900", display: "swap", variable: "--font-heebo" });
export const metadata: Metadata = { title: "Ofir · ההזדמנות הבאה שלך", description: "חיפוש משרות אישי לאופיר — הנדסה, פיזיקה ומה שביניהם", robots: { index: false, follow: false } };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="he" dir="rtl"><body className={heebo.variable}>{children}</body></html>;
}
