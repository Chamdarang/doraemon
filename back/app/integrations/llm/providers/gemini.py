from types import SimpleNamespace
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import Settings
from .common import LlmProviderError, api_key, parse_json, portable_schema, post_json, usage

T = TypeVar("T", bound=BaseModel)


def _response_text(body: dict[str, Any]) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    for step in reversed(body.get("steps", [])):
        for item in reversed(step.get("content", [])):
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                return item["text"]
    raise LlmProviderError("Gemini 응답에 결과 본문이 없습니다.")


async def parse_gemini(config: Settings, instructions: str, input_value: str | list[dict], text_format: type[T]) -> SimpleNamespace:
    if not api_key(config):
        raise LlmProviderError("Gemini API 키가 설정되지 않았습니다.")
    base = (config.openai_base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    if base.endswith("/openai"):
        base = base[:-7]
    body = await post_json(
        base if base.endswith("/interactions") else f"{base}/interactions",
        headers={"x-goog-api-key": api_key(config), "content-type": "application/json"},
        payload={"model": config.openai_model, "input": f"[system]\n{instructions}\n\n[user]\n{input_value}", "response_format": {"type": "text", "mime_type": "application/json", "schema": portable_schema(text_format)}},
        provider="Gemini",
    )
    if body.get("status") in {"failed", "cancelled", "incomplete", "budget_exceeded"}:
        raise LlmProviderError(f"Gemini 작업이 완료되지 않았습니다: {body.get('status')}")
    raw_usage = body.get("usage", {})
    total = int(raw_usage.get("total_tokens", 0) or 0)
    output = int(raw_usage.get("output_tokens", raw_usage.get("output_token_count", 0)) or 0)
    return SimpleNamespace(output_parsed=parse_json(_response_text(body), text_format, "Gemini"), usage=usage(max(0, total - output), output))
