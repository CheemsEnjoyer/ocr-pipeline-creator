import { test } from "node:test";
import assert from "node:assert/strict";
import { waitForJob } from "./jobs.js";

test("polls queued and processing jobs until the saved document is ready", async () => {
  const responses = [{ status: "queued" }, { status: "processing" }, { status: "succeeded", documentId: "doc", result: "text" }];
  const result = await waitForJob("/api/jobs/task", { interval: 1, fetchImpl: async (url) => {
    assert.equal(url, "/api/jobs/task");
    return Response.json(responses.shift());
  } });
  assert.equal(result.documentId, "doc");
  assert.equal(responses.length, 0);
});

test("distinguishes terminal task failures from temporary status request errors", async () => {
  await assert.rejects(waitForJob("/api/jobs/task", { fetchImpl: async () => Response.json({ status: "failed", error: "OCR failed" }) }), error => error.taskFailed && error.message === "OCR failed");
  await assert.rejects(waitForJob("/api/jobs/task", { fetchImpl: async () => Response.json({ error: "No access" }, { status: 401 }) }), error => !error.taskFailed && error.message === "No access");
});

test("stops polling when the page is closed", async () => {
  const controller = new AbortController();
  let calls = 0;
  await assert.rejects(waitForJob("/api/jobs/task", { signal: controller.signal, fetchImpl: async () => {
    calls++;
    controller.abort();
    return Response.json({ status: "queued" });
  } }), { name: "AbortError" });
  assert.equal(calls, 1);
});
