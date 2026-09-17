import test from "node:test";
import assert from "node:assert/strict";
import { validFields, serializeFields } from "./extraction-fields.js";

test("nested configuration preserves types and separate descriptions through serialization", () => {
  const fields = [{ name: " objects ", type: "array", public_description: "Objects", description: "Internal rule", fields: [
    { name: "name", description: "Legacy instruction" },
    { name: "size", type: "number", public_description: "Area" },
    { name: "metadata", type: "object", fields: [{ name: "active", type: "boolean" }] },
  ] }];
  assert.equal(validFields(fields), true);
  const saved = serializeFields(fields);
  assert.equal(saved[0].name, "objects");
  assert.equal(saved[0].description, "Internal rule");
  assert.equal(saved[0].public_description, "Objects");
  assert.equal(saved[0].fields[0].type, "string");
  assert.equal(saved[0].fields[0].public_description, "");
  assert.equal(saved[0].fields[1].type, "number");
  assert.equal(saved[0].fields[2].fields[0].type, "boolean");
  assert.deepEqual(serializeFields(JSON.parse(JSON.stringify(saved))), saved);
});

test("each object requires nonempty unique sibling names", () => {
  assert.equal(validFields([{ name: "objects", type: "array", fields: [] }]), false);
  assert.equal(validFields([{ name: "objects", type: "array", fields: [{ name: "x" }, { name: " x " }] }]), false);
  assert.equal(validFields([{ name: "objects", type: "object", fields: [{ name: " " }] }]), false);
  assert.equal(validFields([{ name: "a", type: "object", fields: [{ name: "a" }] }]), true);
  let field = { name: "leaf" };
  for (let i = 0; i < 6; i++) field = { name: "parent", type: "array", fields: [field] };
  assert.equal(validFields([field]), false);
});
