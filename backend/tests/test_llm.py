import json

import httpx
import pytest
from pydantic import BaseModel

from app.core import llm
from app.core.config import get_settings


class Answer(BaseModel):
    ok: bool


def _fake_openrouter(monkeypatch, body: dict) -> list[dict]:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        llm.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    get_settings.cache_clear()
    return sent


@pytest.fixture(autouse=True)
def _fresh_settings():
    yield
    get_settings.cache_clear()


async def test_sends_default_max_tokens_and_parses(monkeypatch):
    sent = _fake_openrouter(
        monkeypatch,
        {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}],
            "usage": {"cost": 0.001},
        },
    )
    result = await llm.complete_json("m", [], Answer)
    assert result.data == {"ok": True}
    assert sent[0]["max_tokens"] == get_settings().openrouter_max_tokens


async def test_truncated_output_says_so(monkeypatch):
    _fake_openrouter(
        monkeypatch, {"choices": [{"finish_reason": "length", "message": {"content": '{"ok": tr'}}]}
    )
    with pytest.raises(llm.LLMError, match="max_tokens"):
        await llm.complete_json("m", [], Answer, max_tokens=10)
