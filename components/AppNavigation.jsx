"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { History, KeyRound, Layers, ScanText, Workflow, ChevronUp, Settings, LogOut, Users, ShieldCheck } from "lucide-react";
import { Sidebar, SidebarContent, SidebarHeader, SidebarFooter, SidebarMenu, SidebarMenuItem, SidebarMenuButton, SidebarProvider, useSidebar } from "@/components/ui/sidebar";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuLabel } from "@/components/ui/dropdown-menu";
import { useSession } from "@/hooks/use-session";

const links = [
  { href: "/", label: "Обработка", icon: ScanText, match: (pathname) => pathname === "/" || pathname === "/process" },
  { href: "/createpipeline", label: "Конструктор", icon: Workflow, match: (pathname) => pathname === "/createpipeline" },
  { href: "/pipelines", label: "Пайплайны", icon: Layers, match: (pathname) => pathname === "/pipelines" || pathname.startsWith("/pipelines/") },
  { href: "/history", label: "История документов", icon: History, match: (pathname) => pathname === "/history" },
  { href: "/api-keys", label: "API-ключи", icon: KeyRound, match: (pathname) => pathname === "/api-keys" },
];

function Navigation() {
  const pathname = usePathname();
  const { setOpenMobile } = useSidebar();
  const user = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const logout = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(user?.provider === "keycloak" ? "/api/auth/keycloak/logout" : "/api/auth/logout", { method: "POST" });
      if (!response.ok && response.status !== 401) throw new Error("Не удалось выйти. Повторите попытку.");
      const data = response.ok ? await response.json() : {};
      window.location.assign(data.logoutUrl || "/login");
    } catch (error) { setError(error.message); setBusy(false); }
  };
  const displayName = user?.name || user?.login || "Пользователь";
  const initials = displayName.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  return <Sidebar className="app-navigation">
    <SidebarHeader className="navigation-brand"><img src="/assets/enplus-logo.svg" alt="Эн+" width={77} height={34}/><span>OCR Pipeline Creator</span></SidebarHeader>
    <SidebarContent className="navigation-content">
      <p className="navigation-caption">РАБОЧЕЕ ПРОСТРАНСТВО</p>
      <nav aria-label="Основная навигация"><SidebarMenu>{links.filter((item) => user?.role === "admin" || !["/createpipeline", "/api-keys"].includes(item.href)).map(({ href, label, icon: Icon, match }) => {
        const active = match(pathname);
        return <SidebarMenuItem key={href}>
          <SidebarMenuButton asChild isActive={active} className="navigation-link"><a href={href} aria-current={active ? "page" : undefined} onClick={() => setOpenMobile(false)}><Icon size={19}/><span>{label}</span></a></SidebarMenuButton>
        </SidebarMenuItem>;
      })}</SidebarMenu></nav>
    </SidebarContent>
    <SidebarFooter className="account-footer">
      <DropdownMenu><DropdownMenuTrigger asChild><button className="account-trigger" aria-label="Открыть меню пользователя" disabled={busy}><span className="account-avatar">{initials}</span><span className="account-info"><strong>{displayName}</strong><small>{user?.role === "admin" ? "Администратор" : "Пользователь"}</small></span><ChevronUp size={16}/></button></DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" sideOffset={10} className="account-menu"><DropdownMenuLabel className="account-menu-heading"><span className="account-avatar">{initials}</span><div><strong>{displayName}</strong><small>{user?.login}</small></div>{user?.role === "admin" && <ShieldCheck size={17}/>}</DropdownMenuLabel><DropdownMenuSeparator/>
          <DropdownMenuItem><Settings size={17}/>Настройки</DropdownMenuItem>
          {user?.role === "admin" && <DropdownMenuItem onSelect={() => { setOpenMobile(false); window.location.assign("/users"); }}><Users size={17}/>Пользователи</DropdownMenuItem>}
          <DropdownMenuSeparator/><DropdownMenuItem variant="destructive" onSelect={logout} disabled={busy}><LogOut size={17}/>{busy ? "Выходим…" : "Выйти"}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {error && <p className="history-error" role="alert">{error}</p>}
    </SidebarFooter>
  </Sidebar>;
}

export default function AppNavigation({ children }) {
  const pathname = usePathname();
  if (pathname === "/login" || pathname === "/invite") return children;
  return <SidebarProvider style={{ "--sidebar-width": "230px" }}><Navigation/><div className="workspace-content">{children}</div></SidebarProvider>;
}
