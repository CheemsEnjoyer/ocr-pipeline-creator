import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const MAX_BODY = 21 * 1024 * 1024;

export function createSimulator({ target = "http://127.0.0.1:8000", fetchImpl = fetch } = {}) {
  const upstream = new URL(target);
  if (!["http:", "https:"].includes(upstream.protocol) || upstream.username || upstream.password) {
    throw new Error("SIMULATOR_API_URL должен быть HTTP(S)-адресом без логина и пароля");
  }
  return createServer(async (req, res) => {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    const fail = (status, detail) => {
      res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ detail }));
    };
    try {
      const url = new URL(req.url, "http://localhost");
      if (req.method === "GET" && url.pathname === "/") {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'" });
        res.end(await readFile(new URL("../simulator/index.html", import.meta.url)));
        return;
      }
      const allowed = req.method === "GET"
        ? /^\/api\/v1\/(pipelines|documents(?:\/[\w-]+)?)$/.test(url.pathname)
        : req.method === "POST" && /^\/api\/v1\/pipelines\/[\w-]+\/run$/.test(url.pathname);
      if (!allowed) return fail(404, "Маршрут не найден");
      // Reject cross-origin browser requests; credentials are never stored by this service.
      if (req.headers["sec-fetch-site"] === "cross-site" || (req.headers.origin && req.headers.origin !== `http://${req.headers.host}`)) {
        return fail(403, "Откройте сервис напрямую в браузере");
      }
      const authorization = req.headers.authorization;
      if (!authorization?.startsWith("Bearer ocr_")) return fail(401, "Введите API-ключ интеграции (ocr_…)");
      const chunks = [];
      let size = 0;
      for await (const chunk of req) {
        size += chunk.length;
        if (size > MAX_BODY) return fail(413, "Максимальный размер файла — 20 МБ");
        chunks.push(chunk);
      }
      const headers = { Authorization: authorization };
      if (req.headers["content-type"]) headers["Content-Type"] = req.headers["content-type"];
      const response = await fetchImpl(new URL(url.pathname + url.search, upstream), {
        method: req.method, headers, redirect: "error", signal: AbortSignal.timeout(300_000),
        ...(req.method === "POST" ? { body: Buffer.concat(chunks) } : {}),
      });
      const body = await response.text();
      res.writeHead(response.status, { "Content-Type": "application/json; charset=utf-8" });
      res.end(body);
    } catch (error) {
      fail(error.name === "TimeoutError" ? 504 : 502,
        error.name === "TimeoutError" ? "API не ответил за 5 минут. Проверьте историю перед повторной отправкой файла." : "Не удалось обратиться к OCR API. Проверьте, что приложение запущено и SIMULATOR_API_URL указан верно. При сбое отправки проверьте историю перед повтором.");
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.loadEnvFile) {
    try { process.loadEnvFile(); } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  const port = Number(process.env.SIMULATOR_PORT || 5180);
  const target = process.env.SIMULATOR_API_URL || `http://127.0.0.1:${process.env.BACKEND_PORT || 8000}`;
  const server = createSimulator({ target });
  server.on("error", (error) => { console.error(`Симулятор: ${error.message}`); process.exitCode = 1; });
  server.listen(port, "127.0.0.1", () => console.log(`Симулятор импорта: http://127.0.0.1:${port}`));
}
