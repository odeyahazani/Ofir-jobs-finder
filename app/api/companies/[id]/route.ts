import { access, sameOrigin } from "@/lib/auth";
import { setMonitor } from "@/lib/db";
export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!(await access())) return Response.json({ error: "נדרשת התחברות" }, { status: 401 });
  if (!(await sameOrigin(request))) return Response.json({ error: "בקשה ממקור לא מורשה" }, { status: 403 });
  const { id } = await params;
  if (!/^[a-f0-9]{16}$/.test(id)) return Response.json({ error: "מזהה חברה לא תקין" }, { status: 400 });
  try {
    const raw = await request.text();
    if (raw.length > 500) return Response.json({ error: "בקשה גדולה מדי" }, { status: 413 });
    const body = JSON.parse(raw);
    if (!body || typeof body !== "object" || Object.keys(body).length !== 1 || typeof body.enabled !== "boolean") return Response.json({ error: "שדות לא תקינים" }, { status: 400 });
    await setMonitor(id, body.enabled);
    return Response.json({ ok: true });
  } catch { return Response.json({ error: "המעקב לא עודכן; יש לוודא שקיים קישור קריירה" }, { status: 400 }); }
}
