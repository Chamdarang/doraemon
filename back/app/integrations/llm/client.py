import asyncio
import json
from types import SimpleNamespace
from typing import TypeVar

from openai import APIConnectionError, APIStatusError
from pydantic import BaseModel

from app.core.config import Settings
from app.integrations.llm.providers import parse_anthropic, parse_compatible, parse_gemini, test_provider_connection
from app.integrations.llm.providers.common import LlmProviderError
from app.schemas import LlmActivity, now_iso
from app.services.generation.context import estimate_tokens

T = TypeVar("T", bound=BaseModel)


async def _parse_structured_unlocked(config: Settings, *, instructions: str, input: str | list[dict], text_format: type[T]) -> SimpleNamespace:
    try:
        if config.llm_provider == "openai":
            if not config.provider_api_key():
                raise LlmProviderError(f"{config.llm_provider_label} API 키가 설정되지 않았습니다.")
            return await config.llm_client().responses.parse(
                model=config.openai_model,
                instructions=instructions,
                input=input,
                text_format=text_format,
            )
        if config.llm_provider == "anthropic":
            return await parse_anthropic(config, instructions, input, text_format)
        if config.llm_provider == "gemini":
            return await parse_gemini(config, instructions, input, text_format)
        return await parse_compatible(config, instructions, input, text_format)
    except LlmProviderError:
        raise
    except APIConnectionError as exc:
        raise LlmProviderError(f"{config.llm_provider_label}에 연결할 수 없습니다: {exc}") from exc
    except APIStatusError as exc:
        raise LlmProviderError(
            f"{config.llm_provider_label} 요청 실패 ({exc.status_code}): {exc.message}"
        ) from exc


_paid_call_lock = asyncio.Lock()
_activity = LlmActivity()


def get_llm_activity() -> LlmActivity:
    return _activity.model_copy(deep=True)


async def parse_structured(
    config: Settings,
    *,
    instructions: str,
    input: str | list[dict],
    text_format: type[T],
    project_id: str | None = None,
    operation: str = "llm",
) -> SimpleNamespace:
    """Allow only one paid model request at a time in this local Doraemon instance."""
    if _paid_call_lock.locked():
        raise LlmProviderError("다른 LLM 요청이 진행 중입니다. 완료된 뒤 다시 시도해주세요. 중복 과금 방지를 위해 이번 요청은 전송하지 않았습니다.")
    async with _paid_call_lock:
        serialized = input if isinstance(input, str) else json.dumps(input, ensure_ascii=False)
        _activity.busy = True
        _activity.project_id = project_id
        _activity.operation = operation
        _activity.estimated_input_tokens = estimate_tokens(instructions + serialized)
        _activity.started_at = now_iso()
        try:
            return await _parse_structured_unlocked(config, instructions=instructions, input=input, text_format=text_format)
        finally:
            _activity.busy = False
            _activity.project_id = None
            _activity.operation = None
            _activity.estimated_input_tokens = 0
            _activity.started_at = None


async def test_connection(config: Settings) -> dict:
    return await test_provider_connection(config)


__all__ = ["LlmProviderError", "get_llm_activity", "parse_structured", "test_connection"]
