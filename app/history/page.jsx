"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Download, FileText, History, LoaderCircle, Save, ScanText } from "lucide-react";
import Header from "@/components/Header";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/components/ui/alert-dialog";

const date = (value) => new Date(value).toLocaleString("ru-RU", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const fieldValue = (value) => typeof value === "string" ? value : JSON.stringify(value, null, 2);
const draftFrom = (fields) => Object.fromEntries(Object.entries(fields).map(([key, value]) => [key, fieldValue(value)]));

async function getJSON(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Не удалось загрузить документ");
  return data;
}

export default function HistoryPage() {
  const [documents, setDocuments] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [document, setDocument] = useState(null);
  const [draft, setDraft] = useState({});
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(true);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [leaveUrl, setLeaveUrl] = useState(null);
  const dirty = document && JSON.stringify(draft) !== JSON.stringify(draftFrom(document.fields));
  const selectDocument = (id) => {
    if (id === selectedId) return;
    setDocument(null);
    setDetailLoading(true);
    setDetailError("");
    setSaveError("");
    setSaved(false);
    setSelectedId(id);
  };
  const reload = () => {
    setLoading(true);
    setError("");
    setDocument(null);
    setDetailLoading(true);
    setDetailError("");
    setSaveError("");
    setSaved(false);
    setRefresh((value) => value + 1);
  };

  useEffect(() => {
    const controller = new AbortController();
    getJSON(`/api/documents?page=${page}`, { signal: controller.signal }).then((data) => {
      setDocuments((current) => page === 0 ? data.documents : [...current.filter((item) => !data.documents.some((entry) => entry.id === item.id)), ...data.documents]);
      setHasMore(data.hasMore);
      setSelectedId((current) => current || new URLSearchParams(window.location.search).get("document") || data.documents[0]?.id || null);
    }).catch((error) => { if (error.name !== "AbortError") setError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [page, refresh]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    getJSON(`/api/documents/${encodeURIComponent(selectedId)}`, { signal: controller.signal }).then((data) => {
      setDocument(data.document);
      setDraft(draftFrom(data.document.fields));
    }).catch((error) => { if (error.name !== "AbortError") setDetailError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selectedId, refresh]);

  useEffect(() => {
    if (!dirty) return;
    const protect = (event) => { event.preventDefault(); event.returnValue = ""; };
    const interceptLink = (event) => {
      const link = event.target.closest?.("a[href]");
      if (!link || link.target === "_blank" || link.hasAttribute("download") || event.ctrlKey || event.metaKey || link.href.includes("/original")) return;
      event.preventDefault();
      event.stopPropagation();
      setLeaveUrl(link.href);
    };
    window.addEventListener("beforeunload", protect);
    window.document.addEventListener("click", interceptLink, true);
    return () => { window.removeEventListener("beforeunload", protect); window.document.removeEventListener("click", interceptLink, true); };
  }, [dirty]);

  const save = async () => {
    setSaveError("");
    let fields;
    try {
      fields = Object.fromEntries(Object.entries(document.fields).map(([key, original]) => {
        if (typeof original === "string") return [key, draft[key]];
        let value;
        try { value = JSON.parse(draft[key]); } catch { throw new Error(`Поле «${key}»: введите корректный JSON`); }
        if (original !== null && (typeof value !== typeof original || Array.isArray(value) !== Array.isArray(original) || value === null)) throw new Error(`Поле «${key}»: сохраните исходный тип значения`);
        return [key, value];
      }));
    } catch (error) { setSaveError(error.message); return; }
    setSaving(true);
    try {
      const updated = await getJSON(`/api/documents/${encodeURIComponent(document.id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fields, revision: document.revision }) });
      setDocument((current) => ({ ...current, ...updated, fields }));
      setDraft(draftFrom(fields));
      setSaved(true);
    } catch (error) { setSaveError(error.message); }
    finally { setSaving(false); }
  };

  return <main className="app-shell">
    <AlertDialog open={Boolean(leaveUrl)} onOpenChange={(open) => { if (!open) setLeaveUrl(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Оставить изменения несохранёнными?</AlertDialogTitle><AlertDialogDescription>Правки полей будут потеряны. Можно остаться и сохранить их.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Остаться</AlertDialogCancel><AlertDialogAction onClick={() => { setDraft(draftFrom(document.fields)); setTimeout(() => window.location.assign(leaveUrl), 0); }}>Уйти без сохранения</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    <Header subtitle="История документов"/>
    <div className="history-workspace">
      <aside className="history-list">
        <div className="history-list-heading"><div><h1>Документы</h1><p>Результаты обработки</p></div><History size={20}/></div>
        {error && <div role="alert" className="history-error">{error}<Button variant="outline" size="sm" disabled={dirty || saving} onClick={reload}>Повторить</Button></div>}
        {!loading && !error && !documents.length && <div className="history-empty"><FileText size={30}/><strong>История пока пуста</strong><p>Обработайте документ — его исходник, текст и поля появятся здесь.</p><Button asChild size="sm"><Link href="/">Загрузить документ</Link></Button></div>}
        {dirty && <p className="history-notice">Сохраните или отмените правки, чтобы выбрать другой документ.</p>}
        <div className="document-list">{documents.map((item) => <button key={item.id} className={`document-row ${selectedId === item.id ? "selected" : ""}`} aria-pressed={selectedId === item.id} disabled={Boolean(dirty) || saving} onClick={() => selectDocument(item.id)}>
          <span className="document-row-icon"><FileText size={19}/></span><span className="document-row-info"><strong>{item.filename}</strong><span>{item.pipeline_name}</span><small>{date(item.created_at)}</small></span><Check size={14} className="document-row-check"/>
        </button>)}</div>
        {loading && <p className="history-loading" role="status"><LoaderCircle size={18} className="spin"/>Загружаем историю…</p>}
        {hasMore && <Button variant="outline" disabled={loading || dirty || saving} onClick={() => { setLoading(true); setPage((value) => value + 1); }}>Загрузить ещё</Button>}
      </aside>
      <section className="document-workspace" aria-label="Выбранный документ">
        {detailLoading && selectedId && <div className="history-empty" role="status"><LoaderCircle className="spin"/>Загружаем документ…</div>}
        {detailError && <div className="history-error" role="alert">{detailError}<Button variant="outline" onClick={reload}>Повторить</Button></div>}
        {!selectedId && !loading && <div className="history-empty document-placeholder"><ScanText size={40}/><h2>Всё по документу — в одном месте</h2><p>Выберите документ в истории, чтобы открыть исходник, прочитать текст и проверить извлечённые поля.</p></div>}
        {document && <>
          <div className="document-heading"><div><span className="document-badge"><Check size={13}/>Обработан</span><h2>{document.filename}</h2><p>{document.pipeline_name} · {date(document.created_at)} · {(document.size / 1024).toFixed(1)} КБ</p></div></div>
          <div className="document-detail-grid">
            <Tabs defaultValue="text" key={document.id} className="document-viewer">
              <div className="document-viewer-toolbar"><TabsList aria-label="Содержимое документа"><TabsTrigger value="original">Исходный документ</TabsTrigger><TabsTrigger value="text">Извлечённый текст</TabsTrigger></TabsList></div>
              <TabsContent value="original"><OriginalDocument document={document}/></TabsContent>
              <TabsContent value="text"><pre className="document-text">{document.text || "В документе не найден текст."}</pre></TabsContent>
            </Tabs>
            <aside className="extracted-panel">
              <div className="extracted-heading"><div><h3>Извлечённые поля</h3><p>Проверьте и уточните значения</p></div><span>{Object.keys(document.fields).length}</span></div>
              {!Object.keys(document.fields).length && <div className="history-empty"><ScanText size={25}/><p>Структурированные поля не получены. Результат доступен ниже.</p><pre className="raw-extraction">{document.result || "Нет результата"}</pre></div>}
              <div className="extracted-fields">{Object.entries(document.fields).map(([key, value], index) => <div className="extracted-field" key={key}>
                <label htmlFor={`extracted-${index}`}>{key}</label>
                <Textarea id={`extracted-${index}`} value={draft[key] ?? ""} disabled={saving} rows={typeof value === "object" && value !== null ? 5 : 2} onChange={(event) => { setDraft((current) => ({ ...current, [key]: event.target.value })); setSaved(false); }}/>
                {typeof value !== "string" && <small>{typeof value === "number" ? "Число" : typeof value === "boolean" ? "true или false" : "Значение JSON"}</small>}
              </div>)}</div>
              {Object.keys(document.fields).length > 0 && <div className="field-actions">
                {saveError && <p className="history-error" role="alert">{saveError}</p>}
                <div className="field-save-status" role="status">{saved ? <><Check size={15}/>Изменения сохранены</> : dirty ? "Есть несохранённые изменения" : "Все изменения сохранены"}</div>
                <Button onClick={save} disabled={!dirty || saving}>{saving ? <LoaderCircle size={16} className="spin"/> : <Save size={16}/>} {saving ? "Сохраняем…" : "Сохранить изменения"}</Button>
                {dirty && <Button variant="ghost" disabled={saving} onClick={() => { setDraft(draftFrom(document.fields)); setSaveError(""); }}>Отменить правки</Button>}
              </div>}
            </aside>
          </div>
        </>}
      </section>
    </div>
  </main>;
}

function OriginalDocument({ document }) {
  const url = `/api/documents/${encodeURIComponent(document.id)}/original`;
  const isImage = /^image\/(png|jpeg|gif|webp|avif|bmp)$/.test(document.mime_type);
  return <div className="original-document">
    <div className="original-actions"><Button variant="outline" size="sm" asChild><a href={`${url}?download=1`}><Download size={15}/>Скачать исходник</a></Button></div>
    {isImage ? <img src={url} alt={document.filename}/> : document.mime_type === "application/pdf" ? <iframe src={url} title={`Исходный документ: ${document.filename}`}/> : <div className="history-empty"><FileText size={35}/><strong>{document.filename}</strong><p>Скачайте исходный файл, чтобы открыть его в подходящем приложении.</p></div>}
  </div>;
}

