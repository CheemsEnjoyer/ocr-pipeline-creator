import assert from "node:assert/strict";
import { test } from "node:test";
import { GET, POST } from "../app/api/[...path]/route.ts";

test("OIDC redirects and state/session cookies pass through the frontend", async (context) => {
  context.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(new URL(url).pathname, "/api/auth/keycloak/login");
    assert.equal(options.redirect, "manual");
    return new Response(null, {status: 302, headers: {
      location: "https://identity.test/realms/company/protocol/openid-connect/auth?state=test",
      "set-cookie": "ocr_oidc_state=test; HttpOnly; Secure; SameSite=Lax; Path=/api/auth/keycloak",
    }});
  });
  const response = await GET(new Request("https://ocr.test/api/auth/keycloak/login"));
  assert.equal(response.status, 302);
  assert.equal(response.headers.get("location"), "https://identity.test/realms/company/protocol/openid-connect/auth?state=test");
  assert.match(response.headers.get("set-cookie"), /HttpOnly/);
});

test("logout passes the browser origin and refuses a foreign origin", async (context) => {
  context.mock.method(globalThis, "fetch", async (_url, options) => {
    assert.equal(options.headers.get("origin"), "https://ocr.test");
    assert.equal(options.headers.get("cookie"), "ocr_admin_session=test");
    return Response.json({status: "ok", logoutUrl: "https://identity.test/logout"});
  });
  const response = await POST(new Request("http://ocr.test/api/auth/keycloak/logout", {method: "POST", headers: {origin: "https://ocr.test", cookie: "ocr_admin_session=test"}}));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).logoutUrl, "https://identity.test/logout");
  const refused = await POST(new Request("http://ocr.test/api/auth/keycloak/logout", {method: "POST", headers: {origin: "https://attacker.test"}}));
  assert.equal(refused.status, 403);
});
