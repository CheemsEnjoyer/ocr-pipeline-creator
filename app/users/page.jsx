"use client";
import { useEffect, useState } from "react";
import { Users, UserRoundPlus, ShieldCheck, Trash2, Copy, Check, LoaderCircle } from "lucide-react";
import Header from "@/components/Header";
import { useSession } from "@/hooks/use-session";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel } from "@/components/ui/alert-dialog";

async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, ...(body ? {headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Не удалось выполнить действие");
  return data;
}

export default function UsersPage() {
  const current = useSession();
  const external = current?.provider === "keycloak";
  const management = !external || current?.users_management;
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [name, setName] = useState("");
  const [login, setLogin] = useState("");
  const [role, setRole] = useState("user");
  const [link, setLink] = useState("");
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [removing, setRemoving] = useState(null);
  useEffect(() => {
    if (current?.role !== "admin" || !management) return;
    let active = true;
    api("/api/users").then((data) => { if (active) setUsers(data.users); }).catch((error) => { if (active) setError(error.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refresh, current?.role, management]);
  const invite = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setActionError("");
    try {
      const data = await api("/api/users/invite", "POST", {name:name.trim(), login:login.trim(), role, ...(external ? {email:email.trim()} : {})});
      setUsers((current) => [...current, data.user]);
      if (data.invitePath) setLink(new URL(data.invitePath, window.location.origin).href);
      setSent(Boolean(data.emailSent));
    } catch (error) { setActionError(error.message); }
    finally { setBusy(false); }
  };
  const changeRole = async (user, role) => {
    setBusy(true); setError("");
    try {
      const data = await api(`/api/users/${user.id}`, "PATCH", {role});
      setUsers((users) => users.map((item) => item.id === user.id ? data.user : item));
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true); setActionError("");
    try {
      await api(`/api/users/${removing.id}`, "DELETE");
      setUsers((users) => users.filter((user) => user.id !== removing.id));
      setRemoving(null);
    } catch (error) { setActionError(error.message); }
    finally { setBusy(false); }
  };
  if (current?.role !== "admin") return <main className="app-shell"><Header subtitle="Пользователи"/><p className="history-error">Раздел доступен только администратору.</p></main>;
  return <main className="app-shell"><Header subtitle="Пользователи"/><section className="users-page"><div className="users-heading"><div><p className="eyebrow">УПРАВЛЕНИЕ ДОСТУПОМ</p><h1>Команда сервиса</h1><p>Приглашайте коллег и назначайте роли в рабочем пространстве.</p></div><Button onClick={() => {setInviteOpen(true); setName(""); setLogin(""); setEmail(""); setSent(false); setRole("user"); setLink(""); setCopied(false); setActionError("");}} disabled={busy || !management}><UserRoundPlus size={17}/>Пригласить пользователя</Button></div>
    <div className="users-role-guide"><ShieldCheck size={20}/><div><strong>Две роли — понятный доступ</strong><p>Администратор управляет пайплайнами, пользователями и API-ключами. Пользователь обрабатывает документы и работает с общей историей.</p></div></div>
    {!management && <p className="history-error">Для управления пользователями настройте сервисный клиент Keycloak. Вход и обработка документов уже доступны.</p>}
    {error && <div className="history-error" role="alert">{error}<Button variant="outline" size="sm" disabled={busy} onClick={() => {setError(""); setLoading(true); setRefresh((value) => value + 1);}}>Повторить</Button></div>}
    {loading && management ? <p className="history-loading" role="status"><LoaderCircle className="spin" size={18}/>Загружаем пользователей…</p> : <div className="users-table-wrap"><table className="users-table"><thead><tr><th>Пользователь</th><th>Статус</th><th>Роль</th><th><span className="sr-only">Действия</span></th></tr></thead><tbody>{users.map((user) => <tr key={user.id}><td><div className="user-cell"><span className="account-avatar">{user.name.slice(0,2).toUpperCase()}</span><div><strong>{user.name}{user.id === current.id && <small className="user-you">Вы</small>}</strong><small>{user.login}</small></div></div></td><td><span className={`user-status ${user.status}`}>{user.status === "active" ? "Активен" : "Приглашён"}</span></td><td><Select value={user.role} onValueChange={(role) => changeRole(user, role)} disabled={busy || user.is_bootstrap || user.id === current.id}><SelectTrigger aria-label={`Роль пользователя ${user.name}`}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="admin">Администратор</SelectItem><SelectItem value="user">Пользователь</SelectItem></SelectContent></Select>{user.is_bootstrap && <small className="user-protected">{external ? "Доступ наследуется в Keycloak" : "Основной администратор"}</small>}</td><td><Button variant="ghost" size="icon" aria-label={`Удалить пользователя ${user.name}`} disabled={busy || user.is_bootstrap || user.id === current.id} onClick={() => {setRemoving(user); setActionError("");}}><Trash2 size={17}/></Button></td></tr>)}</tbody></table>{!users.length && <div className="history-empty"><Users size={30}/><p>Пользователей пока нет.</p></div>}</div>}
  </section>
  <Dialog open={inviteOpen} onOpenChange={(open) => {if (!busy) setInviteOpen(open);}}><DialogContent><DialogHeader><DialogTitle>{sent ? "Приглашение отправлено" : link ? "Приглашение готово" : "Пригласить пользователя"}</DialogTitle><DialogDescription>{sent ? "Keycloak отправил письмо пользователю. Ссылка действует 72 часа." : link ? "Передайте ссылку коллеге. Она действует 72 часа и используется один раз. Письмо автоматически не отправляется." : external ? "Укажите имя, логин, email и роль. Keycloak отправит письмо для получения доступа." : "Укажите имя, логин для входа и роль. Пользователь задаст пароль самостоятельно."}</DialogDescription></DialogHeader>{sent ? <Button onClick={() => setInviteOpen(false)}>Готово</Button> : link ? <div className="invite-result"><Label htmlFor="invite-link">Ссылка приглашения</Label><Input id="invite-link" value={link} readOnly onFocus={(event) => event.target.select()}/><Button variant="outline" onClick={async () => {try {await navigator.clipboard.writeText(link); setCopied(true);} catch {setActionError("Не удалось скопировать. Выделите и скопируйте ссылку вручную.");}}}>{copied ? <Check size={16}/> : <Copy size={16}/>}{copied ? "Скопировано" : "Скопировать ссылку"}</Button><Button onClick={() => setInviteOpen(false)}>Готово</Button></div> : <form className="invite-form" onSubmit={invite}><Label htmlFor="user-name">Имя</Label><Input id="user-name" required maxLength={120} value={name} disabled={busy} onChange={(event) => setName(event.target.value)}/><Label htmlFor="user-login">Логин</Label><Input id="user-login" required maxLength={120} autoComplete="off" value={login} disabled={busy} onChange={(event) => setLogin(event.target.value)}/>{external && <><Label htmlFor="user-email">Email</Label><Input id="user-email" type="email" required maxLength={254} value={email} disabled={busy} onChange={(event) => setEmail(event.target.value)}/></>}<Label>Роль</Label><Select value={role} onValueChange={setRole} disabled={busy}><SelectTrigger aria-label="Роль приглашённого пользователя"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="user">Пользователь</SelectItem><SelectItem value="admin">Администратор</SelectItem></SelectContent></Select><DialogFooter><Button type="button" variant="outline" disabled={busy} onClick={() => setInviteOpen(false)}>Отмена</Button><Button disabled={busy || !name.trim() || !login.trim() || (external && !email.trim())}>{busy ? "Создаём…" : "Создать приглашение"}</Button></DialogFooter></form>}{actionError && <p className="history-error" role="alert">{actionError}</p>}</DialogContent></Dialog>
  <AlertDialog open={Boolean(removing)} onOpenChange={(open) => {if (!open && !busy) setRemoving(null);}}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Удалить пользователя?</AlertDialogTitle><AlertDialogDescription>«{removing?.name}» потеряет доступ к сервису. Открытые сессии и приглашение будут отозваны. История документов сохранится. {external && "Общая учётная запись в Keycloak останется доступна другим приложениям."}</AlertDialogDescription></AlertDialogHeader>{actionError && <p className="history-error" role="alert">{actionError}</p>}<AlertDialogFooter><AlertDialogCancel disabled={busy}>Отмена</AlertDialogCancel><Button variant="destructive" disabled={busy} onClick={remove}>{busy ? "Удаляем…" : "Удалить пользователя"}</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </main>;
}
