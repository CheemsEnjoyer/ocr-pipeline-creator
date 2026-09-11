"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ login: login.trim(), password }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось войти");
      window.location.assign("/");
    } catch (error) { setError(error.message); setBusy(false); }
  };
  return <main className="login-page"><form className="login-card" onSubmit={submit}>
    <h1>Вход в OCR Flow Studio</h1>
    <p>Войдите как администратор, чтобы управлять документами, пайплайнами и доступом к API.</p>
    <Label htmlFor="admin-login">Логин</Label>
    <Input id="admin-login" autoComplete="username" value={login} onChange={(event) => setLogin(event.target.value)} required disabled={busy}/>
    <Label htmlFor="admin-password">Пароль</Label>
    <Input id="admin-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required disabled={busy}/>
    <small>Логин и пароль задаются в OCR_ADMIN_LOGIN и OCR_ADMIN_PASSWORD. Без этих настроек логин — admin, а пароль сервер создаёт при первом запуске в data/admin-password.txt.</small>
    {error && <p className="history-error" role="alert">{error}</p>}
    <Button type="submit" disabled={busy || !login.trim() || !password}>{busy ? "Входим…" : "Войти"}</Button>
  </form></main>;
}
