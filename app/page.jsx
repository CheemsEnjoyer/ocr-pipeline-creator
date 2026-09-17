"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Check, ChevronRight, CloudUpload, FileText, LoaderCircle, Play, Trash2, Workflow } from "lucide-react";
import Header from "@/components/Header";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { describePipeline } from "@/lib/pipelines";
import { usePipelines } from "@/hooks/use-pipelines";
import { waitForJob } from "@/lib/jobs";
import { useSession } from "@/hooks/use-session";

const ACCEPT = "image/*,application/pdf,.txt,.md,.csv,.json,.html,.docx";

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function ProcessPage() {
  const isAdmin = useSession()?.role === "admin";
  const { pipelines, ready, error: pipelineError } = usePipelines();
  const [pipelineId, setPipelineId] = useState("");
  const [runMode, setRunMode] = useState("async");
  const [items, setItems] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [running, setRunning] = useState(false);
  const inputRef = useRef(null);
  const runController = useRef(null);
  useEffect(() => () => runController.current?.abort(), []);

  const pipeline = useMemo(() => pipelines.find((item) => item.id === pipelineId) ?? pipelines[0] ?? null, [pipelines, pipelineId]);
  const allowSync = pipeline?.allow_sync !== false;
  const allowAsync = pipeline?.allow_async !== false;
  const selectedRunMode = (runMode === "sync" && allowSync) || (runMode === "async" && allowAsync) ? runMode : allowAsync ? "async" : "sync";
  const summary = pipeline ? describePipeline(pipeline) : null;
  const canRun = Boolean(pipeline) && items.some((item) => item.status !== "done") && !running;

  const addFiles = (fileList) => {
    const incoming = Array.from(fileList ?? []).map((file) => ({ id: `${file.name}-${file.size}-${file.lastModified}`, file, status: "idle" }));
    setItems((current) => [...current, ...incoming.filter((item) => !current.some((existing) => existing.id === item.id))]);
  };

  const patch = (id, changes) => setItems((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)));

  const run = async () => {
    setRunning(true);
    const controller = new AbortController();
    runController.current = controller;
    await Promise.all(items.filter((item) => item.status !== "done").map(async (item) => {
      patch(item.id, { status: "processing", result: undefined, error: undefined });
      try {
        let taskId = item.taskId;
        if (!taskId) {
          const body = new FormData();
          body.append("file", item.file);
          body.append("pipeline_id", pipeline.id);
          const background = selectedRunMode === "async";
          const response = await fetch(`/api/pipeline/run?background=${background}`, { method: "POST", body, signal: controller.signal });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || "Обработка не удалась");
          if (!background) {
            patch(item.id, { status: "done", result: data.result, documentId: data.documentId });
            return;
          }
          taskId = data.taskId;
          if (!taskId) throw new Error("Сервер не вернул ID задачи");
          patch(item.id, { taskId });
        }
        const result = await waitForJob(`/api/jobs/${encodeURIComponent(taskId)}`, { signal: controller.signal });
        patch(item.id, { status: "done", result: result.result, documentId: result.documentId });
      } catch (error) {
        if (controller.signal.aborted) return;
        patch(item.id, { status: "error", error: error.message || "Обработка не удалась" });
        if (error.taskFailed) patch(item.id, { taskId: undefined });
      }
    }));
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
            {item.status === "done" && <div className="processed-document-link"><Check size={15}/><span>Сохранён в истории</span><Button variant="outline" size="sm" asChild><a href={`/history?document=${encodeURIComponent(item.documentId)}`}>Открыть документ<ChevronRight size={15}/></a></Button></div>}
          </article>)}
        </div>}
      </section>

      <aside className="pipeline-column">
        <div className="section-head"><p className="eyebrow">ШАГ 2</p><h2>Выберите пайплайн</h2></div>

        {pipelineError ? <p className="history-error" role="alert">{pipelineError}</p> : !ready ? <p role="status">Загружаем пайплайны…</p> : pipelines.length === 0 ? <div className="empty-pipelines">
          <Workflow size={22}/>
          <strong>Пайплайнов пока нет</strong>
          <span>Соберите первый пайплайн в конструкторе — он появится здесь.</span>
          {isAdmin && <Button size="sm" asChild><a href="/createpipeline">Открыть конструктор<ChevronRight size={15}/></a></Button>}
        </div> : <>
          <Select value={pipeline?.id ?? ""} onValueChange={setPipelineId} disabled={running}>
            <SelectTrigger className="process-pipeline-trigger" aria-label="Выберите пайплайн" title={pipeline?.name || "Без названия"}><SelectValue placeholder="Выберите пайплайн"/></SelectTrigger>
            <SelectContent className="process-pipeline-menu" position="popper" align="start">{pipelines.map((item) => <SelectItem className="process-pipeline-option" key={item.id} value={item.id}>{item.name || "Без названия"}</SelectItem>)}</SelectContent>
          </Select>

          {summary && <div className="pipeline-details">
            <div><span>Источник</span><strong>{pipeline.source === "scans" ? "Сканы / изображения" : "Цифровой документ"}</strong></div>
            <div><span>Распознавание</span><strong>{summary.ocr}</strong></div>
            <div><span>Извлечение</span><strong>{summary.extraction}</strong></div>
            {allowAsync && <div><span>Параллельно в Celery</span><strong>До {pipeline.async_concurrency ?? 1}</strong></div>}
          </div>}

          {allowSync && allowAsync ? <div className="main-field"><label htmlFor="run-mode">Режим запуска</label><Select value={selectedRunMode} onValueChange={setRunMode} disabled={running}><SelectTrigger id="run-mode"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="sync">Синхронно</SelectItem><SelectItem value="async">Асинхронно через Celery</SelectItem></SelectContent></Select></div> : <p className="run-hint">Режим: {allowAsync ? "асинхронно через Celery" : "синхронно"}</p>}

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
