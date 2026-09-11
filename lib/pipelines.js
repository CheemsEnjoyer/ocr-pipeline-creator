export const STORAGE_KEY = "ocr-flow.pipelines";
export const PIPELINES_CHANGED = "ocr-flow.pipelines-changed";
const listeners = new Set();
const initial = { pipelines: [], ready: false, error: "" };
let state = initial;
let pending;

export const pipelinesSnapshot = () => state;
export const pipelinesServerSnapshot = () => initial;
function publish(next) {
  state = next;
  listeners.forEach((listener) => listener());
}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Не удалось загрузить пайплайны");
  return data;
}
const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export function refreshPipelines() {
  if (pending) return pending;
  pending = (async () => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const legacy = JSON.parse(raw);
        if (!Array.isArray(legacy)) throw new Error("Некорректный список сохранённых пайплайнов");
        if (legacy.length) await request("/api/pipelines/import", json("POST", legacy));
        // Only remove legacy storage after the server confirms the import.
        window.localStorage.removeItem(STORAGE_KEY);
      }
      const data = await request("/api/pipelines");
      publish({ pipelines: data.pipelines, ready: true, error: "" });
    } catch (error) {
      publish({ ...state, ready: true, error: error.message });
    } finally {
      pending = undefined;
    }
  })();
  return pending;
}

export function subscribePipelines(listener) {
  listeners.add(listener);
  if (listeners.size === 1) {
    void refreshPipelines();
    window.addEventListener("focus", refreshPipelines);
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size) window.removeEventListener("focus", refreshPipelines);
  };
}

export async function savePipeline(pipeline) {
  await refreshPipelines();
  if (state.error) throw new Error(state.error);
  const data = await request(pipeline.id ? `/api/pipelines/${encodeURIComponent(pipeline.id)}` : "/api/pipelines", json(pipeline.id ? "PATCH" : "POST", pipeline));
  publish({ pipelines: [data.pipeline, ...state.pipelines.filter((item) => item.id !== data.pipeline.id)], ready: true, error: "" });
  return data.pipeline;
}

export async function deletePipeline(id) {
  await request(`/api/pipelines/${encodeURIComponent(id)}`, { method: "DELETE" });
  publish({ ...state, pipelines: state.pipelines.filter((item) => item.id !== id) });
}

export function describePipeline(pipeline) {
  const ocr = pipeline.source !== "scans" ? "Прямое извлечение текста" : pipeline.ocr?.provider === "litellm" ? `Vision · ${pipeline.ocr.model}` : `OCR-сервис · ${pipeline.ocr?.url ?? ""}`;
  const extraction = !pipeline.extraction ? "Ответ Vision-модели" : pipeline.extraction.mode === "prompt" ? `Промпт · ${pipeline.extraction.model}` : `${pipeline.extraction.fields.length} полей · ${pipeline.extraction.model}`;
  return { ocr, extraction };
}
