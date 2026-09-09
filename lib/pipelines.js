const STORAGE_KEY = "ocr-flow.pipelines";

export function loadPipelines() {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function savePipeline(pipeline) {
  const stored = { ...pipeline, id: `pl_${Date.now().toString(36)}`, createdAt: new Date().toISOString() };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([stored, ...loadPipelines()]));
  } catch {
    return stored;
  }
  return stored;
}

export function describePipeline(pipeline) {
  const ocr = pipeline.source !== "scans" ? "Прямое извлечение текста" : pipeline.ocr?.provider === "litellm" ? `Vision · ${pipeline.ocr.model}` : `OCR-сервис · ${pipeline.ocr?.url ?? ""}`;
  const extraction = !pipeline.extraction ? "Ответ Vision-модели" : pipeline.extraction.mode === "prompt" ? `Промпт · ${pipeline.extraction.model}` : `${pipeline.extraction.fields.length} полей · ${pipeline.extraction.model}`;
  return { ocr, extraction };
}
