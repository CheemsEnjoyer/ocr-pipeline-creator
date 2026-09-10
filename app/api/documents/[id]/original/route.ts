import { documentHeaders, documentStorage, storageError } from "@/lib/documents";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await context.params;
    const { db, bucket } = documentStorage();
    const row = await db.prepare("SELECT filename, mime_type, original_key FROM documents WHERE id = ?").bind(id).first<{ filename: string; mime_type: string; original_key: string }>();
    if (!row) return Response.json({ error: "Документ не найден" }, { status: 404 });
    const object = await bucket.get(row.original_key);
    if (!object) return Response.json({ error: "Исходный файл не найден" }, { status: 404 });
    // Only passive formats may render inline; HTML and SVG are always downloaded.
    const inline = /^(application\/pdf|image\/(png|jpeg|gif|webp|avif|bmp))$/.test(row.mime_type) && !new URL(request.url).searchParams.has("download");
    const encodedName = encodeURIComponent(row.filename).replace(/['()*]/g, (character) => `%${character.charCodeAt(0).toString(16)}`);
    return new Response(object.body, { headers: {
      ...documentHeaders,
      "Content-Type": row.mime_type,
      "Content-Length": String(object.size),
      "Content-Disposition": `${inline ? "inline" : "attachment"}; filename*=UTF-8''${encodedName}`,
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "sandbox",
    } });
  } catch { return storageError(); }
}
