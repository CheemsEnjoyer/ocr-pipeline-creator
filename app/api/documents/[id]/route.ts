import { documentHeaders, documentStorage, storageError } from "@/lib/documents";
import { z } from "zod";

type Context = { params: Promise<{ id: string }> };

export async function GET(_request: Request, context: Context) {
  try {
    const { id } = await context.params;
    const { db } = documentStorage();
    const document = await db.prepare("SELECT id, filename, mime_type, size, pipeline_name, text, result, fields, created_at, updated_at, revision FROM documents WHERE id = ?").bind(id).first<{ fields: string }>();
    if (!document) return Response.json({ error: "Документ не найден" }, { status: 404 });
    return Response.json({ document: { ...document, fields: JSON.parse(document.fields) } }, { headers: documentHeaders });
  } catch { return storageError(); }
}

export async function PATCH(request: Request, context: Context) {
  let raw;
  try { raw = await request.json(); } catch { return Response.json({ error: "Некорректный JSON" }, { status: 400 }); }
  const parsed = z.object({ fields: z.record(z.unknown()), revision: z.number().int().nonnegative() }).safeParse(raw);
  if (!parsed.success || JSON.stringify(parsed.data.fields).length > 1_000_000) {
    return Response.json({ error: "Некорректные поля документа" }, { status: 400 });
  }
  const payload = parsed.data;
  try {
    const { id } = await context.params;
    const { db } = documentStorage();
    const now = new Date().toISOString();
    const outcome = await db.prepare("UPDATE documents SET fields = ?, updated_at = ?, revision = revision + 1 WHERE id = ? AND revision = ?")
      .bind(JSON.stringify(payload.fields), now, id, payload.revision).run();
    if (!outcome.meta.changes) return Response.json({ error: "Документ изменился в другой вкладке. Откройте его заново перед сохранением." }, { status: 409 });
    return Response.json({ revision: payload.revision + 1, updated_at: now }, { headers: documentHeaders });
  } catch { return storageError(); }
}
