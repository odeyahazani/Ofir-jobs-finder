import { supabase, authConfigured } from "@/lib/auth";
import { NextResponse } from "next/server";
export async function GET(request: Request) {
  const origin = process.env.APP_URL;
  if (!origin || !authConfigured()) return NextResponse.json({ error: "Authentication is not configured" }, { status: 503 });
  const code = new URL(request.url).searchParams.get("code");
  if (code) {
    const client = await supabase();
    const { data, error } = await client.auth.exchangeCodeForSession(code);
    if (!error && data.user?.email_confirmed_at && data.user.app_metadata?.provider === "google" && data.user.email?.toLowerCase() === process.env.OFIR_ALLOWED_EMAIL?.toLowerCase()) return NextResponse.redirect(new URL("/", origin));
    await client.auth.signOut();
  }
  return NextResponse.redirect(new URL("/login?error=denied", origin));
}
