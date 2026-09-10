"use client";

import Link from "next/link";
import { useState } from "react";
import { usePathname } from "next/navigation";
import { History, ScanText, Workflow, Plus, Trash2, Pencil } from "lucide-react";
import { usePipelines } from "@/hooks/use-pipelines";
import { deletePipeline } from "@/lib/pipelines";
import { Button } from "@/components/ui/button";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel } from "@/components/ui/alert-dialog";
import { Sidebar, SidebarContent, SidebarHeader, SidebarMenu, SidebarMenuItem, SidebarMenuButton, SidebarProvider, useSidebar } from "@/components/ui/sidebar";

const links = [
  { href: "/", label: "Конструктор", icon: Workflow },
  { href: "/process", label: "Обработка", icon: ScanText },
  { href: "/history", label: "История документов", icon: History },
];

function Navigation() {
  const pathname = usePathname();
  const { setOpenMobile } = useSidebar();
  const { pipelines, ready } = usePipelines();
  const [removing, setRemoving] = useState(null);
  const [error, setError] = useState("");
  return <Sidebar className="app-navigation">
    <SidebarHeader className="navigation-brand"><img src="/assets/enplus-logo.svg" alt="Эн+"/><span>OCR Flow Studio</span></SidebarHeader>
    <SidebarContent className="navigation-content">
      <p className="navigation-caption">РАБОЧЕЕ ПРОСТРАНСТВО</p>
      <nav aria-label="Основная навигация"><SidebarMenu>{links.map(({ href, label, icon: Icon }) => <SidebarMenuItem key={href}>
        <SidebarMenuButton asChild isActive={pathname === href} className="navigation-link"><Link href={href} aria-current={pathname === href ? "page" : undefined} onClick={() => setOpenMobile(false)}><Icon size={19}/><span>{label}</span></Link></SidebarMenuButton>
      </SidebarMenuItem>)}</SidebarMenu></nav>
      <section className="sidebar-pipelines" aria-label="Сохранённые пайплайны">
        <div className="sidebar-pipelines-heading"><span>ПАЙПЛАЙНЫ</span><Button variant="ghost" size="icon" asChild><Link href="/" aria-label="Создать пайплайн" onClick={() => setOpenMobile(false)}><Plus size={17}/></Link></Button></div>
        {ready && !pipelines.length && <p className="sidebar-pipelines-empty">Сохранённые пайплайны появятся здесь.</p>}
        {!ready && <p className="sidebar-pipelines-empty">Загружаем…</p>}
        {pipelines.map((pipeline) => <div className={`sidebar-pipeline ${pathname === `/pipelines/${pipeline.id}` ? "active" : ""}`} key={pipeline.id}>
          <Link href={`/pipelines/${encodeURIComponent(pipeline.id)}`} onClick={() => setOpenMobile(false)} aria-current={pathname === `/pipelines/${pipeline.id}` ? "page" : undefined} title={`Редактировать: ${pipeline.name}`}><Pencil size={15}/><span>{pipeline.name || "Без названия"}</span></Link>
          <button aria-label={`Удалить пайплайн «${pipeline.name}»`} onClick={() => { setError(""); setRemoving(pipeline); }}><Trash2 size={15}/></button>
        </div>)}
      </section>
      <AlertDialog open={Boolean(removing)} onOpenChange={(open) => { if (!open) setRemoving(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Удалить пайплайн?</AlertDialogTitle><AlertDialogDescription>«{removing?.name}» будет удалён из списка. Обработанные документы и их история сохранятся.</AlertDialogDescription></AlertDialogHeader>{error && <p className="history-error" role="alert">{error}</p>}<AlertDialogFooter><AlertDialogCancel>Отмена</AlertDialogCancel><Button variant="destructive" onClick={() => { try { deletePipeline(removing.id); setRemoving(null); } catch (error) { setError(error.message); } }}>Удалить</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
    </SidebarContent>
  </Sidebar>;
}

export default function AppNavigation({ children }) {
  return <SidebarProvider style={{ "--sidebar-width": "230px" }}><Navigation/><div className="workspace-content">{children}</div></SidebarProvider>;
}
