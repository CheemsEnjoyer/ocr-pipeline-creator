import "./globals.css";
import AuthGate from "@/components/AuthGate";
import AppNavigation from "@/components/AppNavigation";
export const metadata = {
    title: "OCR Pipeline Creator — конструктор пайплайнов",
    description: "Визуальная настройка распознавания и извлечения данных из документов.",
    icons: { icon: "/ocr_pipeline_creator_logo.svg", shortcut: "/ocr_pipeline_creator_logo.svg" },
};
export default function RootLayout({ children }) {
    return <html lang="ru"><body><AuthGate><AppNavigation>{children}</AppNavigation></AuthGate></body></html>;
}
