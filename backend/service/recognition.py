"""Оркестрация обработки документа: распознавание и извлечение полей.

Слой решает, какой обработчик вызвать, и не знает ни про HTTP-слой приложения,
ни про базу. Обращения к LiteLLM идут через модуль, а не через импорт функции,
чтобы у шлюза моделей оставался один шов для подмены в тестах.
"""

import base64

import anyio.to_thread

from ..core.errors import InvalidDocument
from ..handler import litellm, ocr_service
from ..handler.documents import digital_text
from ..schema.pipeline import fields_schema
from .validation import validate_extracted_fields

FIELDS_INSTRUCTION = (
    "\nИзвлеки значения полей документа согласно JSON Schema. Соблюдай типы данных и вложенную структуру. "
    "Верни все заданные поля. Если значение не найдено, верни null; для явно пустого списка — []. "
    "Не придумывай отсутствующие данные."
)


async def read_document(content, filename, mime):
    return await anyio.to_thread.run_sync(digital_text, content, filename, mime)


async def recognize(client, pipeline, content, filename, mime):
    if pipeline.source == "document":
        return await read_document(content, filename, mime)
    ocr = pipeline.ocr
    if ocr is None:
        raise InvalidDocument("Выберите способ распознавания сканов")
    if not ocr.enabled:
        return await read_document(content, filename, mime)
    if ocr.provider == "service":
        return await ocr_service.read_text(client, ocr, content, filename, mime)
    if not ocr.model:
        raise InvalidDocument("Выберите vision-модель")
    return await litellm.complete(client, {
        "model": ocr.model, "temperature": ocr.temperature, "max_tokens": 4096,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": ocr.prompt or "Распознай весь текст на изображении."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"}},
        ]}],
    })


async def extract(client, extraction, text, on_validation=None):
    if not extraction.active:
        return text
    structured = extraction.use_fields
    schema = fields_schema(extraction.fields)
    instruction = extraction.prompt if extraction.use_prompt else ""
    if structured:
        instruction += FIELDS_INSTRUCTION
    result = await litellm.complete(client, {
        "model": extraction.model, "temperature": extraction.temperature, "max_tokens": extraction.max_tokens,
        **({"response_format": {"type": "json_schema", "json_schema": {"name": "document_fields", "strict": True, "schema": schema}}} if structured else {}),
        "messages": [
            {"role": "system", "content": f"{instruction}\n" + ("Отвечай только валидным JSON без пояснений." if structured else "Верни ответ единым текстом. Не создавай JSON-объект и именованные поля результата.")},
            {"role": "user", "content": text},
        ],
    })
    if structured:
        if on_validation:
            on_validation()
        validate_extracted_fields(result, schema)
    return result
