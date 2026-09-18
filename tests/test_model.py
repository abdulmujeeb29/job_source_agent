import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.providers import Astra
from app.schemas import DiscoveryError
from tests.test_verification import evidence


async def configured_model(settings, handler):
    model = Astra(settings)
    await model.client.close()
    model.client = AsyncOpenAI(api_key="fixture", base_url=settings.model_base_url,
                              max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return model


def response(text):
    return httpx.Response(200, json={
        "id": "resp_test", "object": "response", "created_at": 0, "status": "completed",
        "model": "gpt-6-astra", "output": [{"id": "msg_test", "type": "message", "role": "assistant",
        "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": {"input_tokens": 20, "output_tokens": 30, "total_tokens": 50},
    })


async def test_azure_v1_schema_and_malformed_response_recovery(settings):
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        assert request.url.path == "/openai/v1/responses"
        return response("not-json" if len(calls) == 1 else evidence()[2].model_dump_json())
    model = await configured_model(settings, handler)
    try:
        decision = await model.decide({"observation": "fixture"})
        assert decision.action == "verify"
        assert model.usage == {"requests": 2, "input_tokens": 40, "output_tokens": 60}
        assert calls[0]["store"] is False
        schema = calls[0]["text"]["format"]["schema"]
        assert schema["additionalProperties"] is False
        assert schema["$defs"]["ListingSample"]["additionalProperties"] is False
    finally:
        await model.close()


async def test_azure_401_is_not_retried(settings):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": "Unauthorized", "type": "authentication_error"}})
    model = await configured_model(settings, handler)
    try:
        with pytest.raises(DiscoveryError, match="HTTP 401"):
            await model.decide({})
        assert len(calls) == 1
    finally:
        await model.close()


async def test_model_budget_includes_retry_requests(settings):
    settings.max_model_calls = 1
    model = await configured_model(settings, lambda _: response("invalid"))
    try:
        with pytest.raises(DiscoveryError) as exc:
            await model.decide({})
        assert exc.value.code == "model_budget"
        assert model.calls == 1
    finally:
        await model.close()
