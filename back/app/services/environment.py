from __future__ import annotations

from app.repositories.errors import ProjectNotFoundError
from app.repositories.store import ProjectStore
from app.schemas import EnvironmentUpdate, ProjectManifest
from app.services.errors import ApplicationValidationError, ResourceNotFoundError


class EnvironmentService:
    def __init__(self, store: ProjectStore):
        self.store = store

    def get(self, project_id: str) -> dict:
        project = self._project(project_id)
        return self._response(project, self.store.read_env(project_id))

    def update(self, project_id: str, payload: EnvironmentUpdate) -> dict:
        project = self._project(project_id)
        values = self.store.read_env(project_id)
        values.update(payload.values)
        try:
            self.store.write_env(project_id, values)
        except ValueError as exc:
            raise ApplicationValidationError(str(exc)) from exc
        return self._response(project, values)

    def delete(self, project_id: str, key: str) -> dict:
        project = self._project(project_id)
        values = self.store.read_env(project_id)
        values.pop(key, None)
        self.store.write_env(project_id, values)
        return self._response(project, values)

    def _project(self, project_id: str) -> ProjectManifest:
        try:
            return self.store.get(project_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    def _response(self, project: ProjectManifest, saved: dict[str, str]) -> dict:
        declared = {item.key for item in project.runtime.environment}
        keys = self.store.discover_env_keys(project.id) | saved.keys() | declared
        values = {key: saved.get(key, "") for key in keys}
        schema = [{**item.model_dump(), "required": False} for item in project.runtime.environment]
        return {"values": self.store.masked_env(values), "schema": schema}
