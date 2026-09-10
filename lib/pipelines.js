export const STORAGE_KEY = "ocr-flow.pipelines";
export const PIPELINES_CHANGED = "ocr-flow.pipelines-changed";

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
  const pipelines = loadPipelines();
  const existing = pipeline.id ? pipelines.find((item) => item.id === pipeline.id) : null;
  if (pipeline.id && !existing) throw new Error("Пайплайн удалён. Создайте новый пайплайн.");
  const now = new Date().toISOString();
  const stored = { ...pipeline, id: existing?.id || `pl_${crypto.randomUUID()}`, createdAt: existing?.createdAt || now, updatedAt: now };
  writePipelines(existing ? pipelines.map((item) => item.id === stored.id ? stored : item) : [stored, ...pipelines]);
  return stored;
}

function writePipelines(pipelines) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(pipelines));
  } catch {
    throw new Error("Не удалось сохранить изменения. Проверьте доступ к хранилищу браузера.");
  }
  window.dispatchEvent(new Event(PIPELINES_CHANGED));
}

export function deletePipeline(id) {
  writePipelines(loadPipelines().filter((pipeline) => pipeline.id !== id));
}

export function describePipeline(pipeline) {
  const ocr = pipeline.source !== "scans" ? "Прямое извлечение текста" : pipeline.ocr?.provider === "litellm" ? `Vision · ${pipeline.ocr.model}` : `OCR-сервис · ${pipeline.ocr?.url ?? ""}`;
  const extraction = !pipeline.extraction ? "Ответ Vision-модели" : pipeline.extraction.mode === "prompt" ? `Промпт · ${pipeline.extraction.model}` : `${pipeline.extraction.fields.length} полей · ${pipeline.extraction.model}`;
  return { ocr, extraction };
}
