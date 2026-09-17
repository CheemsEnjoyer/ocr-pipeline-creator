"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, FileInput, FileText, Image, ScanText, Sparkles } from "lucide-react";
import Header from "@/components/Header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import ExtractionFields from "@/components/ExtractionFields";
import { validFields, serializeFields } from "@/lib/extraction-fields";
import { savePipeline } from "@/lib/pipelines";

const validPipelineId = (value) => /^[a-zA-Z0-9_-]{1,80}$/.test(value);
const sanitizePipelineId = (value) => value.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 80);
// Redis transport uses inverse priority values: 0 is highest, 9 is lowest.
const PRIORITIES = [[9, "Низкий"], [5, "Обычный"], [0, "Высокий"]];

const validTemperature = (value) => String(value).trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 2;
const validConcurrency = (value) => Number.isInteger(Number(value)) && Number(value) >= 1 && Number(value) <= 30;

const stepMeta = [
  { number: 1, title: "Название", short: "Как назвать пайплайн" },
  { number: 2, title: "Источник", short: "Какие документы придут" },
  { number: 3, title: "Обработка", short: "Промпт и поля результата" },
];

const initialFields = [
  { id: 1, name: "document_number", description: "Номер документа" },
  { id: 2, name: "total_amount", description: "Итоговая сумма с валютой" },
];

export default function PipelineEditor({ initialPipeline = null, onCreateNew }) {
  const [step, setStep] = useState(1);
  const [pipelineId, setPipelineId] = useState(initialPipeline?.id ?? "");
  const [name, setName] = useState(initialPipeline?.name ?? "Обработка входящих счетов");
  const [description, setDescription] = useState(initialPipeline?.description ?? "");
  const [priority, setPriority] = useState(initialPipeline?.priority ?? 5);
  const [allowSync, setAllowSync] = useState(initialPipeline?.allow_sync ?? true);
  const [allowAsync, setAllowAsync] = useState(initialPipeline?.allow_async ?? true);
  const [asyncConcurrency, setAsyncConcurrency] = useState(initialPipeline?.async_concurrency ?? 1);
  const [sourceType, setSourceType] = useState(initialPipeline?.source ?? "scans");
  const [ocrMode, setOcrMode] = useState(initialPipeline?.ocr?.provider ?? "litellm");
  const [ocrModel, setOcrModel] = useState(initialPipeline?.ocr?.model ?? "");
  const [ocrServiceUrl, setOcrServiceUrl] = useState(initialPipeline?.ocr?.url ?? "");
  const [visionPrompt, setVisionPrompt] = useState(initialPipeline?.ocr?.prompt ?? "Распознай весь текст на изображении, сохрани структуру документа и верни результат без комментариев.");
  const [ocrEnabled, setOcrEnabled] = useState(initialPipeline ? Boolean(initialPipeline.ocr) && initialPipeline.ocr.enabled !== false : true);
  const [promptRequested, setPromptEnabled] = useState(initialPipeline?.extraction?.prompt_enabled ?? initialPipeline?.extraction?.mode === "prompt");
  const [fieldsEnabled, setFieldsEnabled] = useState(initialPipeline ? (initialPipeline.extraction?.fields_enabled ?? initialPipeline.extraction?.mode === "fields") : true);
  const promptAllowed = !(sourceType === "scans" && ocrEnabled && ocrMode === "litellm");
  const promptEnabled = promptAllowed && promptRequested;
  const skipExtraction = !promptEnabled && !fieldsEnabled;
  const [prompt, setPrompt] = useState(initialPipeline?.extraction?.prompt ?? "Извлеки нужный текст из документа, сохрани его структуру и верни без комментариев.");
  const [fields, setFields] = useState(() => initialPipeline?.extraction?.fields?.map((field, index) => ({ ...field, id: index + 1 })) ?? initialFields);
  const [llmModel, setLlmModel] = useState(initialPipeline?.extraction?.model ?? "");
  const [ocrTemperature, setOcrTemperature] = useState(initialPipeline?.ocr?.temperature ?? 0);
  const [extractionTemperature, setExtractionTemperature] = useState(initialPipeline?.extraction?.temperature ?? 0);
  const [maxTokens, setMaxTokens] = useState(initialPipeline?.extraction?.max_tokens ?? 2048);
  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelError, setModelError] = useState("");
  const [created, setCreated] = useState(false);
  const savingRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [savedId, setSavedId] = useState(initialPipeline?.id);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/litellm/models", { signal: controller.signal })
      .then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || "Не удалось получить модели"); return data.models || []; })
      .then((available) => { setModels(available); setLlmModel((current) => current || available[0] || ""); setOcrModel((current) => current || available[0] || ""); setModelError(available.length ? "" : "В LiteLLM нет доступных моделей"); })
      .catch((error) => { if (!(error instanceof DOMException && error.name === "AbortError")) setModelError(error.message || "LiteLLM недоступен"); })
      .finally(() => setModelsLoading(false));
    return () => controller.abort();
  }, []);


  const isValid = useMemo(() => {
    if (step === 1) return name.trim().length >= 3 && validPipelineId(pipelineId) && (allowSync || allowAsync) && (!allowAsync || validConcurrency(asyncConcurrency));
    if (step === 2) return Boolean(sourceType);
    if (step === 3) {
      const ocrValid = sourceType !== "scans" || !ocrEnabled || (ocrMode === "litellm" ? Boolean(ocrModel) && validTemperature(ocrTemperature) && visionPrompt.trim().length > 0 : /^https?:\/\//.test(ocrServiceUrl));
      const fieldsValid = validFields(fields);
      return ocrValid && (skipExtraction || (validTemperature(extractionTemperature) && Boolean(llmModel) && Number.isInteger(Number(maxTokens)) && maxTokens >= 1 && maxTokens <= 128000 && (!promptEnabled || prompt.trim().length > 0) && (!fieldsEnabled || fieldsValid)));
    }
    return true;
  }, [ocrEnabled, ocrTemperature, extractionTemperature, step, name, pipelineId, allowSync, allowAsync, asyncConcurrency, sourceType, ocrMode, ocrModel, ocrServiceUrl, visionPrompt, skipExtraction, llmModel, maxTokens, promptEnabled, fieldsEnabled, prompt, fields]);

  // Поля формы сохранённого пайплайна не теряются при редактировании.
  const serviceOptions = initialPipeline?.ocr?.url === ocrServiceUrl ? initialPipeline?.ocr?.options ?? {} : {};

  const pipeline = {
    id: pipelineId, name: name.trim(), description: description.trim(), priority: Number(priority), allow_sync: allowSync, allow_async: allowAsync, async_concurrency: Number(asyncConcurrency), source: sourceType,
    ocr: sourceType === "scans" ? (ocrMode === "litellm" ? { enabled: ocrEnabled, provider: "litellm", model: ocrModel, temperature: Number(ocrTemperature), prompt: visionPrompt } : { enabled: ocrEnabled, provider: "service", url: ocrServiceUrl || null, ...(Object.keys(serviceOptions).length ? { options: serviceOptions } : {}) }) : null,
    extraction: { mode: fieldsEnabled ? "fields" : "prompt", prompt_enabled: promptEnabled, fields_enabled: fieldsEnabled, model: llmModel, max_tokens: Number(maxTokens), temperature: Number(extractionTemperature), prompt, fields: serializeFields(fields) },
  };

  const finish = async () => {
    if (savingRef.current) return;
    setSaveError("");
    if (!validPipelineId(pipelineId)) { setSaveError("Укажите ID: от 1 до 80 латинских букв, цифр, символов _ или -."); setStep(1); return; }
    const fieldsValid = validFields(fields);
    if (name.trim().length < 3 || (!allowSync && !allowAsync) || (allowAsync && !validConcurrency(asyncConcurrency)) || (sourceType === "scans" && ocrEnabled && (ocrMode === "litellm" ? !ocrModel || !validTemperature(ocrTemperature) || !visionPrompt.trim() : !/^https?:\/\//.test(ocrServiceUrl))) || (!skipExtraction && (!validTemperature(extractionTemperature) || !llmModel || Number(maxTokens) < 1 || Number(maxTokens) > 128000 || !Number.isInteger(Number(maxTokens)) || ((promptEnabled && !prompt.trim()) || (fieldsEnabled && !fieldsValid))))) {
      setSaveError("Проверьте название, настройки OCR и извлечения. Названия полей должны быть уникальными."); return;
    }
    savingRef.current = true;
    setSaving(true);
    try { const saved = await savePipeline(pipeline, savedId); setSavedId(saved.id); setCreated(true); }
    catch (error) { setSaveError(error.message); }
    finally { savingRef.current = false; setSaving(false); }
  };
  const next = () => { if (!isValid) return; if (step < 3) setStep(step + 1); else finish(); };

  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    try { void Promise.resolve(context.registerTool({
      name: "configure_ocr_pipeline", title: "Настроить OCR-пайплайн", description: "Заполняет основные параметры мастера создания OCR-пайплайна.",
      inputSchema: { type: "object", properties: { id: { type: "string", pattern: "^[a-zA-Z0-9_-]{1,80}$" }, name: { type: "string" }, priority: { type: "integer", minimum: 0, maximum: 9 }, allowSync: { type: "boolean" }, allowAsync: { type: "boolean" }, asyncConcurrency: { type: "integer", minimum: 1, maximum: 30 }, source: { type: "string", enum: ["scans", "document"] }, extractionMode: { type: "string", enum: ["prompt", "fields"] }, promptEnabled: { type: "boolean" }, fieldsEnabled: { type: "boolean" }, model: { type: "string" }, maxTokens: { type: "integer", minimum: 1 } }, required: ["id", "name", "source", "model", "maxTokens"], additionalProperties: false },
      annotations: { readOnlyHint: false, untrustedContentHint: false }, execute(input) { if (!savedId) setPipelineId(sanitizePipelineId(input.id)); setName(input.name); setPriority(input.priority ?? 5); setAllowSync(input.allowSync ?? true); setAllowAsync(input.allowAsync ?? true); setAsyncConcurrency(input.asyncConcurrency ?? 1); setSourceType(input.source); setPromptEnabled(input.promptEnabled ?? input.extractionMode === "prompt"); setFieldsEnabled(input.fieldsEnabled ?? input.extractionMode !== "prompt"); setLlmModel(input.model); setMaxTokens(input.maxTokens); setStep(3); return { configured: true, name: input.name }; },
    }, { signal: lifecycle.signal })).catch(() => undefined); } catch { /* WebMCP is optional. */ }
    return () => lifecycle.abort();
  }, [savedId]);

  if (created) return <main className="app-shell success-shell"><div className="success-card"><div className="success-icon"><Check size={28}/></div><p className="eyebrow">ПАЙПЛАЙН ГОТОВ</p><h1>{pipeline.name}</h1><p>Пайплайн сохранён. Его можно выбрать для обработки или отредактировать на странице «Пайплайны».</p><PipelineSummary pipeline={pipeline}/><div className="success-actions"><Button variant="outline" onClick={() => setCreated(false)}>Продолжить редактирование</Button><Button variant="outline" onClick={() => { if (onCreateNew) onCreateNew(); else window.location.assign("/createpipeline"); }}>Создать ещё один</Button><Button variant="outline" asChild><a href="/pipelines">Все пайплайны</a></Button><Button asChild><a href="/">Загрузить документы<ArrowRight size={16}/></a></Button></div></div></main>;

  return <main className="app-shell">
    <Header subtitle={initialPipeline ? "Редактирование пайплайна" : "Создание пайплайна"}/>
    <div className="wizard-layout">
      <aside className="step-sidebar"><div><p className="eyebrow">{initialPipeline ? "РЕДАКТИРОВАНИЕ" : "НОВЫЙ ПАЙПЛАЙН"}</p><h2>Ответьте на 3 вопроса</h2><p className="sidebar-copy">Мы соберём готовую конфигурацию обработки документов.</p></div><nav aria-label="Шаги настройки">{stepMeta.map((item) => <button key={item.number} className={`${step === item.number ? "active" : ""} ${step > item.number ? "complete" : ""}`} onClick={() => setStep(item.number)}><span>{step > item.number ? <Check size={15}/> : item.number}</span><div><strong>{item.title}</strong><small>{item.short}</small></div></button>)}</nav></aside>

      <section className="question-area"><div className="progress-row"><span>Шаг {step} из 3</span><div><i style={{ width: `${Math.round(step / 3 * 100)}%` }}/></div><strong>{Math.round(step / 3 * 100)}%</strong></div><div className="question-card">
        {step === 1 && <StepName description={description} setDescription={setDescription} name={name} setName={setName} pipelineId={pipelineId} setPipelineId={setPipelineId} priority={priority} setPriority={setPriority} allowSync={allowSync} setAllowSync={setAllowSync} allowAsync={allowAsync} setAllowAsync={setAllowAsync} asyncConcurrency={asyncConcurrency} setAsyncConcurrency={setAsyncConcurrency} idLocked={Boolean(savedId)}/>}
        {step === 2 && <StepSource sourceType={sourceType} setSourceType={setSourceType}/>}
        {step === 3 && <div className="step-content"><StepHeading icon={Sparkles} kicker="ОБРАБОТКА ДОКУМЕНТА" title="Промпт и поля в одном этапе" copy="Включайте нужные действия независимо. Без промпта и полей результатом будет исходный текст."/>
          {sourceType === "scans" && <><ToggleSection title="Распознавание сканов" copy="Vision-модель с промптом или внешний OCR-сервис." checked={ocrEnabled} onChange={setOcrEnabled}/>{ocrEnabled ? <StepOcr temperature={ocrTemperature} setTemperature={setOcrTemperature} sourceType={sourceType} ocrMode={ocrMode} setOcrMode={setOcrMode} ocrModel={ocrModel} setOcrModel={setOcrModel} ocrServiceUrl={ocrServiceUrl} setOcrServiceUrl={setOcrServiceUrl} visionPrompt={visionPrompt} setVisionPrompt={setVisionPrompt} models={models} modelsLoading={modelsLoading} modelError={modelError}/> : <p className="sidebar-copy">Будет прочитан текстовый слой файла. Для изображений и PDF без текста включите распознавание.</p>}</>}
          <StepExtraction promptAllowed={promptAllowed} temperature={extractionTemperature} setTemperature={setExtractionTemperature} promptEnabled={promptEnabled} setPromptEnabled={setPromptEnabled} fieldsEnabled={fieldsEnabled} setFieldsEnabled={setFieldsEnabled} prompt={prompt} setPrompt={setPrompt} fields={fields} setFields={setFields} llmModel={llmModel} setLlmModel={setLlmModel} maxTokens={maxTokens} setMaxTokens={setMaxTokens} models={models} modelsLoading={modelsLoading} modelError={modelError}/>
        </div>}
        {saveError && <p className="history-error" role="alert">{saveError}</p>}<div className="question-actions"><Button variant="ghost" onClick={() => setStep(Math.max(1, step - 1))} disabled={saving || step === 1}><ArrowLeft size={16}/>Назад</Button><div>{!isValid && <span className="validation-hint">Заполните обязательные поля</span>}{initialPipeline && step < 3 && <Button variant="outline" onClick={finish} disabled={saving}>Сохранить изменения</Button>}<Button onClick={next} disabled={saving || !isValid}>{step === 3 ? (savedId ? "Сохранить изменения" : "Создать пайплайн") : "Продолжить"}{step < 3 && <ArrowRight size={16}/>}</Button></div></div>
      </div></section>

      <aside className="summary-panel"><div className="summary-head"><span>КОНФИГУРАЦИЯ</span><strong>{name.trim() || "Без названия"}</strong></div><SummaryRow number="01" label="Источник" value={sourceType === "scans" ? "Сканы и изображения" : "Цифровой документ"}/><SummaryRow number="02" label="Получение текста" value={sourceType !== "scans" || !ocrEnabled ? "Прямое извлечение" : ocrMode === "litellm" ? (ocrModel || "Модель не выбрана") : (ocrServiceUrl || "Сервис не указан")}/><SummaryRow number="03" label="Извлечение данных" value={skipExtraction ? "Отключено — исходный текст" : fieldsEnabled ? `${fields.length} полей${promptEnabled ? " + промпт" : ""}` : "Свободный промпт"}/><SummaryRow number="04" label="LLM" value={skipExtraction ? "Не используется" : llmModel || "Модель не выбрана"}/><SummaryRow number="05" label="Режимы" value={[allowSync && "Синхронный", allowAsync && `Асинхронный · ${asyncConcurrency}`].filter(Boolean).join(" + ")}/><SummaryRow number="06" label="Приоритет Celery" value={allowAsync ? `${PRIORITIES.find(([value]) => value === Number(priority))?.[1] ?? "Пользовательский"} · ${priority}` : "Не используется"}/><div className="token-summary"><span>{skipExtraction ? "Финальный результат" : "Лимит ответа"}</span><strong>{skipExtraction ? "Исходный текст" : `${Number(maxTokens).toLocaleString("ru-RU")} tokens`}</strong></div></aside>
    </div>
  </main>;
}

function StepName({ description, setDescription, name, setName, pipelineId, setPipelineId, priority, setPriority, allowSync, setAllowSync, allowAsync, setAllowAsync, asyncConcurrency, setAsyncConcurrency, idLocked }) {
  return <div className="step-content">
    <StepHeading icon={FileInput} kicker="НАЧНЁМ С ОСНОВНОГО" title="Как назовём пайплайн?" copy="Название поможет быстро найти его в списке и понять назначение."/>
    <div className="main-field"><Label htmlFor="pipeline-name">Название пайплайна</Label><Input id="pipeline-name" autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="Например, обработка входящих счетов"/><small>{name.length} / 80</small></div>
    <div className="main-field"><Label htmlFor="pipeline-id">ID пайплайна</Label><Input id="pipeline-id" value={pipelineId} readOnly={idLocked} maxLength={80} required spellCheck={false} autoCapitalize="none" aria-describedby="pipeline-id-help" aria-invalid={!idLocked && pipelineId.length > 0 && !validPipelineId(pipelineId)} onChange={(event) => setPipelineId(sanitizePipelineId(event.target.value))} placeholder="Например, invoices_2026"/><small id="pipeline-id-help">{idLocked ? "ID используется в API и не меняется после сохранения." : "Только латинские буквы, цифры, _ и -. Кириллица и пробелы не вводятся. После сохранения ID изменить нельзя."}</small></div>
    <div className="execution-settings">
      <ToggleSection title="Синхронный запуск" copy="Запрос ждёт завершения обработки и сразу получает результат." checked={allowSync} onChange={(checked) => { if (checked || allowAsync) setAllowSync(checked); }}/>
      <ToggleSection title="Асинхронный запуск" copy="Документ попадает в очередь Celery, результат запрашивается по ID задачи." checked={allowAsync} onChange={(checked) => { if (checked || allowSync) setAllowAsync(checked); }}/>
    </div>
    {allowAsync && <><div className="main-field"><Label htmlFor="async-concurrency">Одновременных документов</Label><Input id="async-concurrency" type="number" min="1" max="30" value={asyncConcurrency} onChange={(event) => setAsyncConcurrency(event.target.value)}/><small>От 1 до 30 документов этого пайплайна могут одновременно находиться в обработке Celery. Остальные ждут в очереди.</small></div><div className="main-field"><Label htmlFor="pipeline-priority">Приоритет фоновой обработки</Label><NativeSelect id="pipeline-priority" value={String(priority)} onChange={(event) => setPriority(Number(event.target.value))}>{PRIORITIES.map(([value, label]) => <NativeSelectOption key={value} value={String(value)}>{label} · {value}</NativeSelectOption>)}</NativeSelect><small>Высокий приоритет ставит новые фоновые задачи этого пайплайна раньше задач с обычным и низким приоритетом.</small></div></>}
    <div className="main-field"><Label htmlFor="pipeline-description">Публичное описание</Label><Textarea id="pipeline-description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Что делает пайплайн — видно клиенту в API"/></div>
    <div className="example-line"><span>Примеры</span><button onClick={() => setName("Распознавание актов")}>Распознавание актов</button><button onClick={() => setName("Разбор договоров")}>Разбор договоров</button></div>
  </div>;
}

function StepSource({ sourceType, setSourceType }) { return <div className="step-content"><StepHeading icon={FileText} kicker="ТИП ИСХОДНЫХ ФАЙЛОВ" title="Откуда нужно получить текст?" copy="От ответа зависит, потребуется ли этап OCR."/><RadioGroup value={sourceType} onValueChange={setSourceType} className="choice-grid"><ChoiceCard value="scans" icon={Image} title="Сканы или изображения" copy="PNG, JPG и PDF-сканы без текстового слоя" badge="Потребуется OCR"/><ChoiceCard value="document" icon={FileText} title="Цифровой документ" copy="PDF, DOCX, TXT и другие файлы с текстом" badge="Текст извлекается напрямую"/></RadioGroup></div>; }

function StepOcr({ temperature, setTemperature, sourceType, ocrMode, setOcrMode, ocrModel, setOcrModel, ocrServiceUrl, setOcrServiceUrl, visionPrompt, setVisionPrompt, models, modelsLoading, modelError }) {
  if (sourceType !== "scans") return <div className="step-content"><StepHeading icon={Check} kicker="OCR НЕ ПОТРЕБУЕТСЯ" title="Текст извлечём напрямую" copy="Вы выбрали цифровые документы. Система прочитает их текстовый слой без распознавания изображения."/><div className="skip-card"><FileText size={24}/><div><strong>Извлечение текста из документа</strong><span>PDF · DOCX · TXT · HTML</span></div><Check size={20}/></div></div>;
  return <div className="step-content"><StepHeading icon={ScanText} kicker="РАСПОЗНАВАНИЕ" title="Как будем распознавать сканы?" copy="Используйте vision-модель через LiteLLM или подключите отдельный OCR-сервис."/><RadioGroup value={ocrMode} onValueChange={setOcrMode} className="method-grid"><MethodCard value="litellm" title="Vision-модель LiteLLM" copy="Выберите одну из доступных моделей"/><MethodCard value="service" title="Внешний OCR-сервис" copy="Укажите HTTP endpoint своего сервиса"/></RadioGroup>{ocrMode === "litellm" ? <><ModelField label="OCR-модель" value={ocrModel} setValue={setOcrModel} models={models} modelsLoading={modelsLoading} modelError={modelError}/><TemperatureField id="ocr-temperature" value={temperature} setValue={setTemperature}/><div className="prompt-box vision-prompt"><Label htmlFor="vision-prompt">Промпт для Vision-модели</Label><Textarea id="vision-prompt" rows={4} value={visionPrompt} onChange={(event) => setVisionPrompt(event.target.value)} placeholder="Опишите, как распознать изображение и в каком виде вернуть результат…"/><small>{visionPrompt.length} / 4 000</small></div></> : <div className="main-field"><Label htmlFor="ocr-url">URL OCR-сервиса</Label><Input id="ocr-url" value={ocrServiceUrl} onChange={(event) => setOcrServiceUrl(event.target.value)} placeholder="https://ocr.example.com/v1/recognize"/><small>Сервис должен принимать файл по HTTPS и возвращать распознанный текст. Если он доступен только через корпоративный прокси, задайте PROXY_URL в .env.</small></div>}</div>;
}

function ToggleSection({ title, copy, checked, onChange }) { return <div className="skip-extraction"><div><strong>{title}</strong><span>{copy}</span></div><Switch checked={checked} onCheckedChange={onChange} aria-label={title}/></div>; }

function StepExtraction({ promptAllowed, temperature, setTemperature, promptEnabled, setPromptEnabled, fieldsEnabled, setFieldsEnabled, prompt, setPrompt, fields, setFields, llmModel, setLlmModel, maxTokens, setMaxTokens, models, modelsLoading, modelError }) {
  return <div className="step-content">
    {promptAllowed && <ToggleSection title="Промпт" copy="Свободная инструкция для получения текста. Вместе с полями задаёт правила их извлечения." checked={promptEnabled} onChange={setPromptEnabled}/>}
    {promptEnabled && <div className="prompt-box"><Label htmlFor="prompt">Инструкция для модели</Label><Textarea id="prompt" rows={5} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Опишите, какой текст или данные нужно получить…"/></div>}
    <ToggleSection title="Поля извлечения" copy={promptAllowed ? "Результат в JSON по заданным полям. Можно использовать с промптом или отдельно." : "Результат в JSON по заданным полям из распознанного текста."} checked={fieldsEnabled} onChange={setFieldsEnabled}/>
    {fieldsEnabled && <ExtractionFields fields={fields} onChange={setFields}/>}
    {(promptEnabled || fieldsEnabled) && <><div className="model-token-row"><ModelField label="Модель LiteLLM" value={llmModel} setValue={setLlmModel} models={models} modelsLoading={modelsLoading} modelError={modelError}/><div className="main-field compact"><Label htmlFor="max-tokens">max_tokens</Label><Input id="max-tokens" type="number" min="1" max="128000" value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)}/><small>Максимальный размер ответа</small></div></div><TemperatureField id="extraction-temperature" value={temperature} setValue={setTemperature}/></>}
  </div>;
}

function StepHeading({ icon: Icon, kicker, title, copy }) { return <div className="step-heading"><div className="heading-icon"><Icon size={21}/></div><div><p className="eyebrow">{kicker}</p><h1>{title}</h1><p>{copy}</p></div></div>; }
function ChoiceCard({ value, icon: Icon, title, copy, badge }) { return <Label className="choice-card"><RadioGroupItem value={value}/><div className="choice-icon"><Icon size={23}/></div><div><strong>{title}</strong><p>{copy}</p><span>{badge}</span></div></Label>; }
function MethodCard({ value, title, copy }) { return <Label className="method-card"><RadioGroupItem value={value}/><div><strong>{title}</strong><span>{copy}</span></div></Label>; }
function TemperatureField({ id, value, setValue }) {
  const valid = validTemperature(value);
  return <div className="main-field"><Label htmlFor={id}>Температура</Label><Input id={id} type="number" min="0" max="2" step="0.1" value={value} onChange={(event) => setValue(event.target.value)} aria-invalid={!valid} aria-describedby={id + "-hint"}/><small id={id + "-hint"} className={valid ? "" : "error"}>{valid ? "От 0 до 2. Низкие значения уменьшают вариативность ответа. Для документов рекомендуется 0." : "Введите число от 0 до 2."}</small></div>;
}
function ModelField({ label, value, setValue, models, modelsLoading, modelError }) { return <div className="main-field model-field"><Label>{label}</Label><Select value={value} onValueChange={setValue} disabled={modelsLoading && !value}><SelectTrigger><SelectValue placeholder={modelsLoading ? "Загружаем модели…" : "Выберите модель"}/></SelectTrigger><SelectContent>{value && !models.includes(value) && <SelectItem value={value}>{value}</SelectItem>}{models.map((model) => <SelectItem key={model} value={model}>{model}</SelectItem>)}</SelectContent></Select><small className={modelError ? "error" : ""}>{modelError || `${models.length} моделей доступно через LiteLLM`}</small></div>; }
function SummaryRow({ number, label, value }) { return <div className="summary-row"><span>{number}</span><div><small>{label}</small><strong>{value}</strong></div></div>; }
function PipelineSummary({ pipeline }) { return <div className="final-summary"><div><span>ID пайплайна</span><strong>{pipeline.id}</strong></div><div><span>Режимы</span><strong>{[pipeline.allow_sync && "Синхронный", pipeline.allow_async && `Асинхронный · до ${pipeline.async_concurrency}`].filter(Boolean).join(" + ")}</strong></div><div><span>Приоритет Celery</span><strong>{pipeline.allow_async ? `${PRIORITIES.find(([value]) => value === pipeline.priority)?.[1] ?? pipeline.priority} · ${pipeline.priority}` : "Не используется"}</strong></div><div><span>Источник</span><strong>{pipeline.source === "scans" ? "Сканы / изображения" : "Цифровой документ"}</strong></div><div><span>OCR</span><strong>{pipeline.ocr && pipeline.ocr.enabled !== false ? (pipeline.ocr.model || pipeline.ocr.url) : "Не требуется"}</strong></div><div><span>Извлечение</span><strong>{pipeline.extraction && (pipeline.extraction.prompt_enabled || pipeline.extraction.fields_enabled) ? (pipeline.extraction.fields_enabled ? `${pipeline.extraction.fields.length} полей${pipeline.extraction.prompt_enabled ? " + промпт" : ""}` : "Промпт") : "Отключено"}</strong></div><div><span>LLM</span><strong>{pipeline.extraction && (pipeline.extraction.prompt_enabled || pipeline.extraction.fields_enabled) ? `${pipeline.extraction.model} · ${pipeline.extraction.max_tokens} tokens` : "Исходный текст"}</strong></div></div>; }
