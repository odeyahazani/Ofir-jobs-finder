import { access, sameOrigin } from "@/lib/auth";
import { importDiscoveries } from "@/lib/db";
import { parseGrowth } from "@/lib/discovery";
export async function POST(request: Request) {
  if (!(await access())) return Response.json({ error: "נדרשת התחברות" }, { status: 401 });
  if (!(await sameOrigin(request))) return Response.json({ error: "בקשה ממקור לא מורשה" }, { status: 403 });
  const body = await request.text();
  if (body.length > 500_000) return Response.json({ error: "הקובץ גדול מדי" }, { status: 413 });
  let payload;
  try { payload = parseGrowth(body); } catch (error) { return Response.json({ error: error instanceof Error ? error.message : "קובץ לא תקין" }, { status: 400 }); }
  try { return Response.json(await importDiscoveries(payload)); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "הייבוא נכשל" }, { status: 503 }); }
}
