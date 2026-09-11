import "./globals.css";
import AuthGate from "@/components/AuthGate";
import AppNavigation from "@/components/AppNavigation";
export const metadata = {
    title: "OCR Flow Studio — конструктор пайплайнов",
    description: "Визуальная настройка распознавания и извлечения данных из документов.",
    icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};
export default function RootLayout({ children }) {
    return <html lang="ru"><body><AuthGate><AppNavigation>{children}</AppNavigation></AuthGate></body></html>;
}
