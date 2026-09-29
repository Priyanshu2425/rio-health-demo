"""Thin OpenRouter client. Every LLM call in Rio goes through `complete_json`."""

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import get_settings


class LLMError(Exception):
    """The provider failed, timed out, or returned something that is not the schema."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    latency_ms: int
    cost_usd: float | None


def image_part(image: bytes, mime: str) -> dict[str, Any]:
    encoded = base64.b64encode(image).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


async def complete_json(
    model: str,
    messages: list[dict[str, Any]],
    schema: type[BaseModel],
    *,
    temperature: float = 0.0,
    strict: bool = False,
) -> LLMResult:
    """Call `model` and return JSON that validates against `schema`.

    `strict=True` asks the provider to enforce the schema, but only works when every
    property is required and `additionalProperties` is false; the response is validated
    against `schema` either way. Raises LLMError on HTTP errors, timeouts, or a response
    that does not validate.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    if not model:
        raise LLMError("model id is empty; set VISION_MODEL / RERANK_MODEL")

    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "strict": strict, "schema": schema.model_json_schema()},
        },
        "usage": {"include": True},
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": "https://rio.buildspacelabs.com",
        "X-Title": "Rio demo",
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.openrouter_timeout_s) as client:
            resp = await client.post(
                f"{settings.openrouter_base_url}/chat/completions", json=body, headers=headers
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"openrouter request failed: {exc}") from exc
    latency_ms = int((time.perf_counter() - started) * 1000)

    payload = resp.json()
    try:
        content = payload["choices"][0]["message"]["content"]
        data = schema.model_validate(json.loads(content)).model_dump(mode="json")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMError(f"response did not match {schema.__name__}: {exc}") from exc

    usage = payload.get("usage") or {}
    return LLMResult(
        data=data, model=payload.get("model", model), latency_ms=latency_ms, cost_usd=usage.get("cost")
    )
