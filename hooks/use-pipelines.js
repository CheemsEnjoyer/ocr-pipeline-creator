"use client";
import { useMemo, useSyncExternalStore } from "react";
import { PIPELINES_CHANGED, STORAGE_KEY } from "@/lib/pipelines";

function subscribe(callback) {
  const storage = (event) => { if (!event.key || event.key === STORAGE_KEY) callback(); };
  window.addEventListener("storage", storage);
  window.addEventListener(PIPELINES_CHANGED, callback);
  return () => { window.removeEventListener("storage", storage); window.removeEventListener(PIPELINES_CHANGED, callback); };
}
function snapshot() {
  try { return window.localStorage.getItem(STORAGE_KEY) || "[]"; } catch { return "[]"; }
}
export function usePipelines() {
  const raw = useSyncExternalStore(subscribe, snapshot, () => null);
  return useMemo(() => {
    try { const parsed = JSON.parse(raw || "[]"); return { pipelines: Array.isArray(parsed) ? parsed : [], ready: raw !== null }; }
    catch { return { pipelines: [], ready: true }; }
  }, [raw]);
}
