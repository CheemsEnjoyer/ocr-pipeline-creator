import hashlib
import json
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import httpx
import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.api.policies import COOKIE
from backend.handler.keycloak import KeycloakSettings, digest
from backend.server import create_app
from backend.db.domain.models import OIDCFlow, OIDCSession
from backend.tests import test_api as api_tests


class KeycloakTests(unittest.TestCase):
    def setUp(self):
        self.fixture = api_tests.APITests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        environment = patch.dict("os.environ", {"AUTH_PROVIDER": "keycloak", "KEYCLOAK_URL": "https://identity.test", "KEYCLOAK_REALM": "company", "KEYCLOAK_CLIENT_ID": "ocr", "KEYCLOAK_CLIENT_SECRET": "test-client-secret", "APP_PUBLIC_URL": "https://app.test", "KEYCLOAK_SESSION_KEY": Fernet.generate_key().decode(), "KEYCLOAK_ROLE_SCOPE": "client", "KEYCLOAK_ADMIN_ROLE": "admin", "KEYCLOAK_USER_ROLE": "user", "KEYCLOAK_ADMIN_CLIENT_ID": "ocr-management", "KEYCLOAK_ADMIN_CLIENT_SECRET": "test-management-secret"})
        environment.start()
        self.addCleanup(environment.stop)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        self.jwk.update(kid="signing-key", alg="RS256", use="sig")
        self.nonce, self.active, self.roles = "", True, ["admin"]
        self.requests = []
        self.accounts = {"alice": {"id": "alice", "username": "alice", "firstName": "Alice", "email": "alice@example.com", "enabled": True}, "bob": {"id": "bob", "username": "bob", "email": "bob@example.com", "enabled": True}, "other": {"id": "other", "username": "other", "enabled": True}}
        self.assignments = {"alice": ["admin"], "bob": ["user", "unrelated"], "other": ["unrelated"]}
        self.fail_email = False
        self.app = create_app(self.fixture.database_url, self.fixture.storage, httpx.MockTransport(self.upstream))
        self.client = TestClient(self.app, base_url="https://app.test", follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def token(self, identity=False, **overrides):
        claims = {"iss": self.app.state.keycloak.settings.issuer, "sub": "alice", "iat": int(time.time()), "exp": int(time.time())+300, "azp": "ocr", "aud": "ocr" if identity else "account", "nonce": self.nonce, "preferred_username": "alice", "name": "Alice", "resource_access": {"ocr": {"roles": self.roles}}}
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "signing-key"})

    def upstream(self, request):
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [self.jwk]})
        if path.endswith("/token/introspect"):
            return httpx.Response(200, json={"active": self.active})
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["client_credentials"]:
                return httpx.Response(200, json={"access_token": "management-token", "expires_in": 60})
            return httpx.Response(200, json={"access_token": self.token(), "id_token": self.token(identity=True), "refresh_token": "test-refresh-token"})
        admin = "/admin/realms/company"
        if path.startswith(admin):
            self.assertEqual(request.headers["Authorization"], "Bearer management-token")
            relative = path[len(admin):]
            if relative == "/clients":
                return httpx.Response(200, json=[{"id": "client-uuid", "clientId": "ocr"}])
            if relative.startswith("/clients/client-uuid/roles/"):
                role = relative.rsplit("/", 1)[-1]
                return httpx.Response(200, json={"id": role, "name": role, "composite": False})
            if relative == "/users":
                if request.method == "POST":
                    data = json.loads(request.content)
                    data["id"] = "new-user"
                    self.accounts[data["id"]] = data
                    self.assignments[data["id"]] = []
                    return httpx.Response(201, headers={"Location": "https://identity.test" + admin + "/users/new-user"})
                users = list(self.accounts.values())
                if request.url.params.get("username"):
                    users = [user for user in users if user["username"] == request.url.params["username"]]
                return httpx.Response(200, json=users)
            user_id = relative.split("/")[2]
            if "/role-mappings/" in relative:
                roles = self.assignments.get(user_id, [])
                if request.method == "POST":
                    roles.extend(role["id"] for role in json.loads(request.content))
                elif request.method == "DELETE":
                    removed = {role["id"] for role in json.loads(request.content)}
                    self.assignments[user_id] = [role for role in roles if role not in removed]
                else:
                    return httpx.Response(200, json=[{"id": role, "name": role} for role in roles])
                return httpx.Response(204)
            if relative.endswith("/execute-actions-email"):
                return httpx.Response(500 if self.fail_email else 204)
            return httpx.Response(200, json=self.accounts[user_id])
        return self.fixture.upstream(request)

    def login(self):
        start = self.client.get("/api/auth/keycloak/login")
        self.assertEqual(start.status_code, 302)
        query = parse_qs(urlsplit(start.headers["Location"]).query)
        self.nonce = query["nonce"][0]
        response = self.client.get("/api/auth/keycloak/callback", params={"state": query["state"][0], "code": "test-code"})
        self.assertEqual(response.status_code, 302, response.text)
        return query

    def test_code_flow_pkce_cookies_and_encrypted_tokens(self):
        query = self.login()
        self.assertEqual(query["code_challenge_method"], ["S256"])
        exchange = next(request for request in self.requests if request.url.path.endswith("/token"))
        verifier = parse_qs(exchange.content.decode())["code_verifier"][0]
        import base64
        self.assertEqual(query["code_challenge"][0], base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode())
        response = self.client.get("/api/auth/session")
        self.assertEqual(response.json()["role"], "admin")
        self.assertEqual(response.json()["provider"], "keycloak")
        with self.app.state.sessions() as session:
            row = session.scalar(select(OIDCSession))
            self.assertNotIn("test-refresh-token", row.payload)
            self.assertNotIn(self.client.cookies.get(COOKIE), row.id)
            self.assertIsNone(session.scalar(select(OIDCFlow)))
        cookie = next(cookie for cookie in self.client.cookies.jar if cookie.name == COOKIE)
        self.assertTrue(cookie.secure)
        self.assertIn("HttpOnly", cookie._rest)
        replay = self.client.get("/api/auth/keycloak/callback", params={"state": query["state"][0], "code": "test-code"})
        self.assertEqual(replay.status_code, 400)

    def test_state_and_token_validation(self):
        self.assertEqual(self.client.get("/api/auth/keycloak/callback?state=wrong&code=x").status_code, 400)
        kc = self.app.state.keycloak
        for overrides in ({"iss": "https://attacker.test"}, {"azp": "another-client"}, {"exp": int(time.time())-60}):
            with self.subTest(overrides=overrides), self.assertRaises(HTTPException):
                kc.validate(self.token(**overrides))
        with self.assertRaises(HTTPException):
            kc.validate(self.token(identity=True, aud="other"), identity=True)
        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(jwt.decode(self.token(), options={"verify_signature": False}), wrong_key, algorithm="RS256", headers={"kid": "signing-key"})
        with self.assertRaises(HTTPException):
            kc.validate(forged)

    def test_no_local_password_or_session_bypass(self):
        self.assertEqual(self.client.post("/api/auth/login", json=api_tests.ADMIN_CREDENTIALS).status_code, 409)
        self.client.cookies.set(COOKIE, self.fixture.client.cookies.get(COOKIE))
        self.assertEqual(self.client.get("/api/auth/session").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/invitations/accept", json={"token": "x"*30, "password": "password123"}).status_code, 404)

    def test_user_permissions_and_missing_role(self):
        self.roles = ["user"]
        self.login()
        self.assertEqual(self.client.get("/api/users").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/documents").status_code, 200)
        self.roles = []
        with self.assertRaises(HTTPException):
            self.app.state.keycloak.role({"resource_access": {}})

    def test_refresh_roles_and_remote_revocation(self):
        self.login()
        with self.app.state.sessions.begin() as session:
            row = session.scalar(select(OIDCSession))
            data = self.app.state.keycloak.decode(row.payload)
            data["access_expires_at"] = 0
            row.payload = self.app.state.keycloak.encode(data)
        self.roles = ["user"]
        self.assertEqual(self.client.get("/api/auth/session").json()["role"], "user")
        self.active = False
        self.assertEqual(self.client.get("/api/auth/session").status_code, 401)
        with self.app.state.sessions() as session:
            self.assertIsNone(session.scalar(select(OIDCSession)))

    def test_logout_clears_local_and_redirects_sso_even_if_expired(self):
        self.login()
        self.active = False
        response = self.client.post("/api/auth/keycloak/logout", headers={"Origin": "https://app.test"})
        self.assertEqual(response.status_code, 200)
        query = parse_qs(urlsplit(response.json()["logoutUrl"]).query)
        self.assertEqual(query["post_logout_redirect_uri"], ["https://app.test/login"])
        self.assertIn("id_token_hint", query)
        self.assertIsNone(self.client.cookies.get(COOKIE))
        self.assertEqual(self.client.post("/api/auth/keycloak/logout", headers={"Origin": "https://attacker.test"}).status_code, 403)

    def test_admin_membership_scope_and_role_changes(self):
        self.login()
        users = self.client.get("/api/users").json()["users"]
        self.assertEqual({user["id"] for user in users}, {"alice", "bob"})
        self.assertEqual(self.client.patch("/api/users/alice", json={"role": "user"}).status_code, 409)
        self.assertEqual(self.client.patch("/api/users/bob", json={"role": "admin"}).status_code, 200)
        self.assertEqual(set(self.assignments["bob"]), {"admin", "unrelated"})
        self.assertEqual(self.client.delete("/api/users/bob").status_code, 200)
        self.assertEqual(self.assignments["bob"], ["unrelated"])
        self.assertIn("bob", self.accounts)
        self.assertEqual(self.client.delete("/api/users/other").status_code, 404)

    def test_invitation_email_and_delivery_failure_rollback(self):
        self.login()
        payload = {"login": "new", "name": "New User", "email": "new@example.com", "role": "user"}
        self.fail_email = True
        self.assertEqual(self.client.post("/api/users/invite", json=payload).status_code, 503)
        self.assertEqual(self.assignments["new-user"], [])
        self.fail_email = False
        result = self.client.post("/api/users/invite", json=payload)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertTrue(result.json()["emailSent"])
        self.assertEqual(self.assignments["new-user"], ["user"])
        self.assertEqual(self.client.post("/api/users/invite", json=payload).status_code, 409)

    def test_configuration_validation_and_unavailable_server(self):
        with patch.dict("os.environ", {"KEYCLOAK_URL": ""}), self.assertRaises(RuntimeError):
            KeycloakSettings.from_env()
        with patch.dict("os.environ", {"KEYCLOAK_URL": "http://identity.test"}), self.assertRaises(RuntimeError):
            KeycloakSettings.from_env()
        self.login()
        def unavailable(request):
            raise httpx.ConnectError("unavailable", request=request)
        self.app.state.keycloak.http.close()
        self.app.state.keycloak.http = httpx.Client(transport=httpx.MockTransport(unavailable))
        self.assertEqual(self.client.get("/api/auth/session").status_code, 503)


if __name__ == "__main__":
    unittest.main()
