"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const login = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось войти");
      window.location.assign("/");
    } catch (error) { setError(error.message); setBusy(false); }
  };
  return <main className="login-page"><form className="login-card" onSubmit={login}>
    <h1>Вход в OCR Flow Studio</h1>
    <p>Введите ключ администратора для управления документами, пайплайнами и доступом к API.</p>
    <Label htmlFor="admin-key">Ключ администратора</Label>
    <Input id="admin-key" type="password" autoComplete="current-password" value={key} onChange={(event) => setKey(event.target.value)} required disabled={busy}/>
    <small>Ключ задаётся в OCR_ADMIN_KEY. При первом запуске без этой настройки сервер создаёт файл data/admin-api-key.txt.</small>
    {error && <p className="history-error" role="alert">{error}</p>}
    <Button type="submit" disabled={busy || !key.trim()}>{busy ? "Входим…" : "Войти"}</Button>
  </form></main>;
}
