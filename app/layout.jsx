import "./globals.css";
import AppNavigation from "@/components/AppNavigation";
export const metadata = {
    title: "OCR Flow Studio — конструктор пайплайнов",
    description: "Визуальная настройка распознавания и извлечения данных из документов.",
    icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};
export default function RootLayout({ children }) {
    return <html lang="ru"><body><AppNavigation>{children}</AppNavigation></body></html>;
}
