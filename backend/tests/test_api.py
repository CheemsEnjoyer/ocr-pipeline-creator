import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from backend.main import MAX_FILE_SIZE, create_app
from backend.processing import proxy_options


class APITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.storage = Path(self.temporary.name)
        self.database_url = f"sqlite:///{(self.storage / 'test.sqlite3').as_posix()}"
        self.calls = []
        self.fail_upstream = False
        self.refuse_upstream = False
        self.environment = patch.dict("os.environ", {"LITELLM_BASE_URL": "http://litellm.test/v1", "LITELLM_API_KEY": "test-key"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.app = self.make_app()
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

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

    def upload(self, content=b'{"total": 1250}', filename="test.json", mime="application/json", pipeline=None):
        return self.client.post("/api/pipeline/run", files={"file": (filename, content, mime)}, data={"pipeline": json.dumps(pipeline or {"source": "document", "name": "Тест"})})

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
        with TestClient(self.make_app()) as restarted:
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

    def test_ocr_service_catalog_comes_from_the_environment(self):
        with patch.dict("os.environ", {"OCR_SERVICE_URL": ""}):
            self.assertEqual(self.client.get("/api/ocr/services").json()["services"], [])
        with patch.dict("os.environ", {"OCR_SERVICE_URL": "http://10.128.34.34:8003/"}):
            service = self.client.get("/api/ocr/services").json()["services"][0]
        self.assertEqual(service["url"], "http://10.128.34.34:8003/api/v1/ocr/openai/file/process")
        self.assertEqual(service["options"], {"model_name": "deepseek-ai/DeepSeek-OCR", "force_ocr": "True"})
        # Полный адрес с путём принимается как есть, некорректный — отбрасывается.
        with patch.dict("os.environ", {"OCR_SERVICE_URL": "http://ocr.test/custom/endpoint"}):
            self.assertEqual(self.client.get("/api/ocr/services").json()["services"][0]["url"], "http://ocr.test/custom/endpoint")
        with patch.dict("os.environ", {"OCR_SERVICE_URL": "10.128.34.34:8003"}), self.assertLogs("ocr", level="WARNING"):
            self.assertEqual(self.client.get("/api/ocr/services").json()["services"], [])

    def test_unreachable_upstream_names_the_address(self):
        self.refuse_upstream = True
        response = self.client.get("/api/litellm/models")
        self.assertEqual(response.status_code, 502)
        # Именно этого не хватало при отладке: в тексте виден адрес, до которого не дошёл запрос.
        self.assertIn("http://litellm.test/v1/models", response.json()["error"])
        self.assertNotIn("Запросы идут через прокси", response.json()["error"])
        with patch.dict("os.environ", {"PROXY_URL": "proxy.company.local:8080"}), TestClient(self.make_app()) as proxied:
            proxied_error = proxied.get("/api/litellm/models").json()["error"]
        self.assertIn("http://proxy.company.local:8080", proxied_error)
        self.assertIn("NO_PROXY", proxied_error)

    def test_health_reports_the_configured_proxy(self):
        blank = dict.fromkeys(("PROXY_URL", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"), "")
        with patch.dict("os.environ", blank), TestClient(self.make_app()) as plain:
            self.assertIsNone(plain.get("/api/health").json()["proxy"])
        with patch.dict("os.environ", {**blank, "PROXY_URL": "proxy.company.local:8080"}), TestClient(self.make_app()) as proxied:
            self.assertEqual(proxied.get("/api/health").json()["proxy"], "http://proxy.company.local:8080")
        health = self.client.get("/api/health").json()
        self.assertEqual(health["litellm"], "http://litellm.test/v1")
        self.assertNotIn("test-key", json.dumps(health))

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
