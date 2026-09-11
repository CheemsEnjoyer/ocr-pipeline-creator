"use client";

import { useEffect, useMemo, useState } from "react";
import { Copy, KeyRound, LogOut, Pencil, Plus, Search, ShieldOff } from "lucide-react";
import Header from "@/components/Header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePipelines } from "@/hooks/use-pipelines";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel } from "@/components/ui/alert-dialog";

const PAGE_SIZE = 20;
const STATUSES = [["active", "Активные"], ["revoked", "Отозванные"], ["all", "Все"]];
const SORTS = [["newest", "Сначала новые"], ["oldest", "Сначала старые"], ["name", "По названию"]];
const PIPELINE_FORMS = ["пайплайн", "пайплайна", "пайплайнов"];

const plural = (count, [one, few, many]) => {
  const tens = count % 100;
  const units = count % 10;
  if (units === 1 && tens !== 11) return one;
  return units >= 2 && units <= 4 && (tens < 10 || tens >= 20) ? few : many;
};
const day = (value) => new Date(value).toLocaleDateString("ru-RU", { day: "2-digit", month: "short", year: "numeric" });
const normalize = (value) => value.toLocaleLowerCase("ru-RU").trim();
const pipelineName = (pipeline) => pipeline.name || "Без названия";

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
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("active");
  const [sort, setSort] = useState("newest");
  const [page, setPage] = useState(0);
  // null — диалог закрыт, {} — новый ключ, объект ключа — изменение доступа.
  const [editing, setEditing] = useState(null);
  const [secret, setSecret] = useState("");
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState(null);
  const [revokeError, setRevokeError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api("/api/keys", "GET", undefined, controller.signal).then((data) => setKeys(data.keys))
      .catch((error) => { if (error.name !== "AbortError") setError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  const names = useMemo(() => new Map(pipelines.map((pipeline) => [pipeline.id, pipelineName(pipeline)])), [pipelines]);
  const counts = useMemo(() => {
    const revoked = keys.filter((key) => key.revoked_at).length;
    return { active: keys.length - revoked, revoked, all: keys.length };
  }, [keys]);
  const visible = useMemo(() => {
    const needle = normalize(query);
    const matches = keys.filter((key) => (status === "all" || (status === "active") === !key.revoked_at)
      && (!needle || [key.name, key.prefix, ...key.pipeline_ids.map((id) => names.get(id) ?? "")].some((text) => normalize(text).includes(needle))));
    const order = {
      newest: (a, b) => b.created_at.localeCompare(a.created_at),
      oldest: (a, b) => a.created_at.localeCompare(b.created_at),
      name: (a, b) => a.name.localeCompare(b.name, "ru"),
    }[sort];
    return matches.sort(order);
  }, [keys, query, status, sort, names]);
  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const rows = visible.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);
  const canCreate = ready && !pipelineError;

  const filter = (change) => { change(); setPage(0); };
  const saved = (key, token) => {
    setKeys((list) => list.some((item) => item.id === key.id) ? list.map((item) => item.id === key.id ? key : item) : [key, ...list]);
    setEditing(null);
    if (token) {
      // Новый ключ должен оказаться на виду, даже если сейчас включён другой фильтр.
      setQuery("");
      setStatus("active");
      setSort("newest");
      setPage(0);
      setSecret(token);
      setCopied(false);
    }
  };
  const revoke = async () => {
    setBusy(true);
    setRevokeError("");
    try {
      await api(`/api/keys/${revoking.id}`, "DELETE");
      setKeys((list) => list.map((key) => key.id === revoking.id ? { ...key, revoked_at: new Date().toISOString() } : key));
      setRevoking(null);
    } catch (error) { setRevokeError(error.message); }
    finally { setBusy(false); }
  };
  const logout = async () => {
    setBusy(true);
    try { await api("/api/auth/logout", "POST"); window.location.assign("/login"); }
    catch (error) { setError(error.message); setBusy(false); }
  };

  return <main className="app-shell"><Header subtitle="API-ключи"/>
    <div className="api-keys-page">
      <div className="pipelines-heading">
        <div><h1>Доступ к API</h1><p>Отдельный ключ для каждой интеграции — с доступом только к выбранным пайплайнам.</p></div>
        <div className="api-keys-heading-actions">
          <Button variant="outline" disabled={busy} onClick={logout}><LogOut size={16}/>Выйти</Button>
          <Button disabled={!canCreate} onClick={() => setEditing({})}><Plus size={16}/>Новый ключ</Button>
        </div>
      </div>
      {(error || pipelineError) && <p className="history-error" role="alert">{error || pipelineError}</p>}

      <section className="api-keys-panel" aria-label="API-ключи">
        <div className="api-keys-toolbar">
          <div className="api-keys-search">
            <Search size={16} aria-hidden="true"/>
            <Input type="search" aria-label="Поиск ключей" placeholder="Название, префикс или пайплайн" value={query} onChange={(event) => filter(() => setQuery(event.target.value))}/>
          </div>
          <div className="api-keys-status" role="group" aria-label="Статус ключей">
            {STATUSES.map(([value, label]) => <button key={value} type="button" aria-pressed={status === value} onClick={() => filter(() => setStatus(value))}>{label}<span>{counts[value]}</span></button>)}
          </div>
          <NativeSelect aria-label="Сортировка" value={sort} onChange={(event) => filter(() => setSort(event.target.value))}>
            {SORTS.map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}
          </NativeSelect>
        </div>

        {loading && <p className="history-loading" role="status">Загружаем ключи…</p>}
        {!loading && !keys.length && !error && <div className="history-empty">
          <KeyRound size={32}/><strong>API-ключей пока нет</strong>
          <p>Создайте ключ для первой интеграции и выберите пайплайны, которые ей доступны.</p>
          <Button disabled={!canCreate} onClick={() => setEditing({})}><Plus size={16}/>Новый ключ</Button>
        </div>}
        {!loading && keys.length > 0 && !visible.length && <div className="history-empty">
          <Search size={28}/><strong>Ничего не найдено</strong>
          <p>{query ? `По запросу «${query}» ключей нет.` : "С таким статусом ключей нет."}</p>
          <Button variant="outline" onClick={() => filter(() => { setQuery(""); setStatus("all"); })}>Сбросить фильтры</Button>
        </div>}

        {rows.length > 0 && <Table className="api-keys-table">
          <TableHeader><TableRow>
            <TableHead>Интеграция</TableHead><TableHead>Пайплайны</TableHead><TableHead>Создан</TableHead><TableHead>Статус</TableHead>
            <TableHead className="api-key-row-actions"><span className="sr-only">Действия</span></TableHead>
          </TableRow></TableHeader>
          <TableBody>{rows.map((key) => <KeyRow key={key.id} apiKey={key} names={names} busy={busy}
            onEdit={() => setEditing(key)} onRevoke={() => { setRevokeError(""); setRevoking(key); }}/>)}</TableBody>
        </Table>}

        {visible.length > PAGE_SIZE && <nav className="api-keys-pager" aria-label="Страницы ключей">
          <span>{current * PAGE_SIZE + 1}–{Math.min(visible.length, (current + 1) * PAGE_SIZE)} из {visible.length}</span>
          <Button variant="outline" size="sm" disabled={current === 0} onClick={() => setPage(current - 1)}>Назад</Button>
          <Button variant="outline" size="sm" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>Вперёд</Button>
        </nav>}
      </section>

      <details className="api-key-help">
        <summary>Как подключить интеграцию</summary>
        <p>Передавайте ключ в заголовке <code>Authorization: Bearer ВАШ_КЛЮЧ</code>.</p>
        <ul>
          <li><code>GET /api/pipelines</code> — пайплайны, доступные ключу;</li>
          <li><code>POST /api/pipelines/ID/run</code> — обработка документа из поля формы <code>file</code>.</li>
        </ul>
      </details>
    </div>

    {editing && <KeyDialog key={editing.id ?? "new"} apiKey={editing.id ? editing : null} pipelines={pipelines} onClose={() => setEditing(null)} onSaved={saved}/>}

    <AlertDialog open={Boolean(secret)}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>API-ключ создан</AlertDialogTitle><AlertDialogDescription>Скопируйте ключ сейчас. Повторно посмотреть его нельзя — можно только создать новый.</AlertDialogDescription></AlertDialogHeader>
      <Input aria-label="Новый API-ключ" value={secret} readOnly onFocus={(event) => event.target.select()}/>
      <Button variant="outline" onClick={async () => { try { await navigator.clipboard.writeText(secret); setCopied(true); } catch { setCopied(false); } }}><Copy size={16}/>{copied ? "Скопировано" : "Скопировать"}</Button>
      <small>Если копирование недоступно, выделите ключ в поле и скопируйте вручную.</small>
      <AlertDialogFooter><Button onClick={() => setSecret("")}>Я сохранил ключ</Button></AlertDialogFooter>
    </AlertDialogContent></AlertDialog>

    <AlertDialog open={Boolean(revoking)} onOpenChange={(open) => { if (!open && !busy) setRevoking(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Отозвать ключ?</AlertDialogTitle><AlertDialogDescription>Интеграция «{revoking?.name}» ({revoking?.prefix}…) больше не сможет обращаться к API с этим ключом.</AlertDialogDescription></AlertDialogHeader>{revokeError && <p className="history-error" role="alert">{revokeError}</p>}<AlertDialogFooter><AlertDialogCancel disabled={busy}>Отмена</AlertDialogCancel><Button variant="destructive" disabled={busy} onClick={revoke}>Отозвать ключ</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </main>;
}

function KeyRow({ apiKey, names, busy, onEdit, onRevoke }) {
  const known = apiKey.pipeline_ids.map((id) => names.get(id)).filter(Boolean);
  const missing = apiKey.pipeline_ids.length - known.length;
  const preview = [known.slice(0, 2).join(", ") + (known.length > 2 ? ` и ещё ${known.length - 2}` : ""), missing ? `удалено: ${missing}` : ""].filter(Boolean).join(" · ");
  const count = apiKey.pipeline_ids.length;
  return <TableRow className={apiKey.revoked_at ? "revoked" : undefined}>
    <TableCell data-label="Интеграция"><div className="api-key-name"><strong title={apiKey.name}>{apiKey.name}</strong><code>{apiKey.prefix}…</code></div></TableCell>
    <TableCell data-label="Пайплайны"><div className="api-key-pipelines" title={[...known, ...(missing ? [`удалено: ${missing}`] : [])].join("\n")}>
      <span>{count} {plural(count, PIPELINE_FORMS)}</span><small>{preview}</small>
    </div></TableCell>
    <TableCell data-label="Создан">{day(apiKey.created_at)}</TableCell>
    <TableCell data-label="Статус" className="api-key-status">{apiKey.revoked_at
      ? <><Badge variant="outline">Отозван</Badge><small>{day(apiKey.revoked_at)}</small></>
      : <Badge variant="secondary">Активен</Badge>}</TableCell>
    <TableCell className="api-key-row-actions">{!apiKey.revoked_at && <>
      <Button variant="ghost" size="icon" disabled={busy} title="Изменить доступ" aria-label={`Изменить доступ ключа «${apiKey.name}»`} onClick={onEdit}><Pencil size={16}/></Button>
      <Button variant="ghost" size="icon" className="api-key-revoke" disabled={busy} title="Отозвать" aria-label={`Отозвать ключ «${apiKey.name}»`} onClick={onRevoke}><ShieldOff size={16}/></Button>
    </>}</TableCell>
  </TableRow>;
}

function KeyDialog({ apiKey, pipelines, onClose, onSaved }) {
  const available = useMemo(() => new Set(pipelines.map((pipeline) => pipeline.id)), [pipelines]);
  const [name, setName] = useState(apiKey?.name ?? "");
  const [ids, setIds] = useState(() => (apiKey?.pipeline_ids ?? []).filter((id) => available.has(id)));
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const missing = (apiKey?.pipeline_ids ?? []).filter((id) => !available.has(id)).length;
  const needle = normalize(search);
  const shown = needle ? pipelines.filter((pipeline) => normalize(pipelineName(pipeline)).includes(needle)) : pipelines;
  const selected = new Set(ids);

  const toggle = (id, checked) => setIds((current) => checked ? [...new Set([...current, id])] : current.filter((item) => item !== id));
  const selectShown = () => setIds((current) => [...new Set([...current, ...shown.map((pipeline) => pipeline.id)])]);
  const clearShown = () => setIds((current) => needle ? current.filter((id) => !shown.some((pipeline) => pipeline.id === id)) : []);
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await api(apiKey ? `/api/keys/${apiKey.id}` : "/api/keys", apiKey ? "PATCH" : "POST", { name: name.trim(), pipeline_ids: ids });
      onSaved(data.key, data.token);
    } catch (error) { setError(error.message); setBusy(false); }
  };

  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
    <DialogContent className="api-key-dialog sm:max-w-[560px]">
      <form className="api-key-dialog-form" onSubmit={submit}>
        <DialogHeader>
          <DialogTitle>{apiKey ? "Доступ ключа" : "Новый API-ключ"}</DialogTitle>
          <DialogDescription>{apiKey ? `Ключ ${apiKey.prefix}… останется прежним — меняются только название и пайплайны.` : "Ключ покажем один раз сразу после создания."}</DialogDescription>
        </DialogHeader>
        <div className="api-key-field">
          <Label htmlFor="key-name">Название интеграции</Label>
          <Input id="key-name" placeholder="Например, 1С: Бухгалтерия" value={name} maxLength={120} disabled={busy} required autoFocus onChange={(event) => setName(event.target.value)}/>
        </div>
        <fieldset className="api-key-field" disabled={busy}>
          <legend>Доступные пайплайны<span>Выбрано {ids.length} из {pipelines.length}</span></legend>
          {pipelines.length > 6 && <Input type="search" aria-label="Поиск пайплайнов" placeholder="Найти пайплайн" value={search} onChange={(event) => setSearch(event.target.value)}/>}
          {pipelines.length > 0 && <div className="api-key-select-actions">
            <button type="button" disabled={!shown.length} onClick={selectShown}>{needle ? "Выбрать найденные" : "Выбрать все"}</button>
            <button type="button" disabled={!ids.length} onClick={clearShown}>{needle ? "Снять найденные" : "Снять все"}</button>
          </div>}
          <div className="key-pipeline-list">
            {shown.map((pipeline) => <label key={pipeline.id}>
              <Checkbox checked={selected.has(pipeline.id)} onCheckedChange={(checked) => toggle(pipeline.id, checked === true)}/>
              <span>{pipelineName(pipeline)}</span>
            </label>)}
            {!pipelines.length && <p>Сначала создайте пайплайн в конструкторе.</p>}
            {pipelines.length > 0 && !shown.length && <p>Пайплайнов с таким названием нет.</p>}
          </div>
          {missing > 0 && <small>Удалённые пайплайны ({missing}) будут убраны из ключа при сохранении.</small>}
        </fieldset>
        {error && <p className="history-error" role="alert">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={busy} onClick={onClose}>Отмена</Button>
          <Button type="submit" disabled={busy || !name.trim() || !ids.length}>{busy ? "Сохраняем…" : apiKey ? "Сохранить доступ" : "Создать ключ"}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
