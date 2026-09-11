"use client";
import { useSyncExternalStore } from "react";
import { subscribePipelines, pipelinesSnapshot, pipelinesServerSnapshot } from "@/lib/pipelines";

export function usePipelines() {
  return useSyncExternalStore(subscribePipelines, pipelinesSnapshot, pipelinesServerSnapshot);
}
