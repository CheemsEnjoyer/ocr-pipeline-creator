// Keep the browser on the frontend origin; processing and persistence live in Python.
// Compare hosts, not full origins: behind an HTTPS reverse proxy the server sees http:// while the browser sends https://.
function sameHost(origin: string, host: string) {
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

async function proxy(request: Request) {
  const incoming = new URL(request.url);
  const origin = request.headers.get("origin");
  if (!["GET", "HEAD"].includes(request.method) && origin && !sameHost(origin, incoming.host)) {
    return Response.json({ error: "Недопустимый источник запроса" }, { status: 403 });
  }
  const base = process.env.BACKEND_URL || "http://127.0.0.1:8000";
  const headers = new Headers();
  for (const name of ["content-type", "range", "if-range", "authorization", "cookie"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const target = new URL(base);
    target.pathname = incoming.pathname;
    target.search = incoming.search;
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      ...({ duplex: "half" } as object),
      redirect: "manual",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(600_000)]),
    });
    const responseHeaders = new Headers();
    for (const name of ["content-type", "content-disposition", "content-length", "content-range", "accept-ranges", "x-content-type-options", "content-security-policy"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append("set-cookie", cookie);
    responseHeaders.set("Cache-Control", "no-store");
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json({ error: "Python-сервер недоступен. Запустите приложение через npm run dev и проверьте сообщения в терминале." }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;

export const DELETE = proxy;
