from types import SimpleNamespace
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import Settings
from .common import LlmProviderError, api_key, messages, parse_json, portable_schema, post_json, usage

T = TypeVar("T", bound=BaseModel)


async def parse_anthropic(config: Settings, instructions: str, input_value: str | list[dict], text_format: type[T]) -> SimpleNamespace:
    if not api_key(config):
        raise LlmProviderError("Anthropic API 키가 설정되지 않았습니다.")
    request_messages = messages(instructions, input_value)
    system = str(request_messages.pop(0)["content"])
    body = await post_json(
        config.openai_base_url or "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key(config), "anthropic-version": "2023-06-01", "content-type": "application/json"},
        payload={
            "model": config.openai_model,
            "max_tokens": config.llm_max_output_tokens,
            "system": system,
            "messages": request_messages,
            "output_config": {"format": {"type": "json_schema", "schema": portable_schema(text_format)}},
        },
        provider="Anthropic",
    )
    stop_reason = body.get("stop_reason")
    if stop_reason in {"refusal", "max_tokens"}:
        reason = "요청을 거절했습니다" if stop_reason == "refusal" else "출력 한도에 도달했습니다. 설정에서 최대 출력 토큰을 늘리세요"
        raise LlmProviderError(f"Anthropic이 {reason}.")
    text = "\n".join(item.get("text", "") for item in body.get("content", []) if item.get("type") == "text")
    raw_usage = body.get("usage", {})
    return SimpleNamespace(output_parsed=parse_json(text, text_format, "Anthropic"), usage=usage(raw_usage.get("input_tokens", 0), raw_usage.get("output_tokens", 0)))
