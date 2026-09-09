import { NextResponse } from "next/server";

function config() {
  const baseUrl = process.env.LITELLM_BASE_URL?.replace(/\/$/, "");
  const apiKey = process.env.LITELLM_API_KEY;
  if (!baseUrl) throw new Error("LITELLM_BASE_URL не настроен");
  return { baseUrl, apiKey };
}

export async function GET() {
  try {
    const { baseUrl, apiKey } = config();
    const response = await fetch(`${baseUrl}/v1/models`, {
      headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`LiteLLM вернул ${response.status}`);
    const payload = await response.json() as { data?: Array<{ id?: string }> };
    const models = [...new Set((payload.data ?? []).map((item) => item.id).filter((id): id is string => Boolean(id)))].sort();
    return NextResponse.json({ models });
  } catch (error) {
    return NextResponse.json({ models: [], error: error instanceof Error ? error.message : "Не удалось получить модели LiteLLM" }, { status: 503 });
  }
}
