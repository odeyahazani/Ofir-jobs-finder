import { access, sameOrigin } from "@/lib/auth";
import { updateJob } from "@/lib/db";

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  if (!(await access())) return Response.json({ error: "נדרשת התחברות" }, { status: 401 });
  if (!(await sameOrigin(request))) return Response.json({ error: "בקשה ממקור לא מורשה" }, { status: 403 });
  const { id } = await context.params;
  if (!/^[a-f0-9]{24}$/.test(id)) return Response.json({ error: "מזהה משרה לא תקין" }, { status: 400 });
  const text = await request.text();
  if (text.length > 12000) return Response.json({ error: "הבקשה ארוכה מדי" }, { status: 413 });
  let body: Record<string, unknown>;
  try { body = JSON.parse(text); } catch { return Response.json({ error: "תוכן לא תקין" }, { status: 400 }); }
  if (!body || typeof body !== "object" || Array.isArray(body)) return Response.json({ error: "תוכן לא תקין" }, { status: 400 });
  const allowed = ["fit", "familiar", "application_status", "personal_note"];
  if (!Object.keys(body).length || Object.keys(body).some(key => !allowed.includes(key)) ||
      ("fit" in body && (typeof body.fit !== "string" || !["unrated", "yes", "maybe", "no"].includes(body.fit))) ||
      ("application_status" in body && (typeof body.application_status !== "string" || !["not_applied", "planned", "applied", "interviewing", "rejected", "withdrawn"].includes(body.application_status))) ||
      ("familiar" in body && typeof body.familiar !== "boolean") ||
      ("personal_note" in body && (typeof body.personal_note !== "string" || body.personal_note.length > 2000))) {
    return Response.json({ error: "אחד השדות אינו תקין" }, { status: 400 });
  }
  const patch = Object.fromEntries(Object.entries(body).map(([key, value]) => [key, typeof value === "boolean" ? Number(value) : value])) as Record<string, string | number>;
  const changed = updateJob(id, patch);
  return changed ? Response.json({ ok: true }) : Response.json({ error: "המשרה לא נמצאה" }, { status: 404 });
}
