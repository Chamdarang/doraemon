from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from app.repositories.errors import ProjectNotFoundError
from app.repositories.store import ProjectStore
from app.schemas import (
    CloneRequest,
    ProjectCreate,
    ProjectManifest,
    ProjectOverview,
    ProjectUpdate,
    ProjectWorkspace,
    SearchResult,
    TrashItem,
)
from app.services.errors import ApplicationConflictError, ResourceNotFoundError
from app.services.health import HealthService
from app.services.importer import ProjectImportService
from app.services.runtime import RuntimeService


class ProjectService:
    def __init__(
        self,
        store: ProjectStore,
        runtime: RuntimeService,
        health: HealthService,
        importer: ProjectImportService,
    ):
        self.store = store
        self.runtime = runtime
        self.health = health
        self.importer = importer

    def search(self, query: str, limit: int) -> list[SearchResult]:
        normalized = query.strip()
        if len(normalized) < 2:
            return []
        return self.store.search(normalized[:100], max(1, min(limit, 100)))

    def list(self, archived: bool) -> list[ProjectManifest]:
        projects = self.store.list(include_archived=archived)
        return [item for item in projects if bool(item.archived_at) is archived]

    async def overviews(self, archived: bool) -> list[ProjectOverview]:
        return await asyncio.gather(
            *(self.health.overview(item.id, probe=False) for item in self.list(archived))
        )

    def create(self, payload: ProjectCreate) -> ProjectManifest:
        return self.store.create(payload.name, payload.description)

    def new_import_path(self) -> Path:
        directory = self.store.root / ".imports"
        directory.mkdir(exist_ok=True)
        return directory / f"upload-{uuid4().hex}.zip"

    def import_archive(self, name: str, description: str, path: Path) -> ProjectManifest:
        return self.importer.import_archive(name.strip(), description.strip(), path)

    def get(self, project_id: str) -> ProjectManifest:
        try:
            return self.store.get(project_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    async def overview(self, project_id: str, probe: bool) -> ProjectOverview:
        self.get(project_id)
        return await self.health.overview(project_id, probe=probe)

    async def workspace(self, project_id: str) -> ProjectWorkspace:
        self.get(project_id)
        return ProjectWorkspace(
            messages=self.store.list_messages(project_id),
            jobs=self.store.list_jobs(project_id),
            processes=self.runtime.states(project_id),
            improvement_messages=self.store.list_improvement_messages(project_id),
            plan=self.store.get_plan(project_id),
            improvement_plan=self.store.get_improvement(project_id),
            usage=self.store.usage_summary(project_id),
            versions=self.store.list_versions(project_id),
            repair_messages=self.store.list_repair_messages(project_id),
            overview=await self.health.overview(project_id),
            notifications=self.store.list_notifications(project_id),
        )

    def clone(self, project_id: str, payload: CloneRequest) -> ProjectManifest:
        self.runtime.ensure_stopped(project_id)
        try:
            return self.store.clone(project_id, payload.name)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    def archive(self, project_id: str) -> ProjectManifest:
        self.runtime.ensure_stopped(project_id)
        return self.store.set_archived(project_id, True)

    def unarchive(self, project_id: str) -> ProjectManifest:
        try:
            return self.store.set_archived(project_id, False)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    def trash(self, project_id: str) -> None:
        self.runtime.ensure_stopped(project_id)
        self.store.move_to_trash(project_id)

    def list_trash(self) -> list[TrashItem]:
        return self.store.list_trash()

    def restore_trash(self, trash_id: str) -> ProjectManifest:
        try:
            return self.store.restore_trash(trash_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("휴지통 항목을 찾을 수 없습니다") from None
        except FileExistsError as exc:
            raise ApplicationConflictError(str(exc)) from exc

    def delete_trash(self, trash_id: str) -> None:
        try:
            self.store.delete_trash(trash_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("휴지통 항목을 찾을 수 없습니다") from None

    def open_folder(self, project_id: str) -> None:
        path = self.store.project_dir(project_id)
        if not (path / "pocket.json").is_file():
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다")
        if os.name != "nt":
            raise ApplicationConflictError("현재 운영체제에서는 폴더 열기를 지원하지 않습니다")
        os.startfile(path)  # type: ignore[attr-defined]

    def update(self, project_id: str, payload: ProjectUpdate) -> ProjectManifest:
        project = self.get(project_id)
        if payload.name is not None:
            project.name = payload.name.strip()
        if payload.description is not None:
            project.description = payload.description.strip()
        if payload.runtime is not None:
            project.runtime = payload.runtime
        if payload.llm_policy is not None:
            project.llm_policy = payload.llm_policy
        self.store.save(project)
        return project
