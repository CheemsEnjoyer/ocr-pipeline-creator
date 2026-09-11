"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { History, KeyRound, Layers, ScanText, Workflow } from "lucide-react";
import { Sidebar, SidebarContent, SidebarHeader, SidebarMenu, SidebarMenuItem, SidebarMenuButton, SidebarProvider, useSidebar } from "@/components/ui/sidebar";

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
  return <Sidebar className="app-navigation">
    <SidebarHeader className="navigation-brand"><img src="/assets/enplus-logo.svg" alt="Эн+"/><span>OCR Flow Studio</span></SidebarHeader>
    <SidebarContent className="navigation-content">
      <p className="navigation-caption">РАБОЧЕЕ ПРОСТРАНСТВО</p>
      <nav aria-label="Основная навигация"><SidebarMenu>{links.map(({ href, label, icon: Icon, match }) => {
        const active = match(pathname);
        return <SidebarMenuItem key={href}>
          <SidebarMenuButton asChild isActive={active} className="navigation-link"><Link href={href} aria-current={active ? "page" : undefined} onClick={() => setOpenMobile(false)}><Icon size={19}/><span>{label}</span></Link></SidebarMenuButton>
        </SidebarMenuItem>;
      })}</SidebarMenu></nav>
    </SidebarContent>
  </Sidebar>;
}

export default function AppNavigation({ children }) {
  const pathname = usePathname();
  if (pathname === "/login") return children;
  return <SidebarProvider style={{ "--sidebar-width": "230px" }}><Navigation/><div className="workspace-content">{children}</div></SidebarProvider>;
}
