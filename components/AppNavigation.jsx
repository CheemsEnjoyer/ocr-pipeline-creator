"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { History, ScanText, Workflow } from "lucide-react";
import { Sidebar, SidebarContent, SidebarHeader, SidebarMenu, SidebarMenuItem, SidebarMenuButton, SidebarProvider, useSidebar } from "@/components/ui/sidebar";

const links = [
  { href: "/", label: "Конструктор", icon: Workflow },
  { href: "/process", label: "Обработка", icon: ScanText },
  { href: "/history", label: "История документов", icon: History },
];

function Navigation() {
  const pathname = usePathname();
  const { setOpenMobile } = useSidebar();
  return <Sidebar className="app-navigation">
    <SidebarHeader className="navigation-brand"><img src="/assets/enplus-logo.svg" alt="Эн+"/><span>OCR Flow Studio</span></SidebarHeader>
    <SidebarContent className="navigation-content">
      <p className="navigation-caption">РАБОЧЕЕ ПРОСТРАНСТВО</p>
      <nav aria-label="Основная навигация"><SidebarMenu>{links.map(({ href, label, icon: Icon }) => <SidebarMenuItem key={href}>
        <SidebarMenuButton asChild isActive={pathname === href} className="navigation-link"><Link href={href} aria-current={pathname === href ? "page" : undefined} onClick={() => setOpenMobile(false)}><Icon size={19}/><span>{label}</span></Link></SidebarMenuButton>
      </SidebarMenuItem>)}</SidebarMenu></nav>
    </SidebarContent>
  </Sidebar>;
}

export default function AppNavigation({ children }) {
  return <SidebarProvider style={{ "--sidebar-width": "230px" }}><Navigation/><div className="workspace-content">{children}</div></SidebarProvider>;
}
