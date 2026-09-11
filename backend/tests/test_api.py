import io
import json
import os
import tempfile
import unittest
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, update

from backend.access import FAILED_LOGIN_WINDOW, MAX_FAILED_LOGINS
from backend.database import AdminSession, APIKey
from backend.main import MAX_FILE_SIZE, create_app
from backend.processing import proxy_options

ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "test-password-123"
ADMIN_CREDENTIALS = {"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD}


class APITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.storage = Path(self.temporary.name)
        self.database_url = f"sqlite:///{(self.storage / 'test.sqlite3').as_posix()}"
        self.calls = []
        self.fail_upstream = False
        self.refuse_upstream = False
        self.environment = patch.dict("os.environ", {"LITELLM_BASE_URL": "http://litellm.test/v1", "LITELLM_API_KEY": "test-key", "OCR_ADMIN_LOGIN": ADMIN_LOGIN, "OCR_ADMIN_PASSWORD": ADMIN_PASSWORD})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = self.make_app()
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.sign_in(self.client)

    def upstream(self, request):
        self.calls.append(request)
        if self.refuse_upstream:
            raise httpx.ConnectError("Соединение отклонено", request=request)
        if self.fail_upstream:
            return httpx.Response(503)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "vision"}, {"id": "extract"}, {"id": "vision"}]})
        if request.url.host == "ocr.test":
            return httpx.Response(200, json={"page_content": "Распознанный текст"})
        body = json.loads(request.content)
        content = "Распознанный текст" if body["model"] == "vision" else '{"total": 1500, "verified": false}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    def make_app(self):
        return create_app(self.database_url, self.storage, httpx.MockTransport(self.upstream))

    def sign_in(self, client):
        response = client.post("/api/auth/login", json=ADMIN_CREDENTIALS)
        self.assertEqual(response.status_code, 200, response.text)
        return client

    @contextmanager
    def restarted_app(self):
        # Новый жизненный цикл приложения на той же базе, с новым входом администратора.
        with TestClient(self.make_app()) as client:
            yield self.sign_in(client)

    def upload(self, content=b'{"total": 1250}', filename="test.json", mime="application/json", pipeline=None):
        return self.client.post("/api/pipeline/run", files={"file": (filename, content, mime)}, data={"pipeline": json.dumps(pipeline or {"source": "document", "name": "Тест"})})

    def test_pipeline_catalog_and_run(self):
        self.assertEqual(self.client.get("/api/pipelines").json(), {"pipelines": []})
        config = {"name": "Catalog test", "source": "scans", "ocr": {"provider": "litellm", "model": "vision", "temperature": 0.4}, "extraction": {"mode": "prompt", "model": "extract", "prompt": "JSON", "temperature": 0.7, "max_tokens": 512}}
        created = self.client.post("/api/pipelines", json=config)
        self.assertEqual(created.status_code, 201, created.text)
        pipeline = created.json()["pipeline"]
        self.assertTrue(pipeline["id"].startswith("pl_"))
        listed = self.client.get("/api/pipelines").json()["pipelines"]
        self.assertEqual(listed, [pipeline])
        self.assertEqual(self.upload(b"image", "scan.png", "image/png", listed[0]).status_code, 200)
        with self.restarted_app() as restarted:
            self.assertEqual(restarted.get("/api/pipelines").json()["pipelines"], listed)
        changed = {**pipeline, "name": "Updated"}
        self.assertEqual(self.client.patch(f"/api/pipelines/{pipeline['id']}", json=changed).status_code, 200)
        self.assertEqual(self.client.get("/api/pipelines").json()["pipelines"][0]["name"], "Updated")
        self.assertEqual(self.client.delete(f"/api/pipelines/{pipeline['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/pipelines").json()["pipelines"], [])

    def test_pipeline_import_preserves_edits_and_deletions(self):
        legacy = {"id": "pl_legacy", "name": "Legacy", "source": "document", "extraction": None}
        for _ in range(2):
            self.assertEqual(self.client.post("/api/pipelines/import", json=[legacy]).status_code, 200)
        self.assertEqual(len(self.client.get("/api/pipelines").json()["pipelines"]), 1)
        self.client.patch("/api/pipelines/pl_legacy", json={**legacy, "name": "Server edit"})
        self.client.post("/api/pipelines/import", json=[legacy])
        self.assertEqual(self.client.get("/api/pipelines").json()["pipelines"][0]["name"], "Server edit")
        self.client.delete("/api/pipelines/pl_legacy")
        self.client.post("/api/pipelines/import", json=[legacy])
        self.assertEqual(self.client.get("/api/pipelines").json()["pipelines"], [])
        self.assertEqual(self.client.patch("/api/pipelines/missing", json=legacy).status_code, 404)
        self.assertEqual(self.client.post("/api/pipelines", json={"source": "invalid"}).status_code, 422)

    def test_create_history_edit_original_and_restart(self):
        with self.app.state.sessions() as session:
            self.assertIn("documents", inspect(session.bind).get_table_names())
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.text)
        document_id = response.json()["documentId"]
        self.assertEqual(self.client.get("/api/documents").json()["documents"][0]["id"], document_id)
        before = self.client.get(f"/api/documents/{document_id}").json()["document"]
        updated = self.client.patch(f"/api/documents/{document_id}", json={"fields": {"total": 1500, "lines": [1, 2]}, "revision": 0})
        self.assertEqual(updated.status_code, 200)
        source = self.client.get(f"/api/documents/{document_id}/original")
        self.assertEqual(source.content, b'{"total": 1250}')
        self.assertIn("attachment", source.headers["content-disposition"])
        conflict = self.client.patch(f"/api/documents/{document_id}", json={"fields": {}, "revision": 0})
        self.assertEqual(conflict.status_code, 409)
        # A second application lifespan reuses the same SQLite file without SQL commands.
        with self.restarted_app() as restarted:
            after = restarted.get(f"/api/documents/{document_id}").json()["document"]
            self.assertEqual(after["fields"], {"total": 1500, "lines": [1, 2]})
            self.assertEqual(after["text"], before["text"])
            self.assertEqual(after["result"], before["result"])
            self.assertEqual(after["revision"], 1)

    def test_vision_and_extraction(self):
        response = self.upload(b"image", "scan.png", "image/png", {"source": "scans", "ocr": {"provider": "litellm", "model": "vision"}, "extraction": {"mode": "fields", "model": "extract", "fields": [{"name": "total", "description": "Сумма"}]}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["text"], "Распознанный текст")
        row = self.client.get(f"/api/documents/{response.json()['documentId']}").json()["document"]
        self.assertEqual(row["fields"], {"total": 1500, "verified": False})
        self.assertTrue(all(call.headers.get("authorization") == "Bearer test-key" for call in self.calls))
        self.assertEqual(self.calls[0].url.path, "/v1/chat/completions")
        self.assertTrue(json.loads(self.calls[0].content)["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(json.loads(self.calls[1].content)["messages"][1]["content"], "Распознанный текст")

    def test_pipeline_temperatures(self):
        for temperatures in ({}, {"ocr": 0.3, "extraction": 0.8}, {"ocr": 0, "extraction": 2}):
            with self.subTest(temperatures=temperatures):
                self.calls.clear()
                pipeline = {"source": "scans", "ocr": {"provider": "litellm", "model": "vision"}, "extraction": {"mode": "prompt", "model": "extract", "prompt": "JSON"}}
                for stage, value in temperatures.items():
                    pipeline[stage]["temperature"] = value
                response = self.upload(b"image", "scan.png", "image/png", pipeline)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual([json.loads(call.content)["temperature"] for call in self.calls], [temperatures.get("ocr", 0), temperatures.get("extraction", 0)])

    def test_invalid_temperatures_do_not_call_upstream(self):
        for stage in ("ocr", "extraction"):
            for value in (-0.1, 2.1, "invalid"):
                with self.subTest(stage=stage, value=value):
                    pipeline = {"source": "scans", "ocr": {"provider": "litellm", "model": "vision"}, "extraction": {"mode": "prompt", "model": "extract"}}
                    pipeline[stage]["temperature"] = value
                    response = self.upload(b"image", "scan.png", "image/png", pipeline)
                    self.assertEqual(response.status_code, 400)
        self.assertEqual(self.calls, [])

    def test_ocr_service_and_failure(self):
        options = {"model_name": "deepseek-ai/DeepSeek-OCR", "force_ocr": "True"}
        pipeline = {"source": "scans", "ocr": {"provider": "service", "url": "http://ocr.test/recognize", "options": options}}
        response = self.upload(b"image", "scan.png", "image/png", pipeline)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "Распознанный текст")
        # Поля сервиса уходят в том же multipart-запросе, что и файл.
        body = self.calls[0].content.decode("utf-8", "replace")
        self.assertIn('name="model_name"', body)
        self.assertIn("deepseek-ai/DeepSeek-OCR", body)
        self.assertIn('name="force_ocr"', body)
        self.assertIn('name="file"; filename="scan.png"', body)
        self.fail_upstream = True
        failed = self.upload(b"image", "scan.png", "image/png", pipeline)
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(len(self.client.get("/api/documents").json()["documents"]), 1)
        self.assertEqual(len(list((self.storage / "originals").iterdir())), 1)

    def test_health_is_public_and_hides_configuration(self):
        # health открыт без входа, поэтому адреса LiteLLM и прокси в нём не раскрываются.
        health = TestClient(self.app).get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "ok", "backend": "fastapi-sqlalchemy"})
        blank = dict.fromkeys(("PROXY_URL", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"), "")
        with patch.dict("os.environ", {**blank, "PROXY_URL": "proxy.company.local:8080"}):
            app = self.make_app()
            with TestClient(app):
                self.assertEqual(app.state.proxy, "http://proxy.company.local:8080")

    def create_pipeline(self, name):
        response = self.client.post("/api/pipelines", json={"name": name, "source": "document", "extraction": None})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["pipeline"]["id"]

    @staticmethod
    def send_document(client, url, data=None):
        return client.post(url, files={"file": ("doc.txt", "Текст документа".encode(), "text/plain")}, data=data or {})

    def test_requests_without_credentials_are_rejected(self):
        anonymous = TestClient(self.app)
        for method, url in (("get", "/api/pipelines"), ("get", "/api/documents"), ("get", "/api/keys"), ("get", "/api/auth/session"), ("get", "/api/litellm/models")):
            with self.subTest(url=url):
                self.assertEqual(getattr(anonymous, method)(url).status_code, 401)
        self.assertEqual(self.send_document(anonymous, "/api/pipeline/run", {"pipeline": json.dumps({"source": "document"})}).status_code, 401)
        # Пароль администратора в заголовке не работает — там принимаются только ключи интеграций.
        for header in ("Bearer wrong-key", "Bearer " + ADMIN_PASSWORD, "Basic dXNlcjpwYXNz", "Bearer " + "x" * 600):
            with self.subTest(header=header[:20]):
                self.assertEqual(anonymous.get("/api/pipelines", headers={"Authorization": header}).status_code, 401)

    def test_admin_login_session_expiry_and_logout(self):
        browser = TestClient(self.app)
        for credentials in ({"login": ADMIN_LOGIN, "password": "wrong-password"}, {"login": "root", "password": ADMIN_PASSWORD}):
            with self.subTest(login=credentials["login"]):
                wrong = browser.post("/api/auth/login", json=credentials)
                # Одинаковый ответ: по нему не понять, что именно неверно.
                self.assertEqual((wrong.status_code, wrong.json()["error"]), (401, "Неверный логин или пароль"))
        login = browser.post("/api/auth/login", json={"login": f"  {ADMIN_LOGIN} ", "password": ADMIN_PASSWORD})
        self.assertEqual(login.status_code, 200, login.text)
        cookie = login.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        token = browser.cookies.get("ocr_admin_session")
        with self.app.state.sessions() as session:
            rows = session.scalars(select(AdminSession)).all()
            # В базе нет ни токена сессии, ни пароля в открытом виде.
            self.assertNotIn(token, [row.token_hash for row in rows])
            self.assertFalse(any(ADMIN_PASSWORD in row.admin_hash for row in rows))
        self.assertEqual(browser.get("/api/auth/session").json(), {"role": "admin"})
        self.assertEqual(browser.get("/api/documents").status_code, 200)
        with self.app.state.sessions.begin() as session:
            session.execute(update(AdminSession).values(expires_at=0))
        self.assertEqual(browser.get("/api/auth/session").status_code, 401)

        self.sign_in(browser)
        token = browser.cookies.get("ocr_admin_session")
        self.assertEqual(browser.post("/api/auth/logout").status_code, 200)
        # Старый cookie не оживает, даже если клиент пришлёт его снова.
        self.assertEqual(TestClient(self.app, cookies={"ocr_admin_session": token}).get("/api/auth/session").status_code, 401)

    def test_admin_password_is_generated_once_when_not_configured(self):
        storage = self.storage / "fresh"
        database = f"sqlite:///{(storage / 'fresh.sqlite3').as_posix()}"
        with patch.dict("os.environ", {"OCR_ADMIN_LOGIN": "", "OCR_ADMIN_PASSWORD": ""}):
            with TestClient(create_app(database, storage, httpx.MockTransport(self.upstream))) as first:
                password = (storage / "admin-password.txt").read_text(encoding="utf-8").strip()
                self.assertGreaterEqual(len(password), 16)
                self.assertEqual(first.post("/api/auth/login", json={"login": "admin", "password": password}).status_code, 200)
            with TestClient(create_app(database, storage, httpx.MockTransport(self.upstream))) as second:
                self.assertEqual(second.post("/api/auth/login", json={"login": "admin", "password": password}).status_code, 200)
            self.assertEqual((storage / "admin-password.txt").read_text(encoding="utf-8").strip(), password)
        with patch.dict("os.environ", {"OCR_ADMIN_PASSWORD": "short"}), self.assertRaisesRegex(RuntimeError, "OCR_ADMIN_PASSWORD"):
            with TestClient(self.make_app()):
                pass

    def test_changing_admin_password_ends_sessions(self):
        token = self.client.cookies.get("ocr_admin_session")
        with TestClient(self.make_app(), cookies={"ocr_admin_session": token}) as same_password:
            self.assertEqual(same_password.get("/api/auth/session").status_code, 200)
        with patch.dict("os.environ", {"OCR_ADMIN_PASSWORD": "another-password-456"}), TestClient(self.make_app(), cookies={"ocr_admin_session": token}) as changed:
            self.assertEqual(changed.get("/api/auth/session").status_code, 401)
            self.assertEqual(changed.post("/api/auth/login", json=ADMIN_CREDENTIALS).status_code, 401)
            self.assertEqual(changed.post("/api/auth/login", json={"login": ADMIN_LOGIN, "password": "another-password-456"}).status_code, 200)

    def test_repeated_failed_logins_are_throttled(self):
        browser = TestClient(self.app)
        wrong = {"login": ADMIN_LOGIN, "password": "wrong-password"}
        for _ in range(MAX_FAILED_LOGINS):
            self.assertEqual(browser.post("/api/auth/login", json=wrong).status_code, 401)
        locked = browser.post("/api/auth/login", json=ADMIN_CREDENTIALS)
        self.assertEqual(locked.status_code, 429)
        self.assertIn("Повторите через 10 мин", locked.json()["error"])
        # Окно прошло — верный пароль снова работает, а счётчик сбрасывается.
        throttle = self.app.state.login_throttle
        throttle.failures = deque(moment - FAILED_LOGIN_WINDOW for moment in throttle.failures)
        self.assertEqual(browser.post("/api/auth/login", json=ADMIN_CREDENTIALS).status_code, 200)
        self.assertEqual(len(throttle.failures), 0)

    def test_integration_key_is_limited_to_assigned_pipelines(self):
        allowed = self.create_pipeline("Счета")
        hidden = self.create_pipeline("Договоры")
        created = self.client.post("/api/keys", json={"name": "1С", "pipeline_ids": [allowed]})
        self.assertEqual(created.status_code, 201, created.text)
        token = created.json()["token"]
        self.assertTrue(token.startswith("ocr_"))
        listed = self.client.get("/api/keys").json()["keys"]
        self.assertEqual([(key["name"], key["pipeline_ids"], key["prefix"]) for key in listed], [("1С", [allowed], token[:12])])
        # Ключ показывается один раз: ни список, ни база его не содержат.
        self.assertNotIn(token, json.dumps(listed))
        with self.app.state.sessions() as session:
            self.assertNotIn(token, session.scalars(select(APIKey.token_hash)).all())

        integration = TestClient(self.app, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual([pipeline["id"] for pipeline in integration.get("/api/pipelines").json()["pipelines"]], [allowed])
        by_path = self.send_document(integration, f"/api/pipelines/{allowed}/run")
        self.assertEqual(by_path.status_code, 200, by_path.text)
        self.assertEqual(by_path.json()["text"], "Текст документа")
        self.assertEqual(self.send_document(integration, "/api/pipeline/run", {"pipeline_id": allowed}).status_code, 200)
        self.assertEqual(self.send_document(integration, f"/api/pipelines/{hidden}/run").status_code, 403)
        self.assertEqual(self.send_document(integration, "/api/pipeline/run", {"pipeline_id": hidden}).status_code, 403)
        self.assertEqual(self.send_document(integration, "/api/pipeline/run", {"pipeline": json.dumps({"source": "document"})}).status_code, 403)
        for method, url in (("get", "/api/documents"), ("get", "/api/keys"), ("post", "/api/keys"), ("get", "/api/auth/session"), ("post", "/api/pipelines"), ("delete", f"/api/pipelines/{allowed}"), ("get", "/api/litellm/models")):
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(integration, method)(url).status_code, 403)
        self.assertEqual(TestClient(self.app).post("/api/auth/login", json={"login": ADMIN_LOGIN, "password": token}).status_code, 401)

    def test_key_access_can_be_changed_and_revoked(self):
        first = self.create_pipeline("Первый")
        second = self.create_pipeline("Второй")
        created = self.client.post("/api/keys", json={"name": "CRM", "pipeline_ids": [first]}).json()
        key_id = created["key"]["id"]
        integration = TestClient(self.app, headers={"Authorization": "Bearer " + created["token"]})

        updated = self.client.patch(f"/api/keys/{key_id}", json={"name": "CRM 2", "pipeline_ids": [second, second]})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual((updated.json()["key"]["name"], updated.json()["key"]["pipeline_ids"]), ("CRM 2", [second]))
        self.assertEqual(self.send_document(integration, f"/api/pipelines/{first}/run").status_code, 403)
        self.assertEqual(self.send_document(integration, f"/api/pipelines/{second}/run").status_code, 200)

        self.client.delete(f"/api/pipelines/{first}")
        for ids in ([first], ["pl_missing"], []):
            with self.subTest(ids=ids):
                self.assertEqual(self.client.patch(f"/api/keys/{key_id}", json={"name": "CRM", "pipeline_ids": ids}).status_code, 422)
                self.assertEqual(self.client.post("/api/keys", json={"name": "Новый", "pipeline_ids": ids}).status_code, 422)
        self.assertEqual(self.client.post("/api/keys", json={"name": "   ", "pipeline_ids": [second]}).status_code, 422)

        # Удалённый пайплайн пропадает у ключа, не ломая его.
        self.client.delete(f"/api/pipelines/{second}")
        self.assertEqual(integration.get("/api/pipelines").json()["pipelines"], [])
        self.assertEqual(self.send_document(integration, f"/api/pipelines/{second}/run").status_code, 404)

        self.assertEqual(self.client.delete(f"/api/keys/{key_id}").status_code, 200)
        self.assertEqual(integration.get("/api/pipelines").status_code, 401)
        self.assertEqual(self.client.delete(f"/api/keys/{key_id}").status_code, 200)
        self.assertEqual(self.client.patch(f"/api/keys/{key_id}", json={"name": "CRM", "pipeline_ids": [second]}).status_code, 404)
        self.assertEqual(self.client.delete("/api/keys/missing").status_code, 404)
        self.assertIsNotNone(self.client.get("/api/keys").json()["keys"][0]["revoked_at"])

    def test_models_and_chat(self):
        self.assertEqual(self.client.get("/api/litellm/models").json()["models"], ["extract", "vision"])
        chat = self.client.post("/api/litellm/chat", json={"model": "extract", "prompt": "Извлеки сумму", "documentText": "1500"})
        self.assertEqual(chat.status_code, 200)
        self.assertIn("1500", chat.json()["result"])

    def test_validation_and_missing_documents(self):
        self.assertEqual(self.client.get("/api/documents/missing").status_code, 404)
        self.assertEqual(self.client.get("/api/documents/missing/original").status_code, 404)
        self.assertEqual(self.client.patch("/api/documents/missing", json={"fields": [], "revision": 0}).status_code, 422)
        self.assertEqual(self.client.patch("/api/documents/missing", json={"fields": {}, "revision": 0}).status_code, 404)
        bad = self.client.post("/api/pipeline/run", files={"file": ("x.txt", b"test")}, data={"pipeline": "invalid"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.upload(b"a" * (MAX_FILE_SIZE + 1)).status_code, 413)
        self.assertEqual(self.client.get("/api/documents").json()["documents"], [])

    def test_safe_download_and_range(self):
        response = self.upload(b"<script>alert(1)</script>", "../../danger.html", "text/html")
        document_id = response.json()["documentId"]
        source = self.client.get(f"/api/documents/{document_id}/original")
        self.assertIn("attachment", source.headers["content-disposition"])
        self.assertEqual(source.headers["x-content-type-options"], "nosniff")
        self.assertEqual(list((self.storage / "originals").iterdir())[0].name, document_id)
        partial = self.client.get(f"/api/documents/{document_id}/original", headers={"Range": "bytes=0-6"})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.content, b"<script")

    def test_docx_text(self):
        from docx import Document
        doc = Document()
        doc.add_paragraph("Договор номер 15")
        buf = io.BytesIO()
        doc.save(buf)
        response = self.upload(buf.getvalue(), "contract.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Договор номер 15", response.json()["text"])


class ProxyTests(unittest.TestCase):
    def setUp(self):
        blank = dict.fromkeys(("PROXY_URL", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY"), "")
        self.environment = patch.dict("os.environ", blank)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_bare_address_gets_a_scheme_and_wins_over_the_environment(self):
        os.environ["HTTP_PROXY"] = "old.local:3128"
        os.environ["PROXY_URL"] = "proxy.company.local:8080"
        self.assertEqual(proxy_options(), "http://proxy.company.local:8080")
        self.assertEqual(os.environ["HTTP_PROXY"], "http://proxy.company.local:8080")
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://proxy.company.local:8080")

    def test_environment_proxy_stays_the_fallback(self):
        os.environ["HTTPS_PROXY"] = "old.local:3128"
        self.assertIsNone(proxy_options())
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://old.local:3128")

    def test_unsupported_scheme_is_ignored(self):
        os.environ["PROXY_URL"] = "ftp://proxy.company.local:21"
        with self.assertLogs("ocr", level="WARNING"):
            self.assertIsNone(proxy_options())
        self.assertEqual(os.environ["HTTP_PROXY"], "")

    def test_ocr_service_requests_are_routed_through_the_proxy(self):
        os.environ["PROXY_URL"] = "proxy.company.local:8080"
        os.environ["NO_PROXY"] = "127.0.0.1"
        proxy_options()
        with httpx.Client() as client:
            routed = client._transport_for_url(httpx.URL("https://ocr.example.com/recognize"))
            excluded = client._transport_for_url(httpx.URL("http://127.0.0.1:8000/recognize"))
        self.assertEqual((routed._pool._proxy_url.host, routed._pool._proxy_url.port), (b"proxy.company.local", 8080))
        self.assertFalse(hasattr(excluded._pool, "_proxy_url"))


if __name__ == "__main__":
    unittest.main()
