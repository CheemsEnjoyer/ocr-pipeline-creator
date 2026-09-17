import logging
import unittest
from unittest.mock import patch

from backend.config import JobSettings
from backend.security import SecretFilter, safe_url


class SecurityTests(unittest.TestCase):
    def test_oidc_codes_and_session_keys_are_redacted(self):
        from backend.security import redact
        with patch.dict("os.environ", {"KEYCLOAK_SESSION_KEY": "private-encryption-key"}):
            message = redact('GET /api/auth/keycloak/callback?state=private-state&code=private-code HTTP/1.1 private-encryption-key')
        for secret in ("private-state", "private-code", "private-encryption-key"):
            self.assertNotIn(secret, message)
        from uvicorn.logging import AccessFormatter
        record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1", "GET", "/api/auth/keycloak/callback?code=private-code", "1.1", 302), None)
        SecretFilter().filter(record)
        self.assertNotIn("private-code", AccessFormatter().format(record))

    def test_urls_hide_credentials_queries_and_fragments(self):
        self.assertEqual(safe_url("http://user:password@proxy.local:8080/path?token=secret#secret"), "http://proxy.local:8080/path")
        self.assertEqual(safe_url("https://[::1]:9000/path?X-Amz-Signature=secret"), "https://[::1]:9000/path")
        self.assertEqual(safe_url("bad URL user:password"), "[адрес скрыт]")

    def test_log_messages_and_tracebacks_hide_secrets(self):
        secret = "private-api-key-123"
        with patch.dict("os.environ", {"LITELLM_API_KEY": secret}):
            try:
                raise RuntimeError("https://user:password@host/path?token=secret " + secret)
            except RuntimeError:
                import sys
                record = logging.LogRecord("ocr", logging.ERROR, __file__, 1, "Request failed: %s", (secret,), sys.exc_info())
            SecretFilter().filter(record)
            output = logging.Formatter().format(record)
        for value in (secret, "user:password", "token=secret"):
            self.assertNotIn(value, output)

    def test_task_limits_are_validated(self):
        with patch.dict("os.environ", {"OCR_TASK_SOFT_LIMIT_SECONDS": "300", "OCR_TASK_HARD_LIMIT_SECONDS": "200"}):
            with self.assertRaises(RuntimeError):
                JobSettings.from_env()
        with patch.dict("os.environ", {"OCR_GLOBAL_SYNC_LIMIT": "3", "OCR_CLIENT_SYNC_LIMIT": "4"}):
            with self.assertRaises(RuntimeError):
                JobSettings.from_env()
        with patch.dict("os.environ", {}, clear=True):
            settings = JobSettings.from_env()
        self.assertEqual((settings.sync_global_limit, settings.sync_client_limit), (10, 4))
