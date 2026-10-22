import { authConfigured, sameOrigin, supabase } from "@/lib/auth";
import { NextResponse } from "next/server";
export async function POST(request: Request) {
  if (!(await sameOrigin(request))) return new Response("Forbidden", { status: 403 });
  if (authConfigured()) await (await supabase()).auth.signOut();
  return NextResponse.redirect(new URL("/login", process.env.APP_URL || request.url), 303);
}
