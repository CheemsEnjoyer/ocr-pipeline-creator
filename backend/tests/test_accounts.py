import time
import unittest
from urllib.parse import urlsplit, parse_qs

from fastapi.testclient import TestClient
from backend.db.domain.models import User
from backend.service.accounts import hash_password, verify_password
from backend.tests import test_api


class UserTests(unittest.TestCase):
    setUp = test_api.APITests.setUp
    database_for = test_api.APITests.database_for
    make_app = test_api.APITests.make_app
    upstream = test_api.APITests.upstream
    sign_in = test_api.APITests.sign_in

    def invite(self, login="colleague", role="user"):
        response = self.client.post("/api/users/invite", json={"login":login, "name":"Test colleague", "role":role})
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        token = parse_qs(urlsplit(data["invitePath"]).fragment)["token"][0]
        return data["user"], token

    def activate(self, token):
        return self.client.post("/api/auth/invitations/accept", json={"token":token, "password":"colleague-password-123"})

    def browser(self):
        browser = TestClient(self.app)
        response = browser.post("/api/auth/login", json={"login":"colleague", "password":"colleague-password-123"})
        self.assertEqual(response.status_code, 200, response.text)
        return browser

    def test_normal_user_can_process_but_cannot_administer(self):
        user, token = self.invite()
        self.assertEqual(self.activate(token).status_code, 200)
        browser = self.browser()
        self.assertEqual(browser.get("/api/auth/session").json()["role"], "user")
        for path in ("/api/users", "/api/keys"):
            self.assertEqual(browser.get(path).status_code, 403)
        self.assertEqual(browser.post("/api/users/invite", json={"login":"other", "name":"Other", "role":"admin"}).status_code, 403)
        self.assertEqual(browser.patch(f"/api/users/{user['id']}", json={"role":"admin"}).status_code, 403)
        self.assertEqual(browser.post("/api/pipelines", json={"id":"forbidden", "name":"Forbidden", "source":"document"}).status_code, 403)
        created = self.client.post("/api/pipelines", json={"name":"Shared", "source":"document"})
        self.assertEqual(created.status_code, 201, created.text)
        pipeline_id = created.json()["pipeline"]["id"]
        self.assertEqual(browser.get("/api/pipelines").json()["pipelines"][0]["id"], pipeline_id)
        processed = browser.post(f"/api/pipelines/{pipeline_id}/run", files={"file":("text.txt", b"Shared document", "text/plain")})
        self.assertEqual(processed.status_code, 200, processed.text)
        self.assertEqual(len(browser.get("/api/documents").json()["documents"]), 1)
        self.assertEqual(browser.get("/api/history/pipelines").status_code, 200)
        self.assertEqual(browser.post("/api/auth/logout").status_code, 200)
        self.assertEqual(browser.get("/api/auth/session").status_code, 401)

    def test_invitation_is_single_use_and_expires(self):
        user, token = self.invite()
        self.assertEqual(self.activate(token).status_code, 200)
        self.assertEqual(self.activate(token).status_code, 400)
        other, expired = self.invite("expired")
        with self.app.state.sessions.begin() as session:
            session.get(User, other["id"]).invite_expires = time.time() - 1
        self.assertEqual(self.activate(expired).status_code, 400)
        self.assertEqual(TestClient(self.app).post("/api/auth/login", json={"login":"expired", "password":"colleague-password-123"}).status_code, 401)

    def test_live_role_changes_and_deletion_revoke_access(self):
        user, token = self.invite(role="admin")
        self.activate(token)
        browser = self.browser()
        self.assertEqual(browser.get("/api/users").status_code, 200)
        self.assertEqual(self.client.patch(f"/api/users/{user['id']}", json={"role":"user"}).status_code, 200)
        self.assertEqual(browser.get("/api/auth/session").json()["role"], "user")
        self.assertEqual(browser.get("/api/users").status_code, 403)
        self.assertEqual(self.client.patch(f"/api/users/{user['id']}", json={"role":"admin"}).status_code, 200)
        self.assertEqual(browser.get("/api/users").status_code, 200)
        before = len(self.client.get("/api/documents").json()["documents"])
        self.assertEqual(self.client.delete(f"/api/users/{user['id']}").status_code, 200)
        self.assertEqual(browser.get("/api/auth/session").status_code, 401)
        self.assertEqual(browser.post("/api/auth/login", json={"login":"colleague", "password":"colleague-password-123"}).status_code, 401)
        self.assertEqual(len(self.client.get("/api/documents").json()["documents"]), before)

    def test_bootstrap_and_self_management_are_protected(self):
        current = self.client.get("/api/auth/session").json()
        self.assertEqual(self.client.delete(f"/api/users/{current['id']}").status_code, 409)
        self.assertEqual(self.client.patch(f"/api/users/{current['id']}", json={"role":"user"}).status_code, 409)
        user, token = self.invite(role="admin")
        self.activate(token)
        browser = self.browser()
        for target in (user["id"], current["id"]):
            self.assertEqual(browser.delete(f"/api/users/{target}").status_code, 409)
            self.assertEqual(browser.patch(f"/api/users/{target}", json={"role":"user"}).status_code, 409)

    def test_secrets_and_duplicate_logins(self):
        user, token = self.invite()
        self.assertNotIn(token, self.client.get("/api/users").text)
        self.activate(token)
        with self.app.state.sessions() as session:
            stored = session.get(User, user["id"]).password_hash
            self.assertTrue(stored.startswith("scrypt$"))
            self.assertNotIn("colleague-password-123", stored)
        response = self.client.get("/api/users").text
        self.assertNotIn(stored, response)
        self.assertNotIn("password_hash", response)
        self.assertNotIn("invite_hash", response)
        self.assertEqual(self.client.post("/api/users/invite", json={"login":"colleague", "name":"Other"}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/users/{user['id']}", json={"role":"owner"}).status_code, 422)
        first, second = hash_password("password-123"), hash_password("password-123")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("password-123", first))
        self.assertFalse(verify_password("wrong-password", first))

    def test_deleted_invitation_is_revoked_and_login_can_be_reinvited(self):
        user, token = self.invite()
        self.client.delete(f"/api/users/{user['id']}")
        self.assertEqual(self.activate(token).status_code, 400)
        again, new_token = self.invite()
        self.assertEqual(again["id"], user["id"])
        self.assertNotEqual(token, new_token)
        self.assertEqual(self.activate(new_token).status_code, 200)
