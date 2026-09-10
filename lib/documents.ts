import { env } from "cloudflare:workers";

export function documentStorage() {
  const bindings = env as unknown as { DB?: D1Database; BUCKET?: R2Bucket };
  if (!bindings.DB || !bindings.BUCKET) throw new Error("Хранилище документов недоступно. Настройте базу и файловое хранилище.");
  return { db: bindings.DB, bucket: bindings.BUCKET };
}

export function resultFields(result: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(result);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    return { result: parsed };
  } catch { return {}; }
}

export async function saveDocument(file: File, pipelineName: string, text: string, result: string) {
  const { db, bucket } = documentStorage();
  const id = crypto.randomUUID();
  const originalKey = `documents/${id}/original`;
  const now = new Date().toISOString();
  await bucket.put(originalKey, file.stream(), { httpMetadata: { contentType: file.type || "application/octet-stream" } });
  try {
    await db.prepare(`INSERT INTO documents (id, filename, mime_type, size, pipeline_name, original_key, text, result, fields, created_at, updated_at, revision)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`).bind(id, file.name, file.type || "application/octet-stream", file.size, pipelineName, originalKey, text, result, JSON.stringify(resultFields(result)), now, now).run();
  } catch (error) {
    await bucket.delete(originalKey);
    throw error;
  }
  return id;
}

export const documentHeaders = { "Cache-Control": "no-store" };
export function storageError() {
  return Response.json({ error: "Не удалось обратиться к истории документов. Проверьте доступность хранилища и повторите попытку." }, { status: 503, headers: documentHeaders });
}
