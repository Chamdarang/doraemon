from typing import Any

import httpx

from app.core.config import Settings
from .common import LlmProviderError, api_key, raise_http


async def test_provider_connection(config: Settings) -> dict[str, Any]:
    provider = config.llm_provider
    key = api_key(config)
    if provider != "ollama" and not key:
        raise LlmProviderError("선택한 공급자의 API 키가 설정되지 않았습니다.")
    headers: dict[str, str] = {}
    if provider == "openai":
        url = f"https://api.openai.com/v1/models/{config.openai_model}"
        headers["authorization"] = f"Bearer {key}"
    elif provider == "anthropic":
        base = (config.openai_base_url or "https://api.anthropic.com/v1/messages").rstrip("/")
        root = base[:-9] if base.endswith("/messages") else base
        url = f"{root}/models/{config.openai_model}"
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    elif provider == "gemini":
        base = (config.openai_base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/").removesuffix("/openai")
        url = f"{base}/models/{config.openai_model}"
        headers["x-goog-api-key"] = key
    else:
        base = (config.openai_base_url or "").rstrip("/")
        if not base:
            raise LlmProviderError("API 주소가 설정되지 않았습니다.")
        url = f"{base}/models"
        if key:
            headers["authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8)) as client:
            response = await client.get(url, headers=headers)
    except httpx.RequestError as exc:
        raise LlmProviderError(f"공급자에 연결할 수 없습니다: {exc}") from exc
    raise_http(response, provider)
    model_found = True
    structured_output: bool | None = True if provider in {"openai", "anthropic", "gemini"} else None
    if provider in {"openrouter", "ollama", "custom"}:
        try:
            data = response.json().get("data", response.json().get("models", []))
            ids = {str(item.get("id") or item.get("name", "")).removeprefix("models/") for item in data if isinstance(item, dict)}
            model_found = config.openai_model.removeprefix("models/") in ids
            if provider == "openrouter":
                selected = next((item for item in data if isinstance(item, dict) and str(item.get("id", "")) == config.openai_model), None)
                parameters = selected.get("supported_parameters", []) if selected else []
                structured_output = "response_format" in parameters or "structured_outputs" in parameters
        except (ValueError, AttributeError):
            model_found = False
    if not model_found:
        raise LlmProviderError(f"연결은 됐지만 모델 '{config.openai_model}'을 찾을 수 없습니다.")
    if provider == "openrouter" and structured_output is False:
        raise LlmProviderError(f"모델 '{config.openai_model}'은 OpenRouter 구조화 출력을 지원하지 않습니다.")
    capability = "구조화 출력 지원도 확인했습니다." if structured_output else "구조화 출력 지원 여부는 첫 요청 전에 공급자에서 다시 확인됩니다."
    return {"provider": provider, "model": config.openai_model, "reachable": True, "model_found": True, "structured_output": structured_output, "detail": f"API 키와 모델 접근을 확인했습니다. {capability} 유료 생성 요청은 보내지 않았습니다."}
