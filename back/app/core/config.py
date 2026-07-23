from pathlib import Path
import os
from typing import ClassVar
from uuid import uuid4

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from openai import AsyncOpenAI


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="POCKET_", extra="ignore")

    app_name: str = "Doraemon"
    api_prefix: str = "/api"
    root: Path = Field(default=Path(__file__).resolve().parents[2] / "pocket")
    openai_model: str = "gpt-5.4-mini"
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "POCKET_OPENAI_API_KEY"),
    )
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "POCKET_ANTHROPIC_API_KEY"))
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY", "POCKET_GEMINI_API_KEY"))
    openrouter_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("OPENROUTER_API_KEY", "POCKET_OPENROUTER_API_KEY"))
    custom_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("CUSTOM_LLM_API_KEY", "POCKET_CUSTOM_LLM_API_KEY"))
    openai_base_url: str | None = None
    llm_provider: str = "openai"
    llm_max_output_tokens: int = 64_000
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    max_generated_files: int = 120
    max_file_size: int = 500_000
    llm_env_file: Path = Field(default=Path(__file__).resolve().parents[1] / ".env", exclude=True)

    _provider_key_fields: ClassVar[dict[str, tuple[str, str]]] = {
        "openai": ("openai_api_key", "OPENAI_API_KEY"),
        "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
        "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
        "openrouter": ("openrouter_api_key", "OPENROUTER_API_KEY"),
        "custom": ("custom_api_key", "CUSTOM_LLM_API_KEY"),
    }

    def provider_api_key(self, provider: str | None = None) -> SecretStr | None:
        selected = provider or self.llm_provider
        if selected == "ollama":
            return None
        field = self._provider_key_fields.get(selected, ("openai_api_key", "OPENAI_API_KEY"))[0]
        return getattr(self, field)

    def configured_api_key_providers(self) -> list[str]:
        return sorted(provider for provider in self._provider_key_fields if self.provider_api_key(provider))

    @property
    def llm_provider_label(self) -> str:
        return {
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "gemini": "Google Gemini",
            "openrouter": "OpenRouter",
            "ollama": "Ollama",
            "custom": "사용자 지정 LLM",
        }.get(self.llm_provider, self.llm_provider)

    def save_provider_api_key(self, provider: str, value: str | None) -> None:
        if provider == "ollama":
            return
        field, env_name = self._provider_key_fields[provider]
        if value and ("\n" in value or "\r" in value):
            raise ValueError("API 키에는 줄바꿈을 사용할 수 없습니다")
        normalized = value.strip() if value else None
        setattr(self, field, SecretStr(normalized) if normalized else None)
        self._update_env_value(env_name, normalized)

    def _update_env_value(self, key: str, value: str | None) -> None:
        path = self.llm_env_file
        lines = path.read_text("utf-8").splitlines() if path.is_file() else []
        replacement = f"{key}={value}" if value else None
        updated: list[str] = []
        found = False
        for line in lines:
            if line.lstrip().startswith("#") or "=" not in line or line.split("=", 1)[0].strip() != key:
                updated.append(line)
                continue
            if not found and replacement:
                updated.append(replacement)
            found = True
        if not found and replacement:
            updated.append(replacement)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text("\n".join(updated) + ("\n" if updated else ""), "utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider in {"ollama", "custom"}:
            return bool(self.openai_base_url)
        return bool(self.provider_api_key())

    def llm_client(self) -> AsyncOpenAI:
        secret = self.provider_api_key()
        key = secret.get_secret_value() if secret else "local"
        return AsyncOpenAI(api_key=key, base_url=self.openai_base_url or None)


settings = Settings()
