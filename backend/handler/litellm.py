"""Клиент LiteLLM — единственное место, где приложение ходит в шлюз моделей."""

import os

from ..core.errors import ConfigurationError, UpstreamError


def litellm_config():
    base = os.getenv("LITELLM_BASE_URL", "").rstrip("/")
    if not base:
        raise ConfigurationError("LITELLM_BASE_URL не настроен в .env")
    if not base.startswith(("http://", "https://")):
        raise ConfigurationError("LITELLM_BASE_URL должен начинаться с http:// или https://")
    key = os.getenv("LITELLM_API_KEY")
    return base, {"Authorization": f"Bearer {key}"} if key else {}


def api_url(base, path):
    return f"{base}{'' if base.endswith('/v1') else '/v1'}/{path}"


async def complete(client, body: dict):
    base, headers = litellm_config()
    response = await client.post(api_url(base, "chat/completions"), headers=headers, json=body)
    structured = body.get("response_format", {}).get("type") == "json_schema"
    if not response.is_success:
        if structured and response.status_code in {400, 422}:
            raise UpstreamError(f"LiteLLM отклонил Structured Output (HTTP {response.status_code}). Проверьте поддержку json_schema выбранной моделью и настройки LiteLLM.")
        raise UpstreamError.from_status(f"LiteLLM вернул HTTP {response.status_code}. Проверьте модель и доступ к сервису.", response.status_code)
    try:
        choice = response.json()["choices"][0]
        message = choice["message"]
        if structured:
            if message.get("refusal"):
                raise UpstreamError("Модель отказалась извлекать поля документа")
            if choice.get("finish_reason") != "stop":
                raise UpstreamError("Модель не завершила Structured Output. Проверьте лимит max_tokens и ответ модели.")
        result = message["content"]
        if not isinstance(result, str):
            raise ValueError("Not text")
        return result
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise UpstreamError("LiteLLM вернул некорректный ответ") from error
