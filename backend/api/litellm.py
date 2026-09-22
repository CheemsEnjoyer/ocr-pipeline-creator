import json
from fastapi import APIRouter, Depends, HTTPException
from .policies import admin_only
from ..handler import litellm as gateway
from ..schema.api import ChatRequest


def create_router(app, storage):
    router = APIRouter(tags=["LiteLLM Models"])
    @router.get("/api/litellm/models", dependencies=[Depends(admin_only)])
    async def models():
        base, headers = gateway.litellm_config()
        response = await app.state.client.get(gateway.api_url(base, "models"), headers=headers)
        if not response.is_success:
            raise HTTPException(503, f"LiteLLM вернул HTTP {response.status_code}")
        try:
            names = {item["id"] for item in response.json().get("data", []) if isinstance(item.get("id"), str)}
            return {"models": sorted(names)}
        except (ValueError, TypeError, AttributeError) as error:
            raise HTTPException(502, "LiteLLM вернул некорректный список моделей") from error

    @router.post("/api/litellm/chat", dependencies=[Depends(admin_only)])
    async def chat(payload: ChatRequest):
        schema = {field.get("name", ""): {"type": "string", "description": field.get("description", "")} for field in payload.fields}
        result = await gateway.complete(app.state.client, {
            "model": payload.model, "temperature": 0, "max_tokens": payload.maxTokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f"{payload.prompt}\nВерни JSON с полями по схеме: {json.dumps(schema, ensure_ascii=False)}"},
                {"role": "user", "content": payload.documentText or "Текст документа появится после этапа OCR/извлечения."},
            ],
        })
        return {"model": payload.model, "result": result}

    return router
