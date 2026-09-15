export async function waitForJob(statusUrl, { signal, fetchImpl = fetch, interval = 1500, timeout = 600_000 } = {}) {
  const deadline = AbortSignal.timeout(timeout);
  const combined = signal ? AbortSignal.any([signal, deadline]) : deadline;
  try {
    for (;;) {
      combined.throwIfAborted();
      const response = await fetchImpl(statusUrl, { signal: combined, cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось получить статус обработки");
      if (data.status === "succeeded") return data;
      if (data.status === "failed") {
        const error = new Error(data.error || "Обработка не удалась");
        error.taskFailed = true;
        throw error;
      }
      if (!["queued", "processing"].includes(data.status)) throw new Error("Неизвестный статус обработки");
      await new Promise((resolve, reject) => {
        const abort = () => { clearTimeout(timer); reject(combined.reason); };
        const timer = setTimeout(() => { combined.removeEventListener("abort", abort); resolve(); }, interval);
        combined.addEventListener("abort", abort, { once: true });
        if (combined.aborted) abort();
      });
    }
  } catch (error) {
    if (deadline.aborted) throw new Error("Ожидание заняло больше 10 минут. Проверьте статус повторно: обработка продолжается на сервере.");
    throw error;
  }
}
