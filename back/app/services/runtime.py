from __future__ import annotations

from typing import Literal

from app.repositories.errors import ProjectNotFoundError
from app.repositories.store import ProjectStore
from app.runtime.manager import ProcessManager
from app.schemas import LogChunk, ProcessState, ProjectManifest, RuntimePortsUpdate, RuntimeSnapshot
from app.services.errors import ApplicationConflictError, ApplicationValidationError, ResourceNotFoundError
from app.services.health import HealthService

RuntimeTarget = Literal["backend", "frontend"]


class RuntimeService:
    def __init__(self, store: ProjectStore, manager: ProcessManager, health: HealthService):
        self.store = store
        self.manager = manager
        self.health = health

    def states(self, project_id: str) -> list[ProcessState]:
        try:
            return [self.manager.state(project_id, "backend"), self.manager.state(project_id, "frontend")]
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    async def snapshot(
        self,
        project_id: str,
        include_logs: bool,
        backend_cursor: int,
        backend_log_id: str,
        frontend_cursor: int,
        frontend_log_id: str,
    ) -> RuntimeSnapshot:
        self._project(project_id)
        logs = {}
        if include_logs:
            logs = {
                "backend": LogChunk.model_validate(
                    self.manager.log_chunk(project_id, "backend", backend_cursor, backend_log_id)
                ),
                "frontend": LogChunk.model_validate(
                    self.manager.log_chunk(project_id, "frontend", frontend_cursor, frontend_log_id)
                ),
            }
        return RuntimeSnapshot(
            processes=self.states(project_id),
            jobs=self.store.list_jobs(project_id),
            overview=await self.health.overview(project_id, probe=False),
            notifications=self.store.list_notifications(project_id),
            logs=logs,
        )

    def update_ports(self, project_id: str, payload: RuntimePortsUpdate) -> ProjectManifest:
        self.ensure_stopped(project_id)
        if payload.backend_port == payload.frontend_port:
            raise ApplicationValidationError("백엔드와 프론트엔드 포트는 달라야 합니다")
        for label, port in (("백엔드", payload.backend_port), ("프론트엔드", payload.frontend_port)):
            if self.manager._available_port(port) != port:
                raise ApplicationConflictError(f"{label} 포트 {port}는 이미 사용 중입니다")
        requested = {payload.backend_port, payload.frontend_port}
        owner = next(
            (
                item
                for item in self.store.list()
                if item.id != project_id
                and requested & {item.runtime.backend_port, item.runtime.frontend_port}
            ),
            None,
        )
        if owner:
            conflict = requested & {owner.runtime.backend_port, owner.runtime.frontend_port}
            raise ApplicationConflictError(
                f"포트 {min(conflict)}는 Doraemon 서비스 '{owner.name}'에서 사용하도록 설정되어 있습니다."
            )
        project = self._project(project_id)
        project.runtime.backend_command = self.manager._command_with_port(
            project.runtime.backend_command, payload.backend_port, project.runtime.backend_port
        )
        project.runtime.frontend_command = self.manager._command_with_port(
            project.runtime.frontend_command, payload.frontend_port, project.runtime.frontend_port
        )
        project.runtime.backend_port = payload.backend_port
        project.runtime.frontend_port = payload.frontend_port
        self.store.save(project)
        declared = {item.key for item in project.runtime.environment}
        if {"BACKEND_PORT", "FRONTEND_PORT"} & declared:
            values = self.store.read_env(project_id)
            if "BACKEND_PORT" in declared:
                values["BACKEND_PORT"] = str(payload.backend_port)
            if "FRONTEND_PORT" in declared:
                values["FRONTEND_PORT"] = str(payload.frontend_port)
            self.store.write_env(project_id, values)
        return project

    async def start_all(self, project_id: str) -> list[ProcessState]:
        return await self._runtime_call(self.manager.start_all, project_id)

    async def stop_all(self, project_id: str) -> list[ProcessState]:
        return await self._runtime_call(self.manager.stop_all, project_id)

    async def start(self, project_id: str, target: RuntimeTarget) -> ProcessState:
        return await self._runtime_call(self.manager.start, project_id, target)

    async def stop(self, project_id: str, target: RuntimeTarget) -> ProcessState:
        try:
            return await self.manager.stop(project_id, target)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    def logs(self, project_id: str, target: RuntimeTarget, tail: int | None) -> dict[str, str]:
        lines = tail or self.store.get_global_settings().log_tail_lines
        return {"logs": self.manager.logs(project_id, target, lines)}

    def log_chunk(self, project_id: str, target: RuntimeTarget, cursor: int, log_id: str) -> dict:
        return self.manager.log_chunk(project_id, target, cursor, log_id)

    def ensure_stopped(self, project_id: str, message: str | None = None) -> None:
        if any(state.running for state in self.states(project_id)):
            raise ApplicationConflictError(
                message or "실행 중인 백엔드와 프론트엔드를 먼저 중지해주세요"
            )

    async def stop_project(self, project_id: str) -> None:
        for target in ("backend", "frontend"):
            if self.manager.state(project_id, target).running:
                await self.manager.stop(project_id, target)

    def _project(self, project_id: str) -> ProjectManifest:
        try:
            return self.store.get(project_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    async def _runtime_call(self, operation, *args):
        try:
            return await operation(*args)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None
        except (OSError, ValueError) as exc:
            raise ApplicationConflictError(str(exc)) from exc
