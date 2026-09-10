"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertCircle, Check, ChevronRight, CloudUpload, FileText, LoaderCircle, Play, Trash2, Workflow } from "lucide-react";
import Header from "@/components/Header";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { describePipeline } from "@/lib/pipelines";
import { usePipelines } from "@/hooks/use-pipelines";

const ACCEPT = "image/*,application/pdf,.txt,.md,.csv,.json,.html,.docx";

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function ProcessPage() {
  const { pipelines } = usePipelines();
  const [pipelineId, setPipelineId] = useState("");
  const [items, setItems] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [running, setRunning] = useState(false);
  const inputRef = useRef(null);

  const pipeline = useMemo(() => pipelines.find((item) => item.id === pipelineId) ?? pipelines[0] ?? null, [pipelines, pipelineId]);
  const summary = pipeline ? describePipeline(pipeline) : null;
  const canRun = Boolean(pipeline) && items.length > 0 && !running;

  const addFiles = (fileList) => {
    const incoming = Array.from(fileList ?? []).map((file) => ({ id: `${file.name}-${file.size}-${file.lastModified}`, file, status: "idle" }));
    setItems((current) => [...current, ...incoming.filter((item) => !current.some((existing) => existing.id === item.id))]);
  };

  const patch = (id, changes) => setItems((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)));

  const run = async () => {
    setRunning(true);
    for (const item of items) {
      patch(item.id, { status: "processing", result: undefined, error: undefined });
      try {
        const body = new FormData();
        body.append("file", item.file);
        body.append("pipeline", JSON.stringify(pipeline));
        const response = await fetch("/api/pipeline/run", { method: "POST", body });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Обработка не удалась");
        patch(item.id, { status: "done", result: data.result, documentId: data.documentId });
      } catch (error) {
        patch(item.id, { status: "error", error: error.message || "Обработка не удалась" });
      }
    }
    setRunning(false);
  };

  return <main className="app-shell">
    <Header subtitle="Обработка документов"/>

    <div className="process-layout">
      <section className="upload-column">
        <div className="section-head"><p className="eyebrow">ШАГ 1</p><h1>Загрузите документы</h1><p>Перетащите файлы в область ниже или выберите их вручную.</p></div>

        <div
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(event.dataTransfer.files); }}
          onClick={() => inputRef.current?.click()}
        >
          <div className="dropzone-icon"><CloudUpload size={26}/></div>
          <strong>Перетащите файлы сюда</strong>
          <span>PNG, JPG, PDF, TXT, CSV, JSON — до 20 МБ на файл</span>
          <input ref={inputRef} type="file" multiple accept={ACCEPT} hidden onChange={(event) => { addFiles(event.target.files); event.target.value = ""; }}/>
        </div>

        {items.length > 0 && <div className="file-list">
          <div className="file-list-head"><span>{items.length} файл(ов)</span><button onClick={() => setItems([])} disabled={running}>Очистить всё</button></div>
          {items.map((item) => <article className={`file-card ${item.status}`} key={item.id}>
            <div className="file-icon"><FileText size={18}/></div>
            <div className="file-meta"><strong>{item.file.name}</strong><small>{formatSize(item.file.size)} · {item.file.type || "неизвестный тип"}</small></div>
            <FileStatus status={item.status}/>
            <button className="remove-field" onClick={() => setItems(items.filter((entry) => entry.id !== item.id))} disabled={running} aria-label="Удалить файл"><Trash2 size={16}/></button>
            {item.status === "error" && <p className="file-error"><AlertCircle size={14}/>{item.error}</p>}
            {item.status === "done" && <div className="processed-document-link"><Check size={15}/><span>Сохранён в истории</span><Button variant="outline" size="sm" asChild><Link href={`/history?document=${encodeURIComponent(item.documentId)}`}>Открыть документ<ChevronRight size={15}/></Link></Button></div>}
          </article>)}
        </div>}
      </section>

      <aside className="pipeline-column">
        <div className="section-head"><p className="eyebrow">ШАГ 2</p><h2>Выберите пайплайн</h2></div>

        {pipelines.length === 0 ? <div className="empty-pipelines">
          <Workflow size={22}/>
          <strong>Пайплайнов пока нет</strong>
          <span>Соберите первый пайплайн в конструкторе — он появится здесь.</span>
          <Button size="sm" asChild><Link href="/">Открыть конструктор<ChevronRight size={15}/></Link></Button>
        </div> : <>
          <Select value={pipeline?.id ?? ""} onValueChange={setPipelineId} disabled={running}>
            <SelectTrigger><SelectValue placeholder="Выберите пайплайн"/></SelectTrigger>
            <SelectContent>{pipelines.map((item) => <SelectItem key={item.id} value={item.id}>{item.name || "Без названия"}</SelectItem>)}</SelectContent>
          </Select>

          {summary && <div className="pipeline-details">
            <div><span>Источник</span><strong>{pipeline.source === "scans" ? "Сканы / изображения" : "Цифровой документ"}</strong></div>
            <div><span>Распознавание</span><strong>{summary.ocr}</strong></div>
            <div><span>Извлечение</span><strong>{summary.extraction}</strong></div>
          </div>}

          <Button className="run-button" onClick={run} disabled={!canRun}>{running ? <><LoaderCircle size={16} className="spin"/>Обрабатываем…</> : <><Play size={16}/>Обработать {items.length || ""}</>}</Button>
          {!items.length && <p className="run-hint">Добавьте хотя бы один документ.</p>}
        </>}
      </aside>
    </div>
  </main>;
}

function FileStatus({ status }) {
  if (status === "processing") return <span className="file-status processing"><LoaderCircle size={13} className="spin"/>Обработка</span>;
  if (status === "done") return <span className="file-status done"><Check size={13}/>Готово</span>;
  if (status === "error") return <span className="file-status error"><AlertCircle size={13}/>Ошибка</span>;
  return <span className="file-status">В очереди</span>;
}
