from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LlmActivity(BaseModel):
    busy: bool = False
    project_id: str | None = None
    operation: str | None = None
    estimated_input_tokens: int = 0
    started_at: str | None = None


class LlmProviderProfile(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(default="", max_length=500)


class GlobalSettings(BaseModel):
    default_cost_mode: Literal["economy", "balanced", "quality"] = "balanced"
    keep_versions: int = Field(default=5, ge=1, le=100)
    log_tail_lines: int = Field(default=300, ge=50, le=5000)
    log_max_bytes: int = Field(default=2_000_000, ge=65_536, le=100_000_000)
    notification_retention_days: int = Field(default=30, ge=1, le=3650)
    notification_max_items: int = Field(default=200, ge=10, le=5000)
    llm_provider: Literal["openai", "anthropic", "gemini", "openrouter", "ollama", "custom"] = "openai"
    llm_model: str = Field(default="gpt-5.4-mini", min_length=1, max_length=200)
    llm_base_url: str = Field(default="", max_length=500)
    llm_api_key_configured: bool = False
    llm_api_key_providers: list[str] = Field(default_factory=list)
    llm_max_output_tokens: int = Field(default=64_000, ge=4_000, le=128_000)
    llm_profiles: dict[str, LlmProviderProfile] = Field(default_factory=dict)

    @field_validator("llm_provider", mode="before")
    @classmethod
    def migrate_provider_name(cls, value):
        return "custom" if value == "openai_compatible" else value


class GlobalSettingsUpdate(GlobalSettings):
    llm_api_key: str | None = Field(default=None, max_length=10_000)
    clear_llm_api_key: bool = False


class LlmConnectionResult(BaseModel):
    provider: str
    model: str
    reachable: bool
    model_found: bool
    structured_output: bool | None = None
    detail: str
