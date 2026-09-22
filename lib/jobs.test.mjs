import { test } from "node:test";
import assert from "node:assert/strict";
import { waitForJob } from "./jobs.js";

test("polls queued and processing jobs until the saved document is ready", async () => {
  const responses = [{ status: "queued", stage: "queued" }, { status: "processing", stage: "extraction" }, { status: "succeeded", stage: "completed", documentId: "doc", result: "text" }];
  const updates = [];
  const result = await waitForJob("/api/jobs/task", { interval: 1, fetchImpl: async (url) => {
    assert.equal(url, "/api/jobs/task");
    return Response.json(responses.shift());
  }, onUpdate: (status) => updates.push(status.stage) });
  assert.equal(result.documentId, "doc");
  assert.equal(responses.length, 0);
  assert.deepEqual(updates, ["queued", "extraction", "completed"]);
});

test("distinguishes terminal task failures from temporary status request errors", async () => {
  await assert.rejects(waitForJob("/api/jobs/task", { fetchImpl: async () => Response.json({ status: "failed", stage: "failed", failedStage: "recognition", error: "OCR failed" }) }), error => error.taskFailed && error.failedStage === "recognition" && error.message === "OCR failed");
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
