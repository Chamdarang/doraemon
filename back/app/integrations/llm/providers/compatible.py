from types import SimpleNamespace
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import Settings
from .common import LlmProviderError, api_key, messages, parse_json, portable_schema, post_json, usage

T = TypeVar("T", bound=BaseModel)


def _chat_text(body: dict[str, Any], provider: str) -> str:
    try:
        message = body["choices"][0]["message"]
        if message.get("refusal"):
            raise LlmProviderError(f"{provider}가 요청을 거절했습니다: {message['refusal']}")
        content = message["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text = "\n".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            )
            if text:
                return text
        raise TypeError("message content is not text")
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmProviderError(f"{provider} 응답에 결과 본문이 없습니다.") from exc


async def parse_compatible(config: Settings, instructions: str, input_value: str | list[dict], text_format: type[T]) -> SimpleNamespace:
    provider = {"openrouter": "OpenRouter", "ollama": "Ollama", "custom": "사용자 지정 API"}.get(config.llm_provider, config.llm_provider)
    if config.llm_provider != "ollama" and not api_key(config):
        raise LlmProviderError(f"{provider} API 키가 설정되지 않았습니다.")
    base = (config.openai_base_url or "").rstrip("/")
    if not base:
        raise LlmProviderError(f"{provider} API 주소가 설정되지 않았습니다.")
    headers = {"content-type": "application/json"}
    if api_key(config):
        headers["authorization"] = f"Bearer {api_key(config)}"
    payload: dict[str, Any] = {
        "model": config.openai_model,
        "messages": messages(instructions, input_value),
        "response_format": {"type": "json_schema", "json_schema": {"name": text_format.__name__, "strict": True, "schema": portable_schema(text_format)}},
    }
    if config.llm_provider == "openrouter":
        payload["provider"] = {"require_parameters": True}
    body = await post_json(f"{base}/chat/completions", headers=headers, payload=payload, provider=provider)
    raw_usage = body.get("usage", {})
    return SimpleNamespace(output_parsed=parse_json(_chat_text(body, provider), text_format, provider), usage=usage(raw_usage.get("prompt_tokens", 0), raw_usage.get("completion_tokens", 0)))
