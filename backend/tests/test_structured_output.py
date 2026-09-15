import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from backend.processing import Extraction, extract


class StructuredOutputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        env = patch.dict("os.environ", {"LITELLM_BASE_URL": "http://litellm.test/v1", "LITELLM_API_KEY": "test-key"})
        env.start()
        self.addCleanup(env.stop)
        self.extraction = Extraction(mode="fields", model="extract", fields=[
            {"name": "total", "description": "Сумма документа"},
            {"name": "invoice/date", "description": "Дата счёта"},
        ])
        self.requests = []

    async def request(self, content, finish_reason="stop", refusal=None, status=200):
        def upstream(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(status, json={"choices": [{"finish_reason": finish_reason, "message": {"content": content, "refusal": refusal}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream), trust_env=False) as client:
            return await extract(client, self.extraction, "Счёт на 1500")

    async def test_schema_and_null_for_absent_values(self):
        content = '{"total": "1500", "invoice/date": null}'
        self.assertEqual(await self.request(content), content)
        fmt = self.requests[0]["response_format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertIs(fmt["json_schema"]["strict"], True)
        schema = fmt["json_schema"]["schema"]
        self.assertEqual(schema["required"], ["total", "invoice/date"])
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["total"], {"type": ["string", "null"], "description": "Сумма документа"})

    async def test_prompt_and_fields_share_one_structured_request(self):
        self.extraction.prompt_enabled = True
        self.extraction.fields_enabled = True
        self.extraction.prompt = "Use the final total including VAT"
        await self.request('{"total":"1500","invoice/date":null}')
        self.assertEqual(len(self.requests), 1)
        self.assertIn(self.extraction.prompt, self.requests[0]["messages"][0]["content"])
        self.assertEqual(self.requests[0]["response_format"]["type"], "json_schema")

    async def test_disabled_prompt_is_not_sent_with_fields(self):
        self.extraction.prompt_enabled = False
        self.extraction.prompt = "DISABLED INSTRUCTION"
        await self.request('{"total":"1500","invoice/date":null}')
        self.assertNotIn(self.extraction.prompt, self.requests[0]["messages"][0]["content"])

    async def test_prompt_only_returns_free_text_and_ignores_saved_fields(self):
        self.extraction = Extraction(model="extract", prompt_enabled=True, fields_enabled=False, prompt="Return the document text", fields=[{"name":"saved"}])
        self.assertEqual(await self.request("Document text"), "Document text")
        self.assertNotIn("response_format", self.requests[0])
        self.assertEqual(self.extraction.mode, "prompt")

    async def test_both_disabled_skip_model_and_preserve_configuration(self):
        self.extraction = Extraction(prompt_enabled=False, fields_enabled=False, prompt="Saved prompt", fields=[{"name":""}])
        self.assertEqual(await self.request("Not used"), "Счёт на 1500")
        self.assertEqual(self.requests, [])
        self.assertEqual(self.extraction.prompt, "Saved prompt")

    async def test_explicit_enabled_prompt_requires_instruction(self):
        with self.assertRaises(ValidationError):
            Extraction(model="extract", prompt_enabled=True, fields_enabled=False)

    async def test_rejects_invalid_json_fields_and_types(self):
        for content in (
            'not json', '[]', 'null', '{}', '{"total":"1500"}',
            '{"total":"1500","invoice/date":null,"extra":"x"}',
            '{"total":1500,"invoice/date":null}',
            '{"total":false,"invoice/date":null}',
            '{"total":{},"invoice/date":null}',
            '{"total":[],"invoice/date":null}',
            '{"total":NaN,"invoice/date":null}',
            '{"total":"first","total":"second","invoice/date":null}',
        ):
            with self.subTest(content=content), self.assertRaises(HTTPException) as raised:
                await self.request(content)
            self.assertEqual(raised.exception.status_code, 502)

    async def test_rejects_refusal_and_truncated_or_filtered_answers(self):
        for reason, refusal in (("length", None), ("content_filter", None), (None, None), ("stop", "refused")):
            with self.subTest(reason=reason, refusal=refusal), self.assertRaises(HTTPException) as raised:
                await self.request('{"total":"1500","invoice/date":null}', reason, refusal)
            self.assertEqual(raised.exception.status_code, 502)

    async def test_no_fallback_when_model_rejects_structured_output(self):
        with self.assertRaises(HTTPException) as raised:
            await self.request(None, status=400)
        self.assertIn("Structured Output", raised.exception.detail)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]["response_format"]["type"], "json_schema")

    async def test_prompt_mode_preserves_free_text(self):
        self.extraction = Extraction(mode="prompt", model="extract", prompt="Опиши документ")
        self.assertEqual(await self.request("Описание.\n\nВторой абзац."), "Описание.\n\nВторой абзац.")
        self.assertNotIn("response_format", self.requests[0])

    def test_empty_and_duplicate_field_names_are_rejected(self):
        for fields in ([], [{"name": " "}], [{"name": "total"}, {"name": "total"}]):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                Extraction(mode="fields", model="extract", fields=fields)
