import { NextRequest, NextResponse } from "next/server";
import { documentStorage, saveDocument } from "@/lib/documents";

type Pipeline = {
  name?: string;
  source?: "scans" | "document";
  ocr?: { provider: "litellm" | "service"; model?: string; prompt?: string; url?: string } | null;
  extraction?: { mode: "prompt" | "fields"; model: string; max_tokens: number; prompt?: string; fields?: Array<{ name: string; description: string }> } | null;
};

function litellm() {
  const baseUrl = process.env.LITELLM_BASE_URL?.replace(/\/$/, "");
  if (!baseUrl) throw new Error("LITELLM_BASE_URL не настроен");
  return { baseUrl, apiKey: process.env.LITELLM_API_KEY };
}

async function complete(body: Record<string, unknown>) {
  const { baseUrl, apiKey } = litellm();
  const response = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as { choices?: Array<{ message?: { content?: string } }>; error?: { message?: string } };
  if (!response.ok) throw new Error(payload.error?.message || `LiteLLM вернул ${response.status}`);
  return payload.choices?.[0]?.message?.content ?? "";
}

function toDataUrl(bytes: ArrayBuffer, mimeType: string) {
  const chunk = 0x8000;
  const view = new Uint8Array(bytes);
  let binary = "";
  for (let offset = 0; offset < view.length; offset += chunk) binary += String.fromCharCode(...view.subarray(offset, offset + chunk));
  return `data:${mimeType || "application/octet-stream"};base64,${btoa(binary)}`;
}

async function recognize(pipeline: Pipeline, file: File) {
  if (pipeline.source !== "scans") return (await file.text()).trim();

  if (pipeline.ocr?.provider === "service") {
    const form = new FormData();
    form.append("file", file, file.name);
    const response = await fetch(pipeline.ocr.url as string, { method: "POST", body: form });
    const raw = await response.text();
    if (!response.ok) throw new Error(`OCR-сервис вернул ${response.status}`);
    try {
      const parsed = JSON.parse(raw) as { text?: string; result?: string };
      return parsed.text ?? parsed.result ?? raw;
    } catch {
      return raw;
    }
  }

  return complete({
    model: pipeline.ocr?.model,
    temperature: 0,
    max_tokens: 4096,
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: pipeline.ocr?.prompt || "Распознай весь текст на изображении." },
          { type: "image_url", image_url: { url: toDataUrl(await file.arrayBuffer(), file.type) } },
        ],
      },
    ],
  });
}

async function extract(extraction: NonNullable<Pipeline["extraction"]>, documentText: string) {
  const instruction =
    extraction.mode === "prompt"
      ? extraction.prompt || ""
      : `Извлеки из текста документа значения полей и верни JSON строго по схеме: ${JSON.stringify(
          Object.fromEntries((extraction.fields ?? []).map((field) => [field.name, { type: "string", description: field.description }])),
        )}`;

  return complete({
    model: extraction.model,
    temperature: 0,
    max_tokens: Math.max(1, Math.min(Number(extraction.max_tokens) || 2048, 128000)),
    response_format: { type: "json_object" },
    messages: [
      { role: "system", content: `${instruction}\nОтвечай только валидным JSON без пояснений.` },
      { role: "user", content: documentText },
    ],
  });
}

export async function POST(request: NextRequest) {
  try {
    const form = await request.formData();
    const file = form.get("file");
    const rawPipeline = form.get("pipeline");
    if (!(file instanceof File)) return NextResponse.json({ error: "Файл не передан" }, { status: 400 });
    if (file.size > 20 * 1024 * 1024) return NextResponse.json({ error: "Максимальный размер файла — 20 МБ" }, { status: 413 });
    if (typeof rawPipeline !== "string") return NextResponse.json({ error: "Пайплайн не передан" }, { status: 400 });

    const pipeline = JSON.parse(rawPipeline) as Pipeline;
    documentStorage();
    const text = await recognize(pipeline, file);
    const result = pipeline.extraction ? await extract(pipeline.extraction, text) : text;

    const documentId = await saveDocument(file, pipeline.name || "Без названия", text, result);
    return NextResponse.json({ file: file.name, text, result, documentId });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Не удалось обработать документ" }, { status: 502 });
  }
}
