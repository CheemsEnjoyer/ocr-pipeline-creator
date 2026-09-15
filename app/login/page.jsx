"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [auth, setAuth] = useState(null);
  useEffect(() => {
    let active = true;
    fetch("/api/auth/config").then(async (response) => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось загрузить настройки входа");
      if (active) setAuth(data);
    }).catch((error) => { if (active) setError(error.message); });
    return () => { active = false; };
  }, []);
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
    <h1>Вход в OCR Pipeline Creator</h1>
    <p>Войдите в рабочее пространство для обработки документов.</p>
    {auth?.provider === "keycloak" ? <><small>Используйте корпоративную учётную запись.</small><Button type="button" onClick={() => window.location.assign(auth.loginUrl)}>Войти через Keycloak</Button></> : auth ? <>
    <Label htmlFor="admin-login">Логин</Label>
    <Input id="admin-login" autoComplete="username" value={login} onChange={(event) => setLogin(event.target.value)} required disabled={busy}/>
    <Label htmlFor="admin-password">Пароль</Label>
    <Input id="admin-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required disabled={busy}/>
    <small>Используйте свою учётную запись. Для получения доступа обратитесь к администратору.</small>
    {error && <p className="history-error" role="alert">{error}</p>}
    <Button type="submit" disabled={busy || !login.trim() || !password}>{busy ? "Входим…" : "Войти"}</Button>
    </> : <p role="status">{error || "Загружаем настройки входа…"}</p>}
  </form></main>;
}
