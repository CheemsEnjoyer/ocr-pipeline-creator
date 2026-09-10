import { documentHeaders, documentStorage, storageError } from "@/lib/documents";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const page = Math.max(0, Math.floor(Number(searchParams.get("page")) || 0));
    const { db } = documentStorage();
    const { results } = await db.prepare(`SELECT id, filename, mime_type, size, pipeline_name, created_at, updated_at
      FROM documents ORDER BY created_at DESC, id DESC LIMIT 51 OFFSET ?`).bind(page * 50).all();
    return Response.json({ documents: results.slice(0, 50), hasMore: results.length > 50 }, { headers: documentHeaders });
  } catch { return storageError(); }
}
