"""Application composition root and lifecycle owner."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.locks import ProjectLockRegistry
from app.repositories.store import ProjectStore
from app.runtime.manager import ProcessManager
from app.services.environment import EnvironmentService
from app.services.generation.service import GenerationService
from app.services.health import HealthService
from app.services.importer import ProjectImportService
from app.services.improvement import ImprovementService
from app.services.infrastructure import InfrastructureService
from app.services.maintenance import MaintenanceService
from app.services.operations import OperationsService
from app.services.planning import PlanningService
from app.services.projects import ProjectService
from app.services.runtime import RuntimeService
from app.services.settings import SettingsService
from app.services.tools import ProjectToolsService
from app.services.versioning import VersioningService
from app.services.workflow import WorkflowService


@dataclass(slots=True)
class ApplicationContainer:
    config: Settings
    store: ProjectStore
    project_locks: ProjectLockRegistry
    generator: GenerationService
    planning: PlanningService
    improvement: ImprovementService
    infrastructure: InfrastructureService
    processes: ProcessManager
    versioning: VersioningService
    health: HealthService
    maintenance: MaintenanceService
    project_tools: ProjectToolsService
    project_importer: ProjectImportService
    runtime_service: RuntimeService
    project_service: ProjectService
    environment_service: EnvironmentService
    settings_service: SettingsService
    workflow_service: WorkflowService
    operations_service: OperationsService

    @classmethod
    def build(cls, config: Settings) -> ApplicationContainer:
        store = ProjectStore(config)
        cls._restore_settings(config, store)
        project_locks = ProjectLockRegistry()
        generator = GenerationService(config, store, project_locks)
        planning = PlanningService(config, store)
        improvement = ImprovementService(config, store)
        infrastructure = InfrastructureService(store)
        processes = ProcessManager(store, infrastructure)
        versioning = VersioningService(store)
        health = HealthService(store, processes)
        maintenance = MaintenanceService(store)
        project_tools = ProjectToolsService(store)
        project_importer = ProjectImportService(store)
        runtime_service = RuntimeService(store, processes, health)
        project_service = ProjectService(store, runtime_service, health, project_importer)
        environment_service = EnvironmentService(store)
        settings_service = SettingsService(config, store, runtime_service)
        workflow_service = WorkflowService(
            store, runtime_service, generator, planning, improvement
        )
        operations_service = OperationsService(
            store,
            runtime_service,
            infrastructure,
            maintenance,
            project_tools,
            versioning,
        )
        return cls(
            config=config,
            store=store,
            project_locks=project_locks,
            generator=generator,
            planning=planning,
            improvement=improvement,
            infrastructure=infrastructure,
            processes=processes,
            versioning=versioning,
            health=health,
            maintenance=maintenance,
            project_tools=project_tools,
            project_importer=project_importer,
            runtime_service=runtime_service,
            project_service=project_service,
            environment_service=environment_service,
            settings_service=settings_service,
            workflow_service=workflow_service,
            operations_service=operations_service,
        )

    async def shutdown(self) -> None:
        await self.processes.shutdown()

    @staticmethod
    def _restore_settings(config: Settings, store: ProjectStore) -> None:
        saved = store.get_global_settings()
        config.openai_model = saved.llm_model
        config.openai_base_url = saved.llm_base_url or None
        config.llm_provider = saved.llm_provider
        config.llm_max_output_tokens = saved.llm_max_output_tokens
        legacy_keys = store.legacy_llm_api_keys()
        if not legacy_keys:
            return
        for provider, value in legacy_keys.items():
            if provider in config._provider_key_fields and not config.provider_api_key(provider):
                config.save_provider_api_key(provider, value)
        store.clear_legacy_llm_api_keys()
