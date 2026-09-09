import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OCR Flow Studio — конструктор пайплайнов",
  description: "Визуальная настройка распознавания и извлечения данных из документов.",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ru"><body>{children}</body></html>;
}
