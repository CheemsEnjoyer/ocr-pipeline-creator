"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, FileInput, FileText, Image, LoaderCircle, Plus, ScanText, Sparkles, Trash2, WandSparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

const stepMeta = [
  { number: 1, title: "Название", short: "Как назвать пайплайн" },
  { number: 2, title: "Источник", short: "Какие документы придут" },
  { number: 3, title: "Распознавание", short: "Как получить текст" },
  { number: 4, title: "Извлечение", short: "Что нужно получить" },
];

const initialFields = [
  { id: 1, name: "document_number", description: "Номер документа" },
  { id: 2, name: "total_amount", description: "Итоговая сумма с валютой" },
];

export default function Home() {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("Обработка входящих счетов");
  const [sourceType, setSourceType] = useState("scans");
  const [ocrMode, setOcrMode] = useState("litellm");
  const [ocrModel, setOcrModel] = useState("");
  const [ocrServiceUrl, setOcrServiceUrl] = useState("");
  const [visionPrompt, setVisionPrompt] = useState("Распознай весь текст на изображении, сохрани структуру документа и верни результат без комментариев.");
  const [skipExtraction, setSkipExtraction] = useState(false);
  const [extractionMode, setExtractionMode] = useState("fields");
  const [prompt, setPrompt] = useState("Проанализируй документ и верни структурированный JSON без дополнительного текста.");
  const [fields, setFields] = useState(initialFields);
  const [llmModel, setLlmModel] = useState("");
  const [maxTokens, setMaxTokens] = useState(2048);
  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelError, setModelError] = useState("");
  const [created, setCreated] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/litellm/models", { signal: controller.signal })
      .then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || "Не удалось получить модели"); return data.models || []; })
      .then((available) => { setModels(available); setLlmModel(available[0] || ""); setOcrModel(available[0] || ""); setModelError(available.length ? "" : "В LiteLLM нет доступных моделей"); })
      .catch((error) => { if (!(error instanceof DOMException && error.name === "AbortError")) setModelError(error.message || "LiteLLM недоступен"); })
      .finally(() => setModelsLoading(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (sourceType !== "scans" || ocrMode !== "litellm") setSkipExtraction(false);
  }, [sourceType, ocrMode]);

  const isValid = useMemo(() => {
    if (step === 1) return name.trim().length >= 3;
    if (step === 2) return Boolean(sourceType);
    if (step === 3 && sourceType === "scans") return ocrMode === "litellm" ? Boolean(ocrModel) && visionPrompt.trim().length > 0 : /^https?:\/\//.test(ocrServiceUrl);
    if (step === 4) return skipExtraction || (Boolean(llmModel) && maxTokens >= 1 && (extractionMode === "prompt" ? prompt.trim().length > 0 : fields.length > 0 && fields.every((field) => field.name.trim() && field.description.trim())));
    return true;
  }, [step, name, sourceType, ocrMode, ocrModel, ocrServiceUrl, visionPrompt, skipExtraction, llmModel, maxTokens, extractionMode, prompt, fields]);

  const pipeline = {
    name: name.trim(), source: sourceType,
    ocr: sourceType === "scans" ? (ocrMode === "litellm" ? { provider: "litellm", model: ocrModel, prompt: visionPrompt } : { provider: "service", url: ocrServiceUrl }) : null,
    extraction: skipExtraction ? null : { mode: extractionMode, model: llmModel, max_tokens: Number(maxTokens), ...(extractionMode === "prompt" ? { prompt } : { fields: fields.map(({ name, description }) => ({ name, description })) }) },
  };

  const next = () => { if (!isValid) return; if (step === 3 && skipExtraction) setCreated(true); else if (step < 4) setStep(step + 1); else setCreated(true); };
  const addField = () => setFields([...fields, { id: Date.now(), name: "", description: "" }]);

  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    try { void Promise.resolve(context.registerTool({
      name: "configure_ocr_pipeline", title: "Настроить OCR-пайплайн", description: "Заполняет основные параметры мастера создания OCR-пайплайна.",
      inputSchema: { type: "object", properties: { name: { type: "string" }, source: { type: "string", enum: ["scans", "document"] }, extractionMode: { type: "string", enum: ["prompt", "fields"] }, model: { type: "string" }, maxTokens: { type: "integer", minimum: 1 } }, required: ["name", "source", "extractionMode", "model", "maxTokens"], additionalProperties: false },
      annotations: { readOnlyHint: false, untrustedContentHint: false }, execute(input) { setName(input.name); setSourceType(input.source); setExtractionMode(input.extractionMode); setLlmModel(input.model); setMaxTokens(input.maxTokens); setStep(4); return { configured: true, name: input.name }; },
    }, { signal: lifecycle.signal })).catch(() => undefined); } catch { /* WebMCP is optional. */ }
    return () => lifecycle.abort();
  }, []);

  if (created) return <main className="app-shell success-shell"><div className="success-card"><div className="success-icon"><Check size={28}/></div><p className="eyebrow">ПАЙПЛАЙН ГОТОВ</p><h1>{pipeline.name}</h1><p>Конфигурация собрана. Её можно сохранить в PostgreSQL и использовать для обработки документов.</p><PipelineSummary pipeline={pipeline}/><div className="success-actions"><Button variant="outline" onClick={() => setCreated(false)}>Изменить настройки</Button><Button onClick={() => { setCreated(false); setStep(1); setName(""); }}>Создать ещё один</Button></div></div></main>;

  return <main className="app-shell">
    <header className="topbar"><div className="brand"><div className="brand-mark"><ScanText size={21}/></div><div><strong>OCR Flow</strong><span>Создание пайплайна</span></div></div><div className="draft-state"><span/>Черновик сохраняется автоматически</div><Button variant="outline" size="sm">Выйти</Button></header>
    <div className="wizard-layout">
      <aside className="step-sidebar"><div><p className="eyebrow">НОВЫЙ ПАЙПЛАЙН</p><h2>Ответьте на 4 вопроса</h2><p className="sidebar-copy">Мы соберём готовую конфигурацию обработки документов.</p></div><nav aria-label="Шаги настройки">{stepMeta.map((item) => { const disabled = item.number === 4 && skipExtraction; return <button key={item.number} disabled={disabled} className={`${step === item.number ? "active" : ""} ${step > item.number ? "complete" : ""} ${disabled ? "disabled" : ""}`} onClick={() => !disabled && setStep(item.number)}><span>{disabled ? <X size={14}/> : step > item.number ? <Check size={15}/> : item.number}</span><div><strong>{item.title}</strong><small>{disabled ? "Отключено в настройках Vision" : item.short}</small></div></button>; })}</nav><div className="sidebar-note"><WandSparkles size={17}/><span><strong>Без сложной схемы</strong>Пайплайн создаётся из ответов и готов к запуску.</span></div></aside>

      <section className="question-area"><div className="progress-row"><span>Шаг {step} из 4</span><div><i style={{ width: `${step * 25}%` }}/></div><strong>{step * 25}%</strong></div><div className="question-card">
        {step === 1 && <StepName name={name} setName={setName}/>} 
        {step === 2 && <StepSource sourceType={sourceType} setSourceType={setSourceType}/>} 
        {step === 3 && <StepOcr sourceType={sourceType} ocrMode={ocrMode} setOcrMode={setOcrMode} ocrModel={ocrModel} setOcrModel={setOcrModel} ocrServiceUrl={ocrServiceUrl} setOcrServiceUrl={setOcrServiceUrl} visionPrompt={visionPrompt} setVisionPrompt={setVisionPrompt} skipExtraction={skipExtraction} setSkipExtraction={setSkipExtraction} models={models} modelsLoading={modelsLoading} modelError={modelError}/>} 
        {step === 4 && <StepExtraction extractionMode={extractionMode} setExtractionMode={setExtractionMode} prompt={prompt} setPrompt={setPrompt} fields={fields} setFields={setFields} addField={addField} llmModel={llmModel} setLlmModel={setLlmModel} maxTokens={maxTokens} setMaxTokens={setMaxTokens} models={models} modelsLoading={modelsLoading} modelError={modelError}/>} 
        <div className="question-actions"><Button variant="ghost" onClick={() => setStep(Math.max(1, step - 1))} disabled={step === 1}><ArrowLeft size={16}/>Назад</Button><div>{!isValid && <span className="validation-hint">Заполните обязательные поля</span>}<Button onClick={next} disabled={!isValid}>{step === 4 || (step === 3 && skipExtraction) ? "Создать пайплайн" : "Продолжить"}{step < 4 && !(step === 3 && skipExtraction) && <ArrowRight size={16}/>}</Button></div></div>
      </div></section>

      <aside className="summary-panel"><div className="summary-head"><span>КОНФИГУРАЦИЯ</span><strong>{name.trim() || "Без названия"}</strong></div><SummaryRow number="01" label="Источник" value={sourceType === "scans" ? "Сканы и изображения" : "Цифровой документ"}/><SummaryRow number="02" label="Получение текста" value={sourceType !== "scans" ? "Прямое извлечение" : ocrMode === "litellm" ? (ocrModel || "Модель не выбрана") : (ocrServiceUrl || "Сервис не указан")}/><SummaryRow number="03" label="Извлечение данных" value={skipExtraction ? "Отключено — ответ Vision финальный" : extractionMode === "prompt" ? "Свободный промпт" : `${fields.length} параметра`}/><SummaryRow number="04" label="LLM" value={skipExtraction ? "Не используется" : llmModel || "Модель не выбрана"}/><div className="token-summary"><span>{skipExtraction ? "Финальный результат" : "Лимит ответа"}</span><strong>{skipExtraction ? "Ответ Vision-модели" : `${Number(maxTokens).toLocaleString("ru-RU")} tokens`}</strong></div></aside>
    </div>
  </main>;
}

function StepName({ name, setName }) { return <div className="step-content"><StepHeading icon={FileInput} kicker="НАЧНЁМ С ОСНОВНОГО" title="Как назовём пайплайн?" copy="Название поможет быстро найти его в списке и понять назначение."/><div className="main-field"><Label htmlFor="pipeline-name">Название пайплайна</Label><Input id="pipeline-name" autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="Например, обработка входящих счетов"/><small>{name.length} / 80</small></div><div className="example-line"><span>Примеры</span><button onClick={() => setName("Распознавание актов")}>Распознавание актов</button><button onClick={() => setName("Разбор договоров")}>Разбор договоров</button></div></div>; }

function StepSource({ sourceType, setSourceType }) { return <div className="step-content"><StepHeading icon={FileText} kicker="ТИП ИСХОДНЫХ ФАЙЛОВ" title="Откуда нужно получить текст?" copy="От ответа зависит, потребуется ли этап OCR."/><RadioGroup value={sourceType} onValueChange={setSourceType} className="choice-grid"><ChoiceCard value="scans" icon={Image} title="Сканы или изображения" copy="PNG, JPG и PDF-сканы без текстового слоя" badge="Потребуется OCR"/><ChoiceCard value="document" icon={FileText} title="Цифровой документ" copy="PDF, DOCX, TXT и другие файлы с текстом" badge="Текст извлекается напрямую"/></RadioGroup></div>; }

function StepOcr({ sourceType, ocrMode, setOcrMode, ocrModel, setOcrModel, ocrServiceUrl, setOcrServiceUrl, visionPrompt, setVisionPrompt, skipExtraction, setSkipExtraction, models, modelsLoading, modelError }) {
  if (sourceType !== "scans") return <div className="step-content"><StepHeading icon={Check} kicker="OCR НЕ ПОТРЕБУЕТСЯ" title="Текст извлечём напрямую" copy="Вы выбрали цифровые документы. Система прочитает их текстовый слой без распознавания изображения."/><div className="skip-card"><FileText size={24}/><div><strong>Извлечение текста из документа</strong><span>PDF · DOCX · TXT · HTML</span></div><Check size={20}/></div></div>;
  return <div className="step-content"><StepHeading icon={ScanText} kicker="РАСПОЗНАВАНИЕ" title="Как будем распознавать сканы?" copy="Используйте vision-модель через LiteLLM или подключите отдельный OCR-сервис."/><RadioGroup value={ocrMode} onValueChange={setOcrMode} className="method-grid"><MethodCard value="litellm" title="Vision-модель LiteLLM" copy="Выберите одну из доступных моделей"/><MethodCard value="service" title="Внешний OCR-сервис" copy="Укажите HTTP endpoint своего сервиса"/></RadioGroup>{ocrMode === "litellm" ? <><ModelField label="OCR-модель" value={ocrModel} setValue={setOcrModel} models={models} modelsLoading={modelsLoading} modelError={modelError}/><div className="prompt-box vision-prompt"><Label htmlFor="vision-prompt">Промпт для Vision-модели</Label><Textarea id="vision-prompt" rows={4} value={visionPrompt} onChange={(event) => setVisionPrompt(event.target.value)} placeholder="Опишите, как распознать изображение и в каком виде вернуть результат…"/><small>{visionPrompt.length} / 4 000</small></div><div className="skip-extraction"><div><strong>Ответ Vision-модели уже финальный</strong><span>Отключить шаг 4 «Извлечение» и использовать ответ распознавания как результат пайплайна.</span></div><Switch checked={skipExtraction} onCheckedChange={setSkipExtraction} aria-label="Отключить шаг извлечения"/></div></> : <div className="main-field"><Label htmlFor="ocr-url">URL OCR-сервиса</Label><Input id="ocr-url" value={ocrServiceUrl} onChange={(event) => setOcrServiceUrl(event.target.value)} placeholder="https://ocr.example.com/v1/recognize"/><small>Сервис должен принимать файл по HTTPS и возвращать распознанный текст.</small></div>}</div>;
}

function StepExtraction({ extractionMode, setExtractionMode, prompt, setPrompt, fields, setFields, addField, llmModel, setLlmModel, maxTokens, setMaxTokens, models, modelsLoading, modelError }) {
  return <div className="step-content"><StepHeading icon={Sparkles} kicker="ОБРАБОТКА ЧЕРЕЗ LLM" title="Что нужно получить из текста?" copy="Можно написать свободную инструкцию или описать отдельные поля результата."/><div className="model-token-row"><ModelField label="Модель LiteLLM" value={llmModel} setValue={setLlmModel} models={models} modelsLoading={modelsLoading} modelError={modelError}/><div className="main-field compact"><Label htmlFor="max-tokens">max_tokens</Label><Input id="max-tokens" type="number" min="1" max="128000" value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)}/><small>Максимальный размер ответа</small></div></div><Tabs value={extractionMode} onValueChange={setExtractionMode} className="mode-tabs"><TabsList className="grid w-full grid-cols-2"><TabsTrigger value="prompt">Целый промпт</TabsTrigger><TabsTrigger value="fields">Отдельные параметры</TabsTrigger></TabsList><TabsContent value="prompt"><div className="prompt-box"><Label htmlFor="prompt">Инструкция для модели</Label><Textarea id="prompt" rows={7} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Опишите, что модель должна сделать с текстом документа…"/><small>{prompt.length} / 4 000</small></div></TabsContent><TabsContent value="fields"><div className="fields-intro"><span>Поля результата</span><Button variant="outline" size="sm" onClick={addField}><Plus size={15}/>Добавить поле</Button></div><div className="fields-list">{fields.map((field, index) => <div className="parameter-card" key={field.id}><span className="field-number">{index + 1}</span><div><Input value={field.name} onChange={(event) => setFields(fields.map((item) => item.id === field.id ? { ...item, name: event.target.value } : item))} placeholder="Название поля, например total"/><Textarea rows={2} value={field.description} onChange={(event) => setFields(fields.map((item) => item.id === field.id ? { ...item, description: event.target.value } : item))} placeholder="Что нужно извлечь и в каком формате"/></div><button className="remove-field" onClick={() => setFields(fields.filter((item) => item.id !== field.id))} aria-label="Удалить поле"><Trash2 size={16}/></button></div>)}</div></TabsContent></Tabs></div>;
}

function StepHeading({ icon: Icon, kicker, title, copy }) { return <div className="step-heading"><div className="heading-icon"><Icon size={21}/></div><div><p className="eyebrow">{kicker}</p><h1>{title}</h1><p>{copy}</p></div></div>; }
function ChoiceCard({ value, icon: Icon, title, copy, badge }) { return <Label className="choice-card"><RadioGroupItem value={value}/><div className="choice-icon"><Icon size={23}/></div><div><strong>{title}</strong><p>{copy}</p><span>{badge}</span></div></Label>; }
function MethodCard({ value, title, copy }) { return <Label className="method-card"><RadioGroupItem value={value}/><div><strong>{title}</strong><span>{copy}</span></div></Label>; }
function ModelField({ label, value, setValue, models, modelsLoading, modelError }) { return <div className="main-field model-field"><Label>{label}</Label><Select value={value} onValueChange={setValue} disabled={modelsLoading || !models.length}><SelectTrigger><SelectValue placeholder={modelsLoading ? "Загружаем модели…" : "Выберите модель"}/></SelectTrigger><SelectContent>{models.map((model) => <SelectItem key={model} value={model}>{model}</SelectItem>)}</SelectContent></Select><small className={modelError ? "error" : ""}>{modelError || `${models.length} моделей доступно через LiteLLM`}</small></div>; }
function SummaryRow({ number, label, value }) { return <div className="summary-row"><span>{number}</span><div><small>{label}</small><strong>{value}</strong></div></div>; }
function PipelineSummary({ pipeline }) { return <div className="final-summary"><div><span>Источник</span><strong>{pipeline.source === "scans" ? "Сканы / изображения" : "Цифровой документ"}</strong></div><div><span>OCR</span><strong>{pipeline.ocr ? (pipeline.ocr.model || pipeline.ocr.url) : "Не требуется"}</strong></div><div><span>Извлечение</span><strong>{pipeline.extraction ? (pipeline.extraction.mode === "prompt" ? "Промпт" : `${pipeline.extraction.fields.length} параметра`) : "Отключено"}</strong></div><div><span>LLM</span><strong>{pipeline.extraction ? `${pipeline.extraction.model} · ${pipeline.extraction.max_tokens} tokens` : "Ответ Vision-модели"}</strong></div></div>; }
