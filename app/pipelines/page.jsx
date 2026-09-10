"use client";

import { useState } from "react";
import Link from "next/link";
import { Pencil, Play, Plus, Trash2, Workflow } from "lucide-react";
import Header from "@/components/Header";
import { Button } from "@/components/ui/button";
import { usePipelines } from "@/hooks/use-pipelines";
import { deletePipeline, describePipeline } from "@/lib/pipelines";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel } from "@/components/ui/alert-dialog";

const date = (value) => value ? new Date(value).toLocaleString("ru-RU", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";

export default function PipelinesPage() {
  const { pipelines, ready } = usePipelines();
  const [removing, setRemoving] = useState(null);
  const [error, setError] = useState("");

  return <main className="app-shell">
    <Header subtitle="Пайплайны"/>
    <div className="pipelines-page">
      <div className="pipelines-heading">
        <div><p className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</p><h1>Сохранённые пайплайны</h1><p>Открывайте, редактируйте и запускайте настроенные сценарии обработки документов.</p></div>
        <Button asChild><Link href="/"><Plus size={17}/>Создать пайплайн</Link></Button>
      </div>

      {!ready && <p className="history-loading" role="status">Загружаем пайплайны…</p>}

      {ready && !pipelines.length && <div className="history-empty">
        <Workflow size={38}/>
        <strong>Пайплайнов пока нет</strong>
        <p>Соберите первый сценарий в конструкторе — он появится здесь и станет доступен на странице обработки.</p>
        <Button asChild><Link href="/">Создать пайплайн</Link></Button>
      </div>}

      {ready && pipelines.length > 0 && <div className="pipeline-grid">{pipelines.map((pipeline) => {
        const summary = describePipeline(pipeline);
        return <article className="pipeline-card" key={pipeline.id}>
          <div className="pipeline-card-head">
            <span className="pipeline-card-icon"><Workflow size={19}/></span>
            <div><h2>{pipeline.name || "Без названия"}</h2><small>Обновлён {date(pipeline.updatedAt || pipeline.createdAt)}</small></div>
          </div>
          <dl className="pipeline-card-meta">
            <div><dt>Распознавание</dt><dd>{summary.ocr}</dd></div>
            <div><dt>Извлечение</dt><dd>{summary.extraction}</dd></div>
          </dl>
          <div className="pipeline-card-actions">
            <Button variant="outline" size="sm" asChild><Link href={`/pipelines/${encodeURIComponent(pipeline.id)}`}><Pencil size={15}/>Редактировать</Link></Button>
            <Button variant="ghost" size="sm" asChild><Link href="/process"><Play size={15}/>Обработать</Link></Button>
            <button className="pipeline-card-delete" aria-label={`Удалить пайплайн «${pipeline.name}»`} onClick={() => { setError(""); setRemoving(pipeline); }}><Trash2 size={15}/></button>
          </div>
        </article>;
      })}</div>}
    </div>

    <AlertDialog open={Boolean(removing)} onOpenChange={(open) => { if (!open) setRemoving(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Удалить пайплайн?</AlertDialogTitle><AlertDialogDescription>«{removing?.name}» будет удалён из списка. Обработанные документы и их история сохранятся.</AlertDialogDescription></AlertDialogHeader>{error && <p className="history-error" role="alert">{error}</p>}<AlertDialogFooter><AlertDialogCancel>Отмена</AlertDialogCancel><Button variant="destructive" onClick={() => { try { deletePipeline(removing.id); setRemoving(null); } catch (error) { setError(error.message); } }}>Удалить</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </main>;
}
