// Каталог внешних OCR-сервисов приходит из бэкенда: адрес задаётся в .env (OCR_SERVICE_URL),
// а options уходят в multipart-запрос вместе с файлом.
export async function loadOcrServices(signal) {
  const response = await fetch("/api/ocr/services", { signal });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Не удалось получить список OCR-сервисов");
  return Array.isArray(data.services) ? data.services : [];
}

export function findOcrService(services, url) {
  return services.find((service) => service.url === url) ?? null;
}
