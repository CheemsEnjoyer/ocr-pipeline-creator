"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Check, ChevronDown, CirclePlay, Copy, FileText, GripVertical, LoaderCircle, MoreHorizontal, Plus, ScanText, Sparkles, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

type StepId = "start" | "ocr" | "extract" | "llm" | "output";
const steps: Array<{ id: StepId; label: string; hint: string; icon: typeof Upload }> = [
  { id: "start", label: "Начало", hint: "Входные файлы", icon: Upload },
  { id: "ocr", label: "OCR", hint: "Распознавание", icon: ScanText },
  { id: "extract", label: "Извлечение", hint: "Текст документа", icon: FileText },
  { id: "llm", label: "LLM", hint: "Анализ данных", icon: Sparkles },
  { id: "output", label: "Вывод", hint: "JSON · Webhook", icon: CirclePlay },
];
const initialFields = [
  { id: 1, name: "invoice_number", description: "Номер счёта или документа" },
  { id: 2, name: "total_amount", description: "Итоговая сумма с валютой" },
  { id: 3, name: "due_date", description: "Срок оплаты в формате YYYY-MM-DD" },
];

export default function Home() {
  const [active, setActive] = useState<StepId>("llm");
  const [running, setRunning] = useState(false);
  const [saved, setSaved] = useState(true);
  const [files, setFiles] = useState<string[]>(["invoice_0241.pdf"]);
  const [fields, setFields] = useState(initialFields);
  const [docTypes, setDocTypes] = useState(["Счёт на оплату", "Акт", "Договор"]);
  const [newType, setNewType] = useState("");
  const [prompt, setPrompt] = useState("Проверь документ и извлеки ключевые реквизиты. Верни только структурированный результат.");
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelError, setModelError] = useState("");
  const [runMessage, setRunMessage] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const activeMeta = useMemo(() => steps.find((step) => step.id === active)!, [active]);
  const ActiveIcon = activeMeta.icon;
  const runPipeline = async () => {
    if (!selectedModel) { setRunMessage("Сначала подключите LiteLLM и выберите модель"); return; }
    setRunning(true); setRunMessage("");
    try {
      const response = await fetch("/api/litellm/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: selectedModel, prompt, fields, documentText: `Документ: ${files.join(", ")}` }) });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "LiteLLM не ответил");
      setRunMessage(`Готово · ${selectedModel}`);
    } catch (error) { setRunMessage(error instanceof Error ? error.message : "Ошибка LiteLLM"); }
    finally { setRunning(false); window.setTimeout(() => setRunMessage(""), 4500); }
  };
  const addField = () => { setFields((v) => [...v, { id: Date.now(), name: "new_field", description: "Описание параметра" }]); setSaved(false); };

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/litellm/models", { signal: controller.signal })
      .then(async (response) => { const payload = await response.json() as { models?: string[]; error?: string }; if (!response.ok) throw new Error(payload.error || "Не удалось получить модели"); return payload.models ?? []; })
      .then((available) => { setModels(available); setSelectedModel((current) => current || available[0] || ""); setModelError(available.length ? "" : "В LiteLLM нет доступных моделей"); })
      .catch((error) => { if (!(error instanceof DOMException && error.name === "AbortError")) setModelError(error instanceof Error ? error.message : "LiteLLM недоступен"); })
      .finally(() => setModelsLoading(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const context = (document as Document & { modelContext?: { registerTool: (tool: unknown, options?: { signal?: AbortSignal }) => void | Promise<void> } }).modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const tool = {
      name: "add_extraction_fields",
      title: "Добавить извлекаемые параметры",
      description: "Добавляет один или несколько параметров в LLM-блок открытого OCR-пайплайна.",
      inputSchema: { type: "object", properties: { fields: { type: "array", minItems: 1, items: { type: "object", properties: { name: { type: "string", minLength: 1 }, description: { type: "string", minLength: 1 } }, required: ["name", "description"], additionalProperties: false } } }, required: ["fields"], additionalProperties: false },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      execute(input: unknown) {
        const value = input as { fields?: Array<{ name?: string; description?: string }> };
        if (!Array.isArray(value.fields) || value.fields.some((item) => !item.name?.trim() || !item.description?.trim())) throw new Error("Укажите название и описание каждого параметра.");
        const additions = value.fields.map((item, index) => ({ id: Date.now() + index, name: item.name!.trim(), description: item.description!.trim() }));
        setFields((current) => [...current, ...additions]); setActive("llm"); setSaved(false);
        return { added: additions.length, fieldNames: additions.map((item) => item.name) };
      },
    };
    try { void Promise.resolve(context.registerTool(tool, { signal: lifecycle.signal })).catch(() => undefined); } catch { /* Browser does not support WebMCP. */ }
    return () => lifecycle.abort();
  }, []);

  return <main className="app-shell">
    <header className="topbar">
      <div className="brand-block"><button className="icon-button" aria-label="Вернуться"><ArrowLeft size={18}/></button><div className="brand-mark"><ScanText size={20}/></div><div><div className="eyebrow">OCR FLOW</div><div className="pipeline-title">Обработка счетов <ChevronDown size={14}/></div></div></div>
      <div className="status-pill"><span/> {saved ? "Все изменения сохранены" : "Есть несохранённые изменения"}</div>
      <div className="header-actions"><Button variant="outline" size="sm" onClick={() => setSaved(true)}>Сохранить</Button><Button size="sm" onClick={runPipeline} disabled={running} className="run-button">{running ? <LoaderCircle className="animate-spin" size={16}/> : <CirclePlay size={16}/>} {running ? "Запускаем…" : "Запустить"}</Button><button className="icon-button" aria-label="Ещё"><MoreHorizontal size={19}/></button></div>
    </header>

    <section className="workspace">
      <aside className="library-panel"><div><p className="panel-kicker">БЛОКИ</p><h2>Этапы обработки</h2><p className="helper-copy">Нажмите на блок, чтобы настроить его.</p></div>
        <div className="library-list">{steps.map((step) => { const Icon=step.icon; return <button key={step.id} className={`library-item ${active===step.id?"selected":""}`} onClick={() => setActive(step.id)}><span className={`step-icon step-${step.id}`}><Icon size={17}/></span><span><strong>{step.label}</strong><small>{step.hint}</small></span><GripVertical className="drag-icon" size={16}/></button>; })}</div>
        <Dialog><DialogTrigger asChild><Button variant="outline" className="doc-types"><FileText size={16}/> Типы документов <span>{docTypes.length}</span></Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Типы документов</DialogTitle></DialogHeader><p className="dialog-help">Тип помогает выбрать подходящий пайплайн и правила извлечения.</p><div className="type-list">{docTypes.map((type)=><div key={type}><FileText size={16}/><span>{type}</span><Check size={15}/></div>)}</div><div className="inline-form"><Input value={newType} onChange={(e)=>setNewType(e.target.value)} placeholder="Новый тип документа"/><Button onClick={()=>{if(newType.trim()){setDocTypes([...docTypes,newType.trim()]);setNewType("");}}}>Добавить</Button></div></DialogContent></Dialog>
        <div className="usage-card"><div><span>Лимит страниц</span><strong>248 / 1 000</strong></div><div className="usage-track"><span/></div><small>Обновится через 18 дней</small></div>
      </aside>

      <section className="canvas" aria-label="Схема OCR-пайплайна"><div className="canvas-toolbar"><span>Схема пайплайна</span><button aria-label="Уменьшить">−</button><strong>90%</strong><button aria-label="Увеличить">+</button></div>
        <div className="flow-row">{steps.map((step,index)=>{const Icon=step.icon;return <div className="flow-part" key={step.id}><button className={`flow-node node-${step.id} ${active===step.id?"active":""}`} onClick={()=>setActive(step.id)}><span className="node-topline"><span className={`node-icon step-${step.id}`}><Icon size={17}/></span><MoreHorizontal size={17}/></span><span className="node-label">{step.label}</span><small>{step.hint}</small>{step.id==="start"&&<span className="node-badge">{files.length} файл</span>}{step.id==="llm"&&<span className="node-badge">{fields.length} поля</span>}</button>{index<steps.length-1&&<div className="connector"><span/></div>}</div>})}</div>
        <div className="flow-caption"><span><Check size={14}/> Маршрут готов к запуску</span><p>Изображения попадут в OCR, цифровые документы — сразу в извлечение текста.</p></div>
      </section>

      <aside className="settings-panel"><div className="settings-head"><div className={`step-icon step-${active}`}><ActiveIcon size={17}/></div><div><p className="panel-kicker">НАСТРОЙКИ БЛОКА</p><h2>{activeMeta.label}</h2></div><button className="icon-button" aria-label="Закрыть"><X size={18}/></button></div>
        {active==="start"&&<div className="settings-body"><div className="field-group"><Label>Тип документа</Label><Select defaultValue="invoice"><SelectTrigger><SelectValue/></SelectTrigger><SelectContent><SelectItem value="invoice">Счёт на оплату</SelectItem><SelectItem value="act">Акт</SelectItem><SelectItem value="contract">Договор</SelectItem></SelectContent></Select></div><div className="field-group"><Label>Файлы для теста</Label><input ref={inputRef} type="file" multiple hidden onChange={(e)=>setFiles(Array.from(e.target.files||[]).map(f=>f.name))}/><button className="upload-zone" onClick={()=>inputRef.current?.click()}><Upload size={20}/><strong>Загрузить файлы</strong><span>PDF, PNG, JPG, DOCX до 25 МБ</span></button></div>{files.map(file=><div className="file-chip" key={file}><FileText size={16}/><span>{file}</span><Check size={15}/></div>)}</div>}
        {active==="ocr"&&<div className="settings-body"><div className="field-group"><Label>Язык распознавания</Label><Select defaultValue="auto"><SelectTrigger><SelectValue/></SelectTrigger><SelectContent><SelectItem value="auto">Определять автоматически</SelectItem><SelectItem value="ru">Русский</SelectItem><SelectItem value="en">Английский</SelectItem></SelectContent></Select></div><SettingSwitch title="Исправлять наклон" copy="Автоматически выравнивать страницы" defaultChecked/><SettingSwitch title="Сохранять разметку" copy="Таблицы, абзацы и координаты блоков" defaultChecked/><SettingSwitch title="Рукописный текст" copy="Распознавать подписи и пометки"/></div>}
        {active==="extract"&&<div className="settings-body"><div className="field-group"><Label>Форматы</Label><div className="format-grid"><span>PDF</span><span>DOCX</span><span>XLSX</span><span>TXT</span></div></div><SettingSwitch title="Сохранять таблицы" copy="Преобразовывать таблицы в Markdown" defaultChecked/><SettingSwitch title="Извлекать метаданные" copy="Автор, дата создания и заголовок" defaultChecked/></div>}
        {active==="llm"&&<div className="llm-settings"><div className="litellm-card"><div className="litellm-heading"><div><span className="provider-logo">L</span><div><strong>LiteLLM</strong><small>OpenAI-совместимый шлюз</small></div></div><span className={`provider-status ${modelError?"offline":""}`}><i/>{modelsLoading?"Подключаемся":modelError?"Нет связи":"Подключено"}</span></div><div className="field-group"><Label>Модель</Label><Select value={selectedModel} onValueChange={(value)=>{setSelectedModel(value);setSaved(false)}} disabled={modelsLoading||!models.length}><SelectTrigger><SelectValue placeholder={modelsLoading?"Загружаем модели…":"Нет доступных моделей"}/></SelectTrigger><SelectContent>{models.map((model)=><SelectItem key={model} value={model}>{model}</SelectItem>)}</SelectContent></Select><small className={`model-help ${modelError?"error":""}`}>{modelError||`${models.length} ${models.length===1?"модель доступна":"моделей доступно"} через LiteLLM`}</small></div></div><Tabs defaultValue="fields" className="settings-tabs"><TabsList className="grid w-full grid-cols-2"><TabsTrigger value="prompt">Промпт</TabsTrigger><TabsTrigger value="fields">Параметры</TabsTrigger></TabsList><TabsContent value="prompt" className="settings-body"><div className="field-group"><Label>Инструкция для модели</Label><Textarea rows={8} value={prompt} onChange={(e)=>{setPrompt(e.target.value);setSaved(false)}}/><small className="counter">{prompt.length} / 4 000</small></div></TabsContent><TabsContent value="fields" className="settings-body"><p className="section-copy">Опишите данные, которые нужно получить из документа.</p><div className="field-list">{fields.map((field,index)=><div className="extract-field" key={field.id}><div className="field-index">{index+1}</div><div><Input value={field.name} onChange={(e)=>setFields(fields.map(item=>item.id===field.id?{...item,name:e.target.value}:item))}/><Textarea value={field.description} rows={2} onChange={(e)=>setFields(fields.map(item=>item.id===field.id?{...item,description:e.target.value}:item))}/></div><button aria-label="Дублировать поле" onClick={()=>setFields([...fields,{...field,id:Date.now()}])}><Copy size={15}/></button></div>)}</div><Button variant="outline" className="add-field" onClick={addField}><Plus size={16}/> Добавить параметр</Button></TabsContent></Tabs></div>}
        {active==="output"&&<div className="settings-body"><div className="field-group"><Label>Формат ответа</Label><Select defaultValue="json"><SelectTrigger><SelectValue/></SelectTrigger><SelectContent><SelectItem value="json">JSON</SelectItem><SelectItem value="csv">CSV</SelectItem><SelectItem value="plain">Текст</SelectItem></SelectContent></Select></div><SettingSwitch title="Отправить в webhook" copy="Передать результат во внешнюю систему"/><div className="preview-json"><span>Предпросмотр</span><pre>{`{\n  "invoice_number": "...",\n  "total_amount": "...",\n  "due_date": "..."\n}`}</pre></div></div>}
      </aside>
    </section>{(running||runMessage)&&<div className="run-toast">{running?<LoaderCircle className="animate-spin" size={18}/>:runMessage.startsWith("Готово")?<Check size={18}/>:<X size={18}/>}<div><strong>{running?"Пайплайн запущен":runMessage.startsWith("Готово")?"LiteLLM завершил обработку":"Запуск невозможен"}</strong><span>{running?`${selectedModel} · обрабатываем ${files.length||1} файл…`:runMessage}</span></div></div>}
  </main>;
}

function SettingSwitch({title,copy,defaultChecked=false}:{title:string;copy:string;defaultChecked?:boolean}) { return <div className="switch-row"><div><strong>{title}</strong><span>{copy}</span></div><Switch defaultChecked={defaultChecked}/></div>; }
