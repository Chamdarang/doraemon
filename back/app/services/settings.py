from __future__ import annotations

from app.core.config import Settings
from app.integrations.llm.client import LlmProviderError, get_llm_activity, test_connection
from app.repositories.store import ProjectStore
from app.schemas import (
    GlobalSettings,
    GlobalSettingsUpdate,
    LlmActivity,
    LlmConnectionResult,
    LlmProviderProfile,
    PortConflictReport,
    RecoveryStatus,
)
from app.services.errors import ApplicationValidationError
from app.services.runtime import RuntimeService


class SettingsService:
    def __init__(self, config: Settings, store: ProjectStore, runtime: RuntimeService):
        self.config = config
        self.store = store
        self.runtime = runtime

    def health(self) -> dict[str, str | bool]:
        return {
            "status": "ok",
            "llm_provider": self.config.llm_provider,
            "llm_provider_label": self.config.llm_provider_label,
            "llm_configured": self.config.llm_configured,
            "llm_model": self.config.openai_model,
        }

    def recovery_status(self) -> RecoveryStatus:
        events = self.store.recovery_events()
        return RecoveryStatus(recovered_count=len(events), events=events)

    def port_conflicts(self) -> PortConflictReport:
        return self.store.port_conflict_report()

    def resolve_port_conflicts(self) -> PortConflictReport:
        running = {
            project.id
            for project in self.store.list()
            if any(state.running for state in self.runtime.states(project.id))
        }
        return self.store.resolve_port_conflicts(running)

    def llm_activity(self) -> LlmActivity:
        return get_llm_activity()

    def get(self) -> GlobalSettings:
        result = self.store.get_global_settings()
        result.llm_model = self.config.openai_model
        result.llm_base_url = self.config.openai_base_url or ""
        result.llm_api_key_configured = bool(self.config.provider_api_key(result.llm_provider))
        result.llm_api_key_providers = self.config.configured_api_key_providers()
        result.llm_max_output_tokens = self.config.llm_max_output_tokens
        result.llm_profiles[result.llm_provider] = LlmProviderProfile(
            model=result.llm_model, base_url=result.llm_base_url
        )
        return result

    def update(self, payload: GlobalSettingsUpdate) -> GlobalSettings:
        try:
            if payload.clear_llm_api_key:
                self.config.save_provider_api_key(payload.llm_provider, None)
            elif payload.llm_api_key:
                self.config.save_provider_api_key(payload.llm_provider, payload.llm_api_key)
        except (OSError, ValueError) as exc:
            raise ApplicationValidationError(str(exc)) from exc
        saved = GlobalSettings.model_validate(payload.model_dump())
        saved.llm_profiles[saved.llm_provider] = LlmProviderProfile(
            model=saved.llm_model, base_url=saved.llm_base_url
        )
        saved.llm_api_key_configured = bool(self.config.provider_api_key(saved.llm_provider))
        saved.llm_api_key_providers = self.config.configured_api_key_providers()
        self.store.save_global_settings(saved)
        self.config.openai_model = saved.llm_model
        self.config.openai_base_url = saved.llm_base_url or None
        self.config.llm_provider = saved.llm_provider
        self.config.llm_max_output_tokens = saved.llm_max_output_tokens
        return saved

    async def test_llm(self) -> LlmConnectionResult:
        try:
            return LlmConnectionResult.model_validate(await test_connection(self.config))
        except LlmProviderError as exc:
            raise ApplicationValidationError(str(exc)) from exc
