import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  try {
    const baseUrl = process.env.LITELLM_BASE_URL?.replace(/\/$/, "");
    const apiKey = process.env.LITELLM_API_KEY;
    if (!baseUrl) throw new Error("LITELLM_BASE_URL не настроен");
    const body = await request.json() as { model?: string; prompt?: string; fields?: Array<{ name: string; description: string }>; documentText?: string; maxTokens?: number };
    if (!body.model || !body.prompt) return NextResponse.json({ error: "Модель и промпт обязательны" }, { status: 400 });
    const schema = Object.fromEntries((body.fields ?? []).map((field) => [field.name, { type: "string", description: field.description }]));
    const response = await fetch(`${baseUrl}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
      body: JSON.stringify({
        model: body.model,
        temperature: 0,
        max_tokens: Math.max(1, Math.min(Number(body.maxTokens) || 2048, 128000)),
        response_format: { type: "json_object" },
        messages: [
          { role: "system", content: `${body.prompt}\nВерни JSON с полями по схеме: ${JSON.stringify(schema)}` },
          { role: "user", content: body.documentText || "Текст документа появится после этапа OCR/извлечения." },
        ],
      }),
    });
    const payload = await response.json() as { choices?: Array<{ message?: { content?: string } }>; error?: { message?: string } };
    if (!response.ok) throw new Error(payload.error?.message || `LiteLLM вернул ${response.status}`);
    return NextResponse.json({ model: body.model, result: payload.choices?.[0]?.message?.content ?? "" });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Ошибка вызова LiteLLM" }, { status: 502 });
  }
}
