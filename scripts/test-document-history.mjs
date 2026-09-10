import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";

// Run against the local dev server after applying the documents migration.
const base = "http://localhost:5173";
let id;
try {
  const original = JSON.stringify({ document_number: "TEST-001", total_amount: 1250, verified: false, lines: [{ name: "Тест", qty: 2 }] });
  const form = new FormData();
  form.append("file", new File([original], "history-integration-test.json", { type: "application/json" }));
  form.append("pipeline", JSON.stringify({ name: "Проверка истории", source: "document", extraction: null }));
  const processed = await fetch(`${base}/api/pipeline/run`, { method: "POST", body: form });
  const result = await processed.json();
  assert.equal(processed.status, 200, JSON.stringify(result));
  id = result.documentId;
  assert.match(id, /^[a-f0-9-]{36}$/);
  const list = await (await fetch(`${base}/api/documents`)).json();
  assert.ok(list.documents.some((entry) => entry.id === id));
  const detail = await (await fetch(`${base}/api/documents/${id}`)).json();
  assert.equal(detail.document.text, original);
  assert.equal(detail.document.fields.total_amount, 1250);
  const source = await fetch(`${base}/api/documents/${id}/original`);
  assert.equal(await source.text(), original);
  assert.match(source.headers.get("content-disposition"), /^attachment/);
  const fields = { ...detail.document.fields, total_amount: 1500, verified: true };
  const save = await fetch(`${base}/api/documents/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fields, revision: 0 }) });
  assert.equal(save.status, 200);
  const reloaded = await (await fetch(`${base}/api/documents/${id}`)).json();
  assert.deepEqual(reloaded.document.fields, fields);
  assert.equal(reloaded.document.text, original, "Editing fields must preserve recognized text");
  assert.equal(reloaded.document.result, original, "Editing fields must preserve the original model result");
  const conflict = await fetch(`${base}/api/documents/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fields, revision: 0 }) });
  assert.equal(conflict.status, 409);
  const invalid = await fetch(`${base}/api/documents/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fields: [], revision: 1 }) });
  assert.equal(invalid.status, 400);
  const missing = await fetch(`${base}/api/documents/missing`);
  assert.equal(missing.status, 404);
  for (const route of ["/", "/process", "/history"]) assert.equal((await fetch(`${base}${route}`)).status, 200, route);
  console.log("PASS: processing, history, source bytes, typed fields, persistence, conflict protection, validation, and page rendering.");
} finally {
  if (id && /^[a-f0-9-]{36}$/.test(id)) {
    const run = (args) => execFileSync(process.execPath, ["node_modules/wrangler/bin/wrangler.js", ...args, "--local", "--config", "dist/server/wrangler.json", "--persist-to", ".wrangler/state"], { stdio: "pipe" });
    run(["d1", "execute", "DB", "--command", `DELETE FROM documents WHERE id = '${id}'`]);
    run(["r2", "object", "delete", `site-creator-r2/documents/${id}/original`]);
    console.log("Test document removed from local storage.");
  }
}
