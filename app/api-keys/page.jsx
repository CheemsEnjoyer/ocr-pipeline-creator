"use client";

import { useEffect, useState } from "react";
import { Copy, KeyRound, Pencil, ShieldOff } from "lucide-react";
import Header from "@/components/Header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { usePipelines } from "@/hooks/use-pipelines";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel } from "@/components/ui/alert-dialog";

async function api(url, method = "GET", body, signal) {
  const response = await fetch(url, { method, signal, ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  if (response.status === 401) window.location.assign("/login");
  if (!response.ok) throw new Error(data.error || "Не удалось выполнить запрос");
  return data;
}

export default function APIKeysPage() {
  const { pipelines, ready, error: pipelineError } = usePipelines();
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [ids, setIds] = useState([]);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [secret, setSecret] = useState("");
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    api("/api/keys", "GET", undefined, controller.signal).then((data) => setKeys(data.keys))
      .catch((error) => { if (error.name !== "AbortError") setError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  const reset = () => { setEditing(null); setName(""); setIds([]); };
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(editing ? `/api/keys/${editing}` : "/api/keys", editing ? "PATCH" : "POST", { name: name.trim(), pipeline_ids: ids });
      setKeys((current) => [data.key, ...current.filter((key) => key.id !== data.key.id)]);
      if (data.token) { setSecret(data.token); setCopied(false); }
      reset();
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  };
  const revoke = async () => {
    setBusy(true);
    setError("");
    try {
      await api(`/api/keys/${revoking.id}`, "DELETE");
      setKeys((current) => current.map((key) => key.id === revoking.id ? { ...key, revoked_at: new Date().toISOString() } : key));
      if (editing === revoking.id) reset();
      setRevoking(null);
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  };
  const logout = async () => {
    setBusy(true);
    try { await api("/api/auth/logout", "POST"); window.location.assign("/login"); }
    catch (error) { setError(error.message); setBusy(false); }
  };

  return <main className="app-shell"><Header subtitle="API-ключи"/>
    <div className="api-keys-page">
      <div className="pipelines-heading"><div><h1>Доступ к API</h1><p>Создайте отдельный ключ для каждой интеграции и выберите доступные ей пайплайны.</p></div><Button variant="outline" disabled={busy} onClick={logout}>Выйти</Button></div>
      {(error || pipelineError) && <p className="history-error" role="alert">{error || pipelineError}</p>}
      <div className="api-keys-layout">
        <form className="api-key-form" onSubmit={submit}>
          <h2>{editing ? "Настройки ключа" : "Новый API-ключ"}</h2>
          <Label htmlFor="key-name">Название интеграции</Label>
          <Input id="key-name" placeholder="Например, 1С: Бухгалтерия" value={name} maxLength={120} disabled={busy} required onChange={(event) => setName(event.target.value)}/>
          <fieldset disabled={busy || !ready}><legend>Доступные пайплайны</legend>
            {!ready && <p role="status">Загружаем пайплайны…</p>}
            {ready && !pipelines.length && <p>Сначала создайте пайплайн в конструкторе.</p>}
            <div className="key-pipeline-list">{pipelines.map((pipeline) => <label key={pipeline.id}>
              <Checkbox checked={ids.includes(pipeline.id)} onCheckedChange={(checked) => setIds((current) => checked ? [...current, pipeline.id] : current.filter((id) => id !== pipeline.id))}/>
              <span>{pipeline.name || "Без названия"}</span>
            </label>)}</div>
          </fieldset>
          <small>Ключ разрешает просмотр и запуск только выбранных пайплайнов. Управление приложением ему недоступно.</small>
          <Button type="submit" disabled={busy || !ready || Boolean(pipelineError) || !name.trim() || !ids.length || Boolean(secret)}>{busy ? "Сохраняем…" : editing ? "Сохранить доступ" : "Сгенерировать ключ"}</Button>
          {editing && <Button type="button" variant="outline" disabled={busy} onClick={reset}>Отмена</Button>}
        </form>
        <section className="api-key-list" aria-label="Созданные API-ключи">
          {loading && <p role="status">Загружаем ключи…</p>}
          {!loading && !keys.length && <div className="history-empty"><KeyRound/><p>API-ключей пока нет.</p></div>}
          {keys.map((key) => <article className="api-key-card" key={key.id}>
            <div className="api-key-card-title"><h2>{key.name}</h2><span>{key.revoked_at ? "Отозван" : "Активен"}</span></div>
            <code>{key.prefix}…</code>
            <p>Создан {new Date(key.created_at).toLocaleString("ru-RU")}</p>
            <ul>{key.pipeline_ids.map((id) => <li key={id}>{pipelines.find((pipeline) => pipeline.id === id)?.name || "Пайплайн удалён или недоступен"}<small>{id}</small></li>)}</ul>
            {!key.revoked_at && <div className="api-key-actions">
              <Button variant="outline" size="sm" disabled={busy} onClick={() => { setEditing(key.id); setName(key.name); setIds(key.pipeline_ids.filter((id) => pipelines.some((pipeline) => pipeline.id === id))); setError(""); }}><Pencil size={15}/>Изменить доступ</Button>
              <Button variant="destructive" size="sm" disabled={busy} onClick={() => { setError(""); setRevoking(key); }}><ShieldOff size={15}/>Отозвать</Button>
            </div>}
          </article>)}
        </section>
      </div>
      <div className="api-key-help"><h2>Использование</h2><p>Передавайте ключ в заголовке <code>Authorization: Bearer ВАШ_КЛЮЧ</code>.</p><p><code>GET /api/pipelines</code> — доступные пайплайны.<br/><code>POST /api/pipelines/ID/run</code> — обработка; передайте документ в поле формы <code>file</code>.</p></div>
    </div>
    <AlertDialog open={Boolean(secret)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>API-ключ создан</AlertDialogTitle><AlertDialogDescription>Скопируйте ключ сейчас. Повторно посмотреть его нельзя — можно только создать новый.</AlertDialogDescription></AlertDialogHeader>
      <Input aria-label="Новый API-ключ" value={secret} readOnly onFocus={(event) => event.target.select()}/>
      <Button variant="outline" onClick={async () => { try { await navigator.clipboard.writeText(secret); setCopied(true); } catch { setCopied(false); } }}><Copy size={16}/>{copied ? "Скопировано" : "Скопировать"}</Button>
      <small>Если копирование недоступно, выделите ключ в поле и скопируйте вручную.</small>
      <AlertDialogFooter><Button onClick={() => setSecret("")}>Я сохранил ключ</Button></AlertDialogFooter>
    </AlertDialogContent></AlertDialog>
    <AlertDialog open={Boolean(revoking)} onOpenChange={(open) => { if (!open && !busy) setRevoking(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Отозвать ключ?</AlertDialogTitle><AlertDialogDescription>Интеграция «{revoking?.name}» больше не сможет обращаться к API с этим ключом.</AlertDialogDescription></AlertDialogHeader>{error && <p role="alert">{error}</p>}<AlertDialogFooter><AlertDialogCancel disabled={busy}>Отмена</AlertDialogCancel><Button variant="destructive" disabled={busy} onClick={revoke}>Отозвать ключ</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </main>;
}
