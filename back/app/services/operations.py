from __future__ import annotations

from pathlib import Path

from app.repositories.errors import ProjectNotFoundError
from app.repositories.store import ProjectStore
from app.schemas import (
    ApiProbeRequest,
    ApiProbeResult,
    DiagnosticReport,
    InfrastructureControlRequest,
    InfrastructureLogs,
    InfrastructureOverview,
    InfrastructurePortsUpdate,
    MaintenanceRequest,
    MaintenanceSummary,
    Notification,
    SqliteDatabase,
    TechnologyStack,
    UsageRecord,
    UsageSummary,
    VersionDiff,
    VersionRecord,
)
from app.services.errors import (
    ApplicationConflictError,
    ApplicationValidationError,
    ResourceNotFoundError,
)
from app.services.infrastructure import InfrastructureService
from app.services.maintenance import MaintenanceService
from app.services.runtime import RuntimeService
from app.services.tools import ProjectToolsService
from app.services.versioning import VersioningService


class OperationsService:
    def __init__(
        self,
        store: ProjectStore,
        runtime: RuntimeService,
        infrastructure: InfrastructureService,
        maintenance: MaintenanceService,
        tools: ProjectToolsService,
        versioning: VersioningService,
    ):
        self.store = store
        self.runtime = runtime
        self.infrastructure = infrastructure
        self.maintenance = maintenance
        self.tools = tools
        self.versioning = versioning

    async def infrastructure_overview(self, project_id: str) -> InfrastructureOverview:
        return await self._infrastructure_call(self.infrastructure.overview, project_id)

    async def infrastructure_logs(
        self, project_id: str, source: str, service: str, tail: int
    ) -> InfrastructureLogs:
        return await self._infrastructure_call(
            self.infrastructure.logs, project_id, source, service, tail
        )

    async def control_infrastructure(
        self, project_id: str, payload: InfrastructureControlRequest
    ) -> InfrastructureOverview:
        return await self._infrastructure_call(
            self.infrastructure.control,
            project_id,
            payload.source,
            payload.service,
            payload.action,
        )

    async def update_infrastructure_ports(
        self, project_id: str, payload: InfrastructurePortsUpdate
    ) -> InfrastructureOverview:
        self.runtime.ensure_stopped(project_id)
        return await self._infrastructure_call(
            self.infrastructure.update_ports, project_id, payload.values
        )

    def notifications(self, project_id: str) -> list[Notification]:
        self._project(project_id)
        return self.store.list_notifications(project_id)

    def mark_notifications_read(self, project_id: str) -> None:
        self._project(project_id)
        self.store.mark_notifications_read(project_id)

    def api_probe(self, project_id: str, payload: ApiProbeRequest) -> ApiProbeResult:
        try:
            return self.tools.api_probe(project_id, payload)
        except (OSError, ValueError) as exc:
            raise ApplicationConflictError(str(exc)) from exc

    def diagnostics(self, project_id: str) -> DiagnosticReport:
        return self.tools.diagnostics(project_id)

    def technology_stack(self, project_id: str) -> TechnologyStack:
        return self.tools.technology_stack(project_id)

    def sqlite_databases(self, project_id: str) -> list[SqliteDatabase]:
        return self.tools.sqlite_databases(project_id)

    def sqlite_rows(self, project_id: str, path: str, table: str, limit: int) -> list[dict]:
        try:
            return self.tools.sqlite_rows(project_id, path, table, limit)
        except (ValueError, OSError) as exc:
            raise ApplicationValidationError(str(exc)) from exc

    def export(self, project_id: str) -> Path:
        return self.tools.export(project_id)

    def usage(self, project_id: str) -> UsageSummary:
        self._project(project_id)
        return self.store.usage_summary(project_id)

    def usage_records(self, project_id: str, offset: int, limit: int) -> list[UsageRecord]:
        self._project(project_id)
        return self.store.usage_records(project_id, offset, limit)

    def clear_cache(self, project_id: str) -> None:
        self._project(project_id)
        self.store.clear_generation_cache(project_id)

    def maintenance_summary(self, project_id: str) -> MaintenanceSummary:
        try:
            return self.maintenance.summary(project_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    def run_maintenance(
        self, project_id: str, payload: MaintenanceRequest
    ) -> MaintenanceSummary:
        self.runtime.ensure_stopped(project_id)
        keep_versions = payload.keep_versions or self.store.get_global_settings().keep_versions
        return self.maintenance.cleanup(
            project_id, payload.clear_logs, payload.clear_cache, keep_versions
        )

    def versions(self, project_id: str) -> list[VersionRecord]:
        self._project(project_id)
        return self.store.list_versions(project_id)

    def diff_version(self, project_id: str, version_id: str) -> VersionDiff:
        try:
            return self.versioning.diff_version(project_id, version_id)
        except (ProjectNotFoundError, FileNotFoundError):
            raise ResourceNotFoundError("비교할 버전을 찾을 수 없습니다") from None

    def restore_version(self, project_id: str, version_id: str) -> VersionRecord:
        self.runtime.ensure_stopped(
            project_id, "실행 중인 백엔드와 프론트엔드를 중지한 뒤 복원해주세요"
        )
        try:
            return self.versioning.restore_version(project_id, version_id)
        except (ProjectNotFoundError, FileNotFoundError):
            raise ResourceNotFoundError("복원할 버전을 찾을 수 없습니다") from None

    def delete_version(self, project_id: str, version_id: str) -> None:
        self.runtime.ensure_stopped(project_id)
        try:
            self.versioning.delete_version(project_id, version_id)
        except (ProjectNotFoundError, FileNotFoundError):
            raise ResourceNotFoundError("삭제할 버전을 찾을 수 없습니다") from None

    def _project(self, project_id: str) -> None:
        try:
            self.store.get(project_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    async def _infrastructure_call(self, operation, *args):
        try:
            return await operation(*args)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None
        except ValueError as exc:
            raise ApplicationValidationError(str(exc)) from exc
