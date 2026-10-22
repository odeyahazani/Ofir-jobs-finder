import "server-only";
import { createServerClient } from "@supabase/ssr";
import { cookies, headers } from "next/headers";

export function authConfigured() {
  return Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY && process.env.OFIR_ALLOWED_EMAIL && process.env.APP_URL);
}

export async function supabase() {
  const jar = await cookies();
  return createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!, {
    cookies: {
      getAll: () => jar.getAll(),
      setAll: values => {
        try { values.forEach(({ name, value, options }) => jar.set(name, value, options)); }
        catch { /* Server components cannot refresh cookies; routes handle updates. */ }
      },
    },
  });
}

export async function access(): Promise<"local" | "google" | null> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("host")?.split(":")[0];
  const forwardedHost = requestHeaders.get("x-forwarded-host")?.split(":")[0];
  if (process.env.NODE_ENV !== "production" && process.env.LOCAL_DEV_MODE === "1" &&
    ["localhost", "127.0.0.1"].includes(host || "") && (!forwardedHost || forwardedHost === host)) return "local";
  if (!authConfigured()) return null;
  try {
    const client = await supabase();
    const { data: { user }, error } = await client.auth.getUser();
    if (error || !user || !user.email_confirmed_at || user.app_metadata?.provider !== "google" || user.email?.toLowerCase() !== process.env.OFIR_ALLOWED_EMAIL?.toLowerCase()) return null;
    return "google";
  } catch { return null; }
}

export async function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  // Browser mutations must have a valid same-origin header, including authenticated local development.
  const expected = process.env.APP_URL || (process.env.NODE_ENV !== "production" ? new URL(request.url).origin : undefined);
  return Boolean(origin && expected && origin === new URL(expected).origin);
}
