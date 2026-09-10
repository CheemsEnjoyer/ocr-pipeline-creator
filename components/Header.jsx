"use client";

import { SidebarTrigger } from "@/components/ui/sidebar";

export default function Header({ subtitle }) {
  return <header className="topbar">
    <div className="brand">
      <SidebarTrigger aria-label="Открыть или свернуть меню"/>
      <strong>{subtitle}</strong>
    </div>
  </header>;
}
