"use client";
import { useState } from "react";
import Link from "next/link";
import { UserRoundPlus, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function InvitePage() {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [login, setLogin] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    if (password !== confirmation) { setError("Пароли не совпадают"); return; }
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (!token) { setError("Откройте полную ссылку приглашения от администратора"); return; }
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/auth/invitations/accept", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({token, password}) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось принять приглашение");
      window.history.replaceState(null, "", "/invite");
      setLogin(data.login);
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  };
  return <main className="login-page">{login ? <div className="login-card"><Check size={32}/><h1>Добро пожаловать</h1><p>Учётная запись активирована. Ваш логин: <strong>{login}</strong>.</p><Button asChild><Link href="/login">Перейти ко входу</Link></Button></div> : <form className="login-card" onSubmit={submit}><UserRoundPlus size={32}/><h1>Присоединиться к команде</h1><p>Задайте пароль для своей учётной записи.</p><Label htmlFor="invite-password">Пароль</Label><Input id="invite-password" type="password" autoComplete="new-password" minLength={8} maxLength={512} required disabled={busy} value={password} onChange={(event) => setPassword(event.target.value)}/><Label htmlFor="invite-confirm">Повторите пароль</Label><Input id="invite-confirm" type="password" autoComplete="new-password" required disabled={busy} value={confirmation} onChange={(event) => setConfirmation(event.target.value)}/><small>Не менее 8 символов. Ссылка действует 72 часа и используется один раз.</small>{error && <p className="history-error" role="alert">{error}</p>}<Button disabled={busy}>{busy ? "Создаём учётную запись…" : "Принять приглашение"}</Button><Link href="/login">Уже есть учётная запись? Войти</Link></form>}</main>;
}
