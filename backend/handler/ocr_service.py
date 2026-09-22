"""Внешний OCR-сервис: файл уходит формой, текст приходит в теле ответа."""

from ..core.errors import InvalidDocument, UpstreamError

TEXT_KEYS = ("page_content", "text", "result")


async def read_text(client, ocr, content, filename, mime):
    if not ocr.url:
        raise InvalidDocument("Укажите URL OCR-сервиса")
    response = await client.post(str(ocr.url), files={"file": (filename, content, mime)}, data=ocr.options or None)
    if not response.is_success:
        raise UpstreamError.from_status(f"OCR-сервис вернул HTTP {response.status_code}", response.status_code)
    try:
        payload = response.json()
    except ValueError:
        return response.text
    text = next((payload[key] for key in TEXT_KEYS if key in payload), response.text) if isinstance(payload, dict) else response.text
    if not isinstance(text, str):
        raise UpstreamError("OCR-сервис должен вернуть текст в поле page_content, text или result")
    return text
