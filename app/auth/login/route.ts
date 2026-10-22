import { authConfigured, supabase } from "@/lib/auth";
import { NextResponse } from "next/server";
export async function GET() {
  if (!authConfigured()) return NextResponse.json({ error: "יש להגדיר התחברות Google לפני השימוש" }, { status: 503 });
  const client = await supabase();
  const { data, error } = await client.auth.signInWithOAuth({ provider: "google", options: { redirectTo: `${process.env.APP_URL}/auth/callback`, queryParams: { prompt: "select_account" } } });
  if (error || !data.url) return NextResponse.redirect(new URL("/login?error=login", process.env.APP_URL));
  return NextResponse.redirect(data.url);
}
