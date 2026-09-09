"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";

const links = [
  { href: "/", label: "Конструктор" },
  { href: "/process", label: "Обработка" },
];

export default function Header({ subtitle, action }) {
  const pathname = usePathname();

  return <header className="topbar">
    <div className="brand">
      <img className="brand-logo" src="/assets/enplus-logo.svg" alt="Эн+"/>
      <div><strong>Конструктор OCR пайплайнов</strong><span>{subtitle}</span></div>
    </div>
    <nav className="topbar-nav">
      {links.map((link) => <Link key={link.href} href={link.href} className={pathname === link.href ? "active" : undefined}>{link.label}</Link>)}
    </nav>
    <Button variant="outline" size="sm" asChild><Link href={action.href}>{action.label}</Link></Button>
  </header>;
}
