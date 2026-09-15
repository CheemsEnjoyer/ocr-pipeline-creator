"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { SessionContext } from "@/hooks/use-session";

export default function AuthGate({ children }) {
  const pathname = usePathname();
  const [status, setStatus] = useState("loading");
  const [user, setUser] = useState(null);
  useEffect(() => {
    if (pathname === "/login" || pathname === "/invite") return;
    const controller = new AbortController();
    const check = async () => {
      try {
        const response = await fetch("/api/auth/session", { signal: controller.signal });
        if (response.status === 401 || response.status === 403) {
          window.location.replace("/login");
        } else {
          if (response.ok) {
            const session = await response.json();
            setUser(session);
            if (session.role !== "admin" && (pathname === "/users" || pathname === "/api-keys" || pathname === "/createpipeline" || pathname.startsWith("/pipelines/"))) {
              window.location.replace("/");
              return;
            }
          }
          setStatus(response.ok ? "ready" : "error");
        }
      } catch (error) {
        if (error.name !== "AbortError") setStatus("error");
      }
    };
    void check();
    window.addEventListener("focus", check);
    return () => { controller.abort(); window.removeEventListener("focus", check); };
  }, [pathname]);
  if (pathname === "/login" || pathname === "/invite") return children;
  if (status === "ready") return <SessionContext.Provider value={user}>{children}</SessionContext.Provider>;
  return <main className="login-page"><div className="login-card">{status === "loading"
    ? <p role="status">Проверяем доступ…</p>
    : <><p role="alert">Не удалось подключиться к серверу.</p><Button onClick={() => window.location.reload()}>Повторить</Button></>}</div></main>;
}
