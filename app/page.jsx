"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, CirclePlay, Copy, FileText, GripVertical, LoaderCircle, MoreHorizontal, MousePointer2, Plus, ScanText, Sparkles, Trash2, Upload, Workflow, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

const blockTypes = [
  { type: "start", label: "Начало", hint: "Файлы и тип документа", icon: Upload },
  { type: "ocr", label: "OCR", hint: "Распознать скан", icon: ScanText },
  { type: "extract", label: "Извлечение", hint: "Прочитать документ", icon: FileText },
  { type: "llm", label: "LLM", hint: "Обработать через LiteLLM", icon: Sparkles },
  { type: "output", label: "Вывод", hint: "JSON, CSV или webhook", icon: CirclePlay },
];

const defaultFields = [
  { id: 1, name: "invoice_number", description: "Номер счёта или документа" },
  { id: 2, name: "total_amount", description: "Итоговая сумма с валютой" },
  { id: 3, name: "due_date", description: "Срок оплаты в формате YYYY-MM-DD" },
];

const nodeConfig = (type) => type === "llm"
  ? { prompt: "Извлеки ключевые реквизиты. Верни только структурированный результат.", model: "", fields: defaultFields }
  : type === "start" ? { documentType: "invoice", files: ["invoice_0241.pdf"] }
  : type === "output" ? { format: "json", webhook: false }
  : {};

const initialPipelines = [
  {
    id: "invoice-flow", name: "Обработка счетов",
    nodes: [
      { id: "n1", type: "start", label: "Загрузить счёт", x: 70, y: 205, config: nodeConfig("start") },
      { id: "n2", type: "ocr", label: "OCR скана", x: 300, y: 90, config: {} },
      { id: "n3", type: "extract", label: "Извлечь PDF", x: 300, y: 320, config: {} },
      { id: "n4", type: "llm", label: "Реквизиты счёта", x: 555, y: 205, config: nodeConfig("llm") },
      { id: "n5", type: "output", label: "Результат JSON", x: 805, y: 205, config: nodeConfig("output") },
    ],
    edges: [
      { id: "e1", source: "n1", target: "n2" }, { id: "e2", source: "n1", target: "n3" },
      { id: "e3", source: "n2", target: "n4" }, { id: "e4", source: "n3", target: "n4" }, { id: "e5", source: "n4", target: "n5" },
    ],
  },
  {
    id: "contract-flow", name: "Проверка договоров",
    nodes: [
      { id: "c1", type: "start", label: "Новый договор", x: 100, y: 220, config: nodeConfig("start") },
      { id: "c2", type: "extract", label: "Текст договора", x: 360, y: 220, config: {} },
      { id: "c3", type: "llm", label: "Анализ рисков", x: 620, y: 130, config: { ...nodeConfig("llm"), prompt: "Найди риски и спорные условия договора." } },
      { id: "c4", type: "llm", label: "Краткое резюме", x: 620, y: 330, config: { ...nodeConfig("llm"), prompt: "Подготовь краткое резюме договора." } },
    ],
    edges: [{ id: "ce1", source: "c1", target: "c2" }, { id: "ce2", source: "c2", target: "c3" }, { id: "ce3", source: "c2", target: "c4" }],
  },
];

export default function Home() {
  const [pipelines, setPipelines] = useState(initialPipelines);
  const [pipelineId, setPipelineId] = useState(initialPipelines[0].id);
  const [activeNodeId, setActiveNodeId] = useState("n4");
  const [connectFrom, setConnectFrom] = useState(null);
  const [newPipelineName, setNewPipelineName] = useState("");
  const [docTypes, setDocTypes] = useState(["Счёт на оплату", "Акт", "Договор"]);
  const [newType, setNewType] = useState("");
  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelError, setModelError] = useState("");
  const [running, setRunning] = useState(false);
  const [runMessage, setRunMessage] = useState("");
  const [saved, setSaved] = useState(true);
  const canvasRef = useRef(null);
  const dragRef = useRef(null);
  const inputRef = useRef(null);

  const pipeline = pipelines.find((item) => item.id === pipelineId) || pipelines[0];
  const activeNode = pipeline.nodes.find((node) => node.id === activeNodeId) || null;
  const activeType = activeNode ? blockTypes.find((item) => item.type === activeNode.type) : null;
  const ActiveIcon = activeType?.icon || MousePointer2;

  const updatePipeline = (updater) => {
    setPipelines((current) => current.map((item) => item.id === pipelineId ? updater(item) : item));
    setSaved(false);
  };
  const updateActiveNode = (patch) => updatePipeline((current) => ({ ...current, nodes: current.nodes.map((node) => node.id === activeNodeId ? { ...node, ...patch } : node) }));
  const updateConfig = (patch) => updateActiveNode({ config: { ...activeNode.config, ...patch } });

  const addNode = (type) => {
    const meta = blockTypes.find((item) => item.type === type);
    const id = `${type}-${Date.now()}`;
    const count = pipeline.nodes.length;
    const node = { id, type, label: meta.label, x: 150 + (count * 43) % 610, y: 115 + (count * 77) % 330, config: nodeConfig(type) };
    updatePipeline((current) => ({ ...current, nodes: [...current.nodes, node] }));
    setActiveNodeId(id);
  };

  const deleteNode = () => {
    if (!activeNode) return;
    updatePipeline((current) => ({ ...current, nodes: current.nodes.filter((node) => node.id !== activeNode.id), edges: current.edges.filter((edge) => edge.source !== activeNode.id && edge.target !== activeNode.id) }));
    setActiveNodeId(null);
  };

  const duplicateNode = () => {
    if (!activeNode) return;
    const id = `${activeNode.type}-${Date.now()}`;
    const copy = { ...activeNode, id, label: `${activeNode.label} — копия`, x: activeNode.x + 35, y: activeNode.y + 35, config: structuredClone(activeNode.config) };
    updatePipeline((current) => ({ ...current, nodes: [...current.nodes, copy] }));
    setActiveNodeId(id);
  };

  const startConnection = (event, nodeId) => { event.stopPropagation(); setConnectFrom((current) => current === nodeId ? null : nodeId); };
  const finishConnection = (event, targetId) => {
    event.stopPropagation();
    if (!connectFrom || connectFrom === targetId) return;
    updatePipeline((current) => current.edges.some((edge) => edge.source === connectFrom && edge.target === targetId) ? current : ({ ...current, edges: [...current.edges, { id: `edge-${Date.now()}`, source: connectFrom, target: targetId }] }));
    setConnectFrom(null);
  };

  const onPointerDown = (event, node) => {
    if (event.button !== 0 || event.target.closest(".node-handle")) return;
    const bounds = canvasRef.current.getBoundingClientRect();
    dragRef.current = { id: node.id, offsetX: event.clientX - bounds.left + canvasRef.current.scrollLeft - node.x, offsetY: event.clientY - bounds.top + canvasRef.current.scrollTop - node.y };
    event.currentTarget.setPointerCapture(event.pointerId);
    setActiveNodeId(node.id);
  };
  const onPointerMove = (event) => {
    if (!dragRef.current) return;
    const bounds = canvasRef.current.getBoundingClientRect();
    const x = Math.max(20, event.clientX - bounds.left + canvasRef.current.scrollLeft - dragRef.current.offsetX);
    const y = Math.max(60, event.clientY - bounds.top + canvasRef.current.scrollTop - dragRef.current.offsetY);
    const draggedId = dragRef.current.id;
    updatePipeline((current) => ({ ...current, nodes: current.nodes.map((node) => node.id === draggedId ? { ...node, x, y } : node) }));
  };

  const createPipeline = () => {
    if (!newPipelineName.trim()) return;
    const id = `pipeline-${Date.now()}`;
    setPipelines((current) => [...current, { id, name: newPipelineName.trim(), nodes: [], edges: [] }]);
    setPipelineId(id); setActiveNodeId(null); setNewPipelineName(""); setSaved(false);
  };

  const runPipeline = async () => {
    const llmNode = pipeline.nodes.find((node) => node.type === "llm" && node.config.model);
    if (!llmNode) { setRunMessage("Добавьте LLM-блок и выберите модель"); return; }
    setRunning(true); setRunMessage("");
    try {
      const response = await fetch("/api/litellm/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: llmNode.config.model, prompt: llmNode.config.prompt, fields: llmNode.config.fields, documentText: "Текст поступит из предыдущего узла пайплайна." }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "LiteLLM не ответил");
      setRunMessage(`Готово · ${llmNode.config.model}`);
    } catch (error) { setRunMessage(error instanceof Error ? error.message : "Ошибка LiteLLM"); }
    finally { setRunning(false); window.setTimeout(() => setRunMessage(""), 4500); }
  };

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/litellm/models", { signal: controller.signal }).then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || "Не удалось получить модели"); return data.models || []; })
      .then((available) => { setModels(available); setModelError(available.length ? "" : "В LiteLLM нет доступных моделей"); })
      .catch((error) => { if (!(error instanceof DOMException && error.name === "AbortError")) setModelError(error.message || "LiteLLM недоступен"); })
      .finally(() => setModelsLoading(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    try { void Promise.resolve(context.registerTool({
      name: "add_pipeline_node", title: "Добавить узел пайплайна", description: "Добавляет новый узел выбранного типа на текущий холст.",
      inputSchema: { type: "object", properties: { type: { type: "string", enum: blockTypes.map((item) => item.type) } }, required: ["type"], additionalProperties: false },
      annotations: { readOnlyHint: false, untrustedContentHint: false }, execute(input) { addNode(input.type); return { added: input.type, pipeline: pipeline.name }; },
    }, { signal: lifecycle.signal })).catch(() => undefined); } catch { /* WebMCP is optional. */ }
    return () => lifecycle.abort();
  }, [pipelineId]);

  return <main className="app-shell">
    <header className="topbar">
      <div className="brand-block"><div className="brand-mark"><Workflow size={20}/></div><div><div className="eyebrow">OCR FLOW</div><Dialog><DialogTrigger asChild><button className="pipeline-title">{pipeline.name}<ChevronDown size={14}/></button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Пайплайны</DialogTitle></DialogHeader><div className="pipeline-list">{pipelines.map((item) => <button key={item.id} className={item.id === pipelineId ? "active" : ""} onClick={() => { setPipelineId(item.id); setActiveNodeId(item.nodes[0]?.id || null); setConnectFrom(null); }}><span><Workflow size={16}/>{item.name}</span><small>{item.nodes.length} узлов</small></button>)}</div><div className="inline-form"><Input value={newPipelineName} onChange={(event) => setNewPipelineName(event.target.value)} placeholder="Название нового пайплайна"/><Button onClick={createPipeline}><Plus size={16}/>Создать</Button></div></DialogContent></Dialog></div></div>
      <div className="status-pill"><span/>{saved ? "Все изменения сохранены" : "Есть несохранённые изменения"}</div>
      <div className="header-actions"><Button variant="outline" size="sm" onClick={() => setSaved(true)}>Сохранить</Button><Button size="sm" onClick={runPipeline} disabled={running} className="run-button">{running ? <LoaderCircle className="animate-spin" size={16}/> : <CirclePlay size={16}/>} {running ? "Запускаем…" : "Запустить"}</Button><button className="icon-button" aria-label="Ещё"><MoreHorizontal size={19}/></button></div>
    </header>

    <section className="workspace">
      <aside className="library-panel"><div><p className="panel-kicker">БИБЛИОТЕКА</p><h2>Добавить узел</h2><p className="helper-copy">Добавляйте любое количество блоков и соединяйте их на холсте.</p></div>
        <div className="library-list">{blockTypes.map((item) => { const Icon = item.icon; return <button key={item.type} className="library-item" onClick={() => addNode(item.type)}><span className={`step-icon step-${item.type}`}><Icon size={17}/></span><span><strong>{item.label}</strong><small>{item.hint}</small></span><Plus className="add-icon" size={16}/></button>; })}</div>
        <Dialog><DialogTrigger asChild><Button variant="outline" className="doc-types"><FileText size={16}/>Типы документов<span>{docTypes.length}</span></Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Типы документов</DialogTitle></DialogHeader><div className="type-list">{docTypes.map((type) => <div key={type}><FileText size={16}/><span>{type}</span><Check size={15}/></div>)}</div><div className="inline-form"><Input value={newType} onChange={(event) => setNewType(event.target.value)} placeholder="Новый тип документа"/><Button onClick={() => { if (newType.trim()) { setDocTypes([...docTypes, newType.trim()]); setNewType(""); } }}>Добавить</Button></div></DialogContent></Dialog>
        <div className="canvas-tip"><MousePointer2 size={16}/><span><strong>Соединение узлов</strong>Нажмите выход одного узла, затем вход другого.</span></div>
      </aside>

      <section ref={canvasRef} className={`canvas ${connectFrom ? "connecting" : ""}`} aria-label="Свободная схема OCR-пайплайна" onPointerMove={onPointerMove} onPointerUp={() => { dragRef.current = null; }} onPointerLeave={() => { dragRef.current = null; }}>
        <div className="canvas-toolbar"><span><Workflow size={14}/>{pipeline.nodes.length} узлов · {pipeline.edges.length} связей</span>{connectFrom && <em>Выберите вход целевого узла</em>}<button onClick={() => setConnectFrom(null)}>Сбросить</button></div>
        <div className="canvas-board" onClick={() => setActiveNodeId(null)}>
          <svg className="edge-layer" width="1200" height="700" aria-hidden="true">{pipeline.edges.map((edge) => { const source = pipeline.nodes.find((node) => node.id === edge.source); const target = pipeline.nodes.find((node) => node.id === edge.target); if (!source || !target) return null; const x1 = source.x + 164, y1 = source.y + 54, x2 = target.x, y2 = target.y + 54, bend = Math.max(55, Math.abs(x2 - x1) * .45); return <path key={edge.id} d={`M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`}/>; })}</svg>
          {pipeline.nodes.map((node) => { const meta = blockTypes.find((item) => item.type === node.type); const Icon = meta.icon; return <div key={node.id} className={`flow-node node-${node.type} ${activeNodeId === node.id ? "active" : ""}`} style={{ left: node.x, top: node.y }} onPointerDown={(event) => onPointerDown(event, node)} onClick={(event) => { event.stopPropagation(); setActiveNodeId(node.id); }}><button className={`node-handle input-handle ${connectFrom ? "ready" : ""}`} aria-label="Вход узла" onClick={(event) => finishConnection(event, node.id)}/><div className="node-topline"><span className={`node-icon step-${node.type}`}><Icon size={17}/></span><GripVertical size={16}/></div><strong className="node-label">{node.label}</strong><small>{meta.hint}</small><span className="node-kind">{node.type}</span><button className={`node-handle output-handle ${connectFrom === node.id ? "active" : ""}`} aria-label="Выход узла" onClick={(event) => startConnection(event, node.id)}/></div>; })}
          {!pipeline.nodes.length && <div className="empty-canvas"><Workflow size={28}/><strong>Пустой пайплайн</strong><span>Добавьте первый узел из библиотеки слева.</span></div>}
        </div>
      </section>

      <aside className="settings-panel">{!activeNode ? <div className="empty-settings"><MousePointer2 size={26}/><strong>Выберите узел</strong><span>Настройки выбранного блока появятся здесь.</span></div> : <><div className="settings-head"><div className={`step-icon step-${activeNode.type}`}><ActiveIcon size={17}/></div><div><p className="panel-kicker">НАСТРОЙКИ УЗЛА</p><h2>{activeType.label}</h2></div><button className="icon-button" onClick={duplicateNode} aria-label="Дублировать"><Copy size={16}/></button><button className="icon-button danger" onClick={deleteNode} aria-label="Удалить"><Trash2 size={16}/></button></div>
        <div className="node-name"><Label>Название узла</Label><Input value={activeNode.label} onChange={(event) => updateActiveNode({ label: event.target.value })}/></div>
        {activeNode.type === "start" && <StartSettings node={activeNode} updateConfig={updateConfig} inputRef={inputRef} docTypes={docTypes}/>} 
        {activeNode.type === "ocr" && <div className="settings-body"><div className="field-group"><Label>Язык распознавания</Label><Select defaultValue="auto"><SelectTrigger><SelectValue/></SelectTrigger><SelectContent><SelectItem value="auto">Определять автоматически</SelectItem><SelectItem value="ru">Русский</SelectItem><SelectItem value="en">Английский</SelectItem></SelectContent></Select></div><SettingSwitch title="Исправлять наклон" copy="Автоматически выравнивать страницы" defaultChecked/><SettingSwitch title="Сохранять разметку" copy="Таблицы, абзацы и координаты блоков" defaultChecked/></div>}
        {activeNode.type === "extract" && <div className="settings-body"><div className="field-group"><Label>Форматы</Label><div className="format-grid"><span>PDF</span><span>DOCX</span><span>XLSX</span><span>TXT</span></div></div><SettingSwitch title="Сохранять таблицы" copy="Преобразовывать таблицы в Markdown" defaultChecked/><SettingSwitch title="Извлекать метаданные" copy="Автор, дата создания и заголовок" defaultChecked/></div>}
        {activeNode.type === "llm" && <LlmSettings node={activeNode} updateConfig={updateConfig} models={models} modelsLoading={modelsLoading} modelError={modelError}/>} 
        {activeNode.type === "output" && <div className="settings-body"><div className="field-group"><Label>Формат ответа</Label><Select value={activeNode.config.format || "json"} onValueChange={(value) => updateConfig({ format: value })}><SelectTrigger><SelectValue/></SelectTrigger><SelectContent><SelectItem value="json">JSON</SelectItem><SelectItem value="csv">CSV</SelectItem><SelectItem value="plain">Текст</SelectItem></SelectContent></Select></div><SettingSwitch title="Отправить в webhook" copy="Передать результат во внешнюю систему"/><div className="preview-json"><span>Предпросмотр</span><pre>{`{\n  "status": "completed",\n  "result": { ... }\n}`}</pre></div></div>}
      </>}</aside>
    </section>
    {(running || runMessage) && <div className="run-toast">{running ? <LoaderCircle className="animate-spin" size={18}/> : runMessage.startsWith("Готово") ? <Check size={18}/> : <X size={18}/>}<div><strong>{running ? "Пайплайн запущен" : runMessage.startsWith("Готово") ? "Обработка завершена" : "Запуск невозможен"}</strong><span>{running ? `Выполняем ${pipeline.nodes.length} узлов…` : runMessage}</span></div></div>}
  </main>;
}

function StartSettings({ node, updateConfig, inputRef, docTypes }) {
  const files = node.config.files || [];
  return <div className="settings-body"><div className="field-group"><Label>Тип документа</Label><Select value={node.config.documentType || "invoice"} onValueChange={(value) => updateConfig({ documentType: value })}><SelectTrigger><SelectValue/></SelectTrigger><SelectContent>{docTypes.map((type, index) => <SelectItem key={type} value={index === 0 ? "invoice" : type}>{type}</SelectItem>)}</SelectContent></Select></div><div className="field-group"><Label>Файлы для теста</Label><input ref={inputRef} type="file" multiple hidden onChange={(event) => updateConfig({ files: Array.from(event.target.files || []).map((file) => file.name) })}/><button className="upload-zone" onClick={() => inputRef.current?.click()}><Upload size={20}/><strong>Загрузить файлы</strong><span>PDF, PNG, JPG, DOCX до 25 МБ</span></button></div>{files.map((file) => <div className="file-chip" key={file}><FileText size={16}/><span>{file}</span><Check size={15}/></div>)}</div>;
}

function LlmSettings({ node, updateConfig, models, modelsLoading, modelError }) {
  const fields = node.config.fields || [];
  const setFields = (next) => updateConfig({ fields: next });
  return <div className="llm-settings"><div className="litellm-card"><div className="litellm-heading"><div><span className="provider-logo">L</span><div><strong>LiteLLM</strong><small>OpenAI-совместимый шлюз</small></div></div><span className={`provider-status ${modelError ? "offline" : ""}`}><i/>{modelsLoading ? "Подключаемся" : modelError ? "Нет связи" : "Подключено"}</span></div><div className="field-group"><Label>Модель этого узла</Label><Select value={node.config.model || ""} onValueChange={(value) => updateConfig({ model: value })} disabled={modelsLoading || !models.length}><SelectTrigger><SelectValue placeholder={modelsLoading ? "Загружаем модели…" : "Нет доступных моделей"}/></SelectTrigger><SelectContent>{models.map((model) => <SelectItem key={model} value={model}>{model}</SelectItem>)}</SelectContent></Select><small className={`model-help ${modelError ? "error" : ""}`}>{modelError || `${models.length} моделей доступно`}</small></div></div><Tabs defaultValue="prompt" className="settings-tabs"><TabsList className="grid w-full grid-cols-2"><TabsTrigger value="prompt">Промпт</TabsTrigger><TabsTrigger value="fields">Параметры</TabsTrigger></TabsList><TabsContent value="prompt" className="settings-body"><div className="field-group"><Label>Инструкция для модели</Label><Textarea rows={8} value={node.config.prompt || ""} onChange={(event) => updateConfig({ prompt: event.target.value })}/></div></TabsContent><TabsContent value="fields" className="settings-body"><p className="section-copy">Поля результата этого LLM-узла.</p><div className="field-list">{fields.map((field, index) => <div className="extract-field" key={field.id}><div className="field-index">{index + 1}</div><div><Input value={field.name} onChange={(event) => setFields(fields.map((item) => item.id === field.id ? { ...item, name: event.target.value } : item))}/><Textarea rows={2} value={field.description} onChange={(event) => setFields(fields.map((item) => item.id === field.id ? { ...item, description: event.target.value } : item))}/></div><button aria-label="Удалить поле" onClick={() => setFields(fields.filter((item) => item.id !== field.id))}><X size={15}/></button></div>)}</div><Button variant="outline" className="add-field" onClick={() => setFields([...fields, { id: Date.now(), name: "new_field", description: "Описание параметра" }])}><Plus size={16}/>Добавить параметр</Button></TabsContent></Tabs></div>;
}

function SettingSwitch({ title, copy, defaultChecked = false }) {
  return <div className="switch-row"><div><strong>{title}</strong><span>{copy}</span></div><Switch defaultChecked={defaultChecked}/></div>;
}
