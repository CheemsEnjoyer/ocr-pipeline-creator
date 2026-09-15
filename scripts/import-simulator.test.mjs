import { test } from "node:test";
import assert from "node:assert/strict";
import { createSimulator } from "./import-simulator.mjs";

async function simulator(t, fetchImpl) {
  const server = createSimulator({ target: "http://ocr.test:8000", fetchImpl });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => { server.close(resolve); server.closeAllConnections(); }));
  return `http://127.0.0.1:${server.address().port}`;
}
const headers = { Authorization: "Bearer ocr_test" };

test("forwards API key and pagination, never admin cookie", async (t) => {
  const base = await simulator(t, async (url, options) => {
    assert.equal(url.href, "http://ocr.test:8000/api/v1/documents?page=2");
    assert.deepEqual(options.headers, headers);
    assert.equal(options.redirect, "error");
    return Response.json({ documents: [{ id: "doc-1", fields: { amount: 123 } }], hasMore: false });
  });
  const response = await fetch(base + "/api/v1/documents?page=2", { headers: { ...headers, Cookie: "admin_session=secret" } });
  assert.equal(response.status, 200);
  assert.equal((await response.json()).documents[0].fields.amount, 123);
});

test("forwards multipart file without corrupting content", async (t) => {
  const base = await simulator(t, async (url, options) => {
    assert.equal(url.pathname, "/api/v1/pipelines/pl_test/run");
    const request = new Request(url, options);
    const form = await request.formData();
    assert.equal(form.get("file").name, "test.txt");
    assert.equal(await form.get("file").text(), "Счёт 1500");
    return Response.json({ documentId: "doc-1" });
  });
  const body = new FormData(); body.append("file", new Blob(["Счёт 1500"]), "test.txt");
  const response = await fetch(base + "/api/v1/pipelines/pl_test/run", { method: "POST", headers, body });
  assert.equal((await response.json()).documentId, "doc-1");
});

test("forwards background job status without exposing admin credentials", async (t) => {
  const base = await simulator(t, async (url, options) => {
    assert.equal(url.pathname, "/api/v1/jobs/task-1");
    assert.deepEqual(options.headers, headers);
    return Response.json({ taskId: "task-1", status: "succeeded", documentId: "doc-1" });
  });
  const response = await fetch(base + "/api/v1/jobs/task-1", { headers });
  assert.equal((await response.json()).documentId, "doc-1");
});

test("preserves revoked key and forbidden pipeline errors", async (t) => {
  for (const status of [401, 403, 404]) {
    const base = await simulator(t, async () => Response.json({ detail: "Нет доступа" }, { status }));
    const response = await fetch(base + "/api/v1/pipelines", { headers });
    assert.equal(response.status, status);
    assert.equal((await response.json()).detail, "Нет доступа");
  }
});

test("blocks unsupported routes, missing key and cross-origin requests", async (t) => {
  const base = await simulator(t, async () => { throw new Error("Must not call upstream"); });
  for (const [path, options, status] of [
    ["/api/keys", { headers }, 404],
    ["/api/v1/pipelines", {}, 401],
    ["/api/v1/documents", { headers: { ...headers, Origin: "https://other.test" } }, 403],
  ]) assert.equal((await fetch(base + path, options)).status, status);
});

test("explains unavailable upstream and serves standalone UI", async (t) => {
  const base = await simulator(t, async () => { throw new TypeError("fetch failed"); });
  const response = await fetch(base + "/api/v1/pipelines", { headers });
  assert.equal(response.status, 502);
  assert.match((await response.json()).detail, /SIMULATOR_API_URL/);
  const page = await fetch(base);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Симулятор импорта по API/);
});
