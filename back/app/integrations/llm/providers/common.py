from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.integrations.llm.structured import parse_structured_output

T = TypeVar("T", bound=BaseModel)


class LlmProviderError(RuntimeError):
    """A safe, user-facing provider failure without secrets or response dumps."""


def api_key(config: Settings) -> str:
    secret = config.provider_api_key() if hasattr(config, "provider_api_key") else config.openai_api_key
    return secret.get_secret_value() if secret else ""


def messages(instructions: str, input_value: str | list[dict]) -> list[dict[str, Any]]:
    result = [{"role": "system", "content": instructions}]
    if isinstance(input_value, str):
        result.append({"role": "user", "content": input_value})
    else:
        result.extend(
            {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
            }
            for item in input_value
        )
    return result


def usage(input_tokens: int = 0, output_tokens: int = 0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_tokens_details=None,
    )


def portable_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Inline local refs and remove constraints rejected by stricter providers."""
    root = model.model_json_schema()
    definitions = root.get("$defs", {})
    unsupported = {
        "default", "examples", "minLength", "maxLength", "minimum", "maximum",
        "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "pattern",
    }

    def visit(value: Any, resolving: frozenset[str] = frozenset()) -> Any:
        if isinstance(value, list):
            return [visit(item, resolving) for item in value]
        if not isinstance(value, dict):
            return value
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.rsplit("/", 1)[-1]
            if name in resolving:
                return {"$ref": "#"}
            target = copy.deepcopy(definitions.get(name, {}))
            target.update({key: item for key, item in value.items() if key != "$ref"})
            return visit(target, resolving | {name})
        result = {
            key: visit(item, resolving)
            for key, item in value.items()
            if key not in unsupported and key not in {"$defs", "$schema"}
        }
        if result.get("type") == "object":
            result.setdefault("additionalProperties", False)
        return result

    return visit(root)


def error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.reason_phrase or "알 수 없는 응답"
    error = body.get("error", body) if isinstance(body, dict) else body
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or response.reason_phrase)
    return str(error)[:500]


def raise_http(response: httpx.Response, provider: str) -> None:
    if response.is_success:
        return
    labels = {401: "API 키가 올바르지 않습니다", 403: "API 접근 권한이 없습니다", 404: "모델 또는 API 주소를 찾을 수 없습니다", 429: "요청 한도 또는 잔액을 확인하세요"}
    reason = labels.get(response.status_code, error_detail(response))
    raise LlmProviderError(f"{provider} 요청 실패 ({response.status_code}): {reason}")


def parse_json(text: str, text_format: type[T], provider: str) -> T:
    try:
        return parse_structured_output(text, text_format)
    except (ValidationError, ValueError) as exc:
        raise LlmProviderError(f"{provider}가 약속한 형식과 다른 응답을 반환했습니다: {exc}") from exc


async def post_json(url: str, *, headers: dict[str, str], payload: dict[str, Any], provider: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=15)) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise LlmProviderError(f"{provider}에 연결할 수 없습니다: {exc}") from exc
    raise_http(response, provider)
    try:
        return response.json()
    except ValueError as exc:
        raise LlmProviderError(f"{provider}가 JSON이 아닌 응답을 반환했습니다.") from exc
