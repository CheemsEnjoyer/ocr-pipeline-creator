"use client";
import { use } from "react";
import Link from "next/link";
import PipelineEditor from "@/components/PipelineEditor";
import Header from "@/components/Header";
import { Button } from "@/components/ui/button";
import { usePipelines } from "@/hooks/use-pipelines";

export default function EditPipelinePage({ params }) {
  const { id } = use(params);
  const { pipelines, ready } = usePipelines();
  const pipeline = pipelines.find((item) => item.id === id);
  if (!ready) return <main className="app-shell"><Header subtitle="Редактирование пайплайна"/><p className="history-loading">Загружаем пайплайн…</p></main>;
  if (!pipeline) return <main className="app-shell"><Header subtitle="Редактирование пайплайна"/><div className="history-empty"><h1>Пайплайн не найден</h1><p>Возможно, он был удалён или сохранён в другом браузере.</p><Button asChild><Link href="/createpipeline">Создать пайплайн</Link></Button></div></main>;
  return <PipelineEditor key={id} initialPipeline={pipeline}/>;
}
