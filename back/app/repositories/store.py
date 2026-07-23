from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from app.core.config import Settings
from app.repositories.environment import EnvironmentStoreMixin
from app.schemas import GlobalSettings, PortChange, PortConflict, PortConflictReport, ProjectManifest, SearchResult, TrashItem, now_iso
from app.repositories.errors import ProjectNotFoundError
from app.repositories.jobs import JobRepositoryMixin
from app.repositories.notifications import NotificationRepositoryMixin
from app.repositories.versions import VersionRepositoryMixin
from app.repositories.workflow import WorkflowRepositoryMixin
from app.repositories.state_io import StateIOMixin
from app.runtime.command import replace_command_port

SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class ProjectStore(
    JobRepositoryMixin,
    NotificationRepositoryMixin,
    VersionRepositoryMixin,
    WorkflowRepositoryMixin,
    EnvironmentStoreMixin,
    StateIOMixin,
):
    """Project, trash and global settings store composed with domain repositories."""

    def __init__(self, config: Settings):
        self.root = config.root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def slugify(name: str) -> str:
        slug = SLUG_PATTERN.sub("-", name.lower()).strip("-")
        return slug or "service"

    def project_dir(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", project_id):
            raise ProjectNotFoundError(project_id)
        path = (self.root / project_id).resolve()
        if self.root not in path.parents:
            raise ProjectNotFoundError(project_id)
        return path

    def create(self, name: str, description: str) -> ProjectManifest:
        base = self.slugify(name)[:70]
        project_id = base
        suffix = 2
        while (self.root / project_id).exists():
            project_id = f"{base}-{suffix}"
            suffix += 1
        path = self.project_dir(project_id)
        (path / "back").mkdir(parents=True)
        (path / "front").mkdir()
        (path / ".pocket" / "jobs").mkdir(parents=True)
        (path / ".pocket" / "messages").mkdir()
        manifest = ProjectManifest(id=project_id, name=name, description=description)
        used_ports = {
            port
            for project in self.list()
            for port in (project.runtime.backend_port, project.runtime.frontend_port)
        }
        backend_port = self._next_project_port(8001, used_ports)
        used_ports.add(backend_port)
        frontend_port = self._next_project_port(5174, used_ports)
        manifest.runtime.backend_port = backend_port
        manifest.runtime.frontend_port = frontend_port
        manifest.runtime.backend_command = self._replace_command_port(manifest.runtime.backend_command, 8001, backend_port)
        manifest.runtime.frontend_command = self._replace_command_port(manifest.runtime.frontend_command, 5174, frontend_port)
        mode = self.get_global_settings().default_cost_mode
        manifest.llm_policy.mode = mode
        if mode == "economy":
            manifest.llm_policy.planning_source_limit, manifest.llm_policy.generation_source_limit = 25_000, 45_000
        elif mode == "quality":
            manifest.llm_policy.planning_source_limit, manifest.llm_policy.generation_source_limit = 70_000, 120_000
        self.save(manifest)
        return manifest

    @staticmethod
    def _next_project_port(preferred: int, used: set[int]) -> int:
        port = preferred
        while port in used:
            if port >= 65_535:
                raise RuntimeError("사용 가능한 프로젝트 포트가 없습니다.")
            port += 1
        return port

    @staticmethod
    def _replace_command_port(command: list[str], previous: int, current: int) -> list[str]:
        return replace_command_port(command, current, previous)

    def _reassign_conflicting_ports(self, project: ProjectManifest) -> None:
        used = {
            port
            for item in self.list()
            if item.id != project.id
            for port in (item.runtime.backend_port, item.runtime.frontend_port)
        }
        previous_backend = project.runtime.backend_port
        previous_frontend = project.runtime.frontend_port
        backend_port = previous_backend if previous_backend not in used else self._next_project_port(8001, used)
        used.add(backend_port)
        frontend_port = previous_frontend if previous_frontend not in used else self._next_project_port(5174, used)
        project.runtime.backend_command = self._replace_command_port(project.runtime.backend_command, previous_backend, backend_port)
        project.runtime.frontend_command = self._replace_command_port(project.runtime.frontend_command, previous_frontend, frontend_port)
        project.runtime.backend_port = backend_port
        project.runtime.frontend_port = frontend_port

    def port_conflict_report(self) -> PortConflictReport:
        owners: dict[int, list[str]] = {}
        for project in self.list():
            owners.setdefault(project.runtime.backend_port, []).append(f"{project.id}:backend")
            owners.setdefault(project.runtime.frontend_port, []).append(f"{project.id}:frontend")
        return PortConflictReport(
            conflicts=[
                PortConflict(port=port, owners=items)
                for port, items in sorted(owners.items())
                if len(items) > 1
            ]
        )

    def resolve_port_conflicts(self, running_projects: set[str] | None = None) -> PortConflictReport:
        running_projects = running_projects or set()
        projects = sorted(self.list(), key=lambda item: (item.id not in running_projects, item.id))
        used: set[int] = set()
        changes: list[PortChange] = []
        unresolved: list[str] = []
        for project in projects:
            changed = False
            for target, preferred in (("backend", 8001), ("frontend", 5174)):
                previous = getattr(project.runtime, f"{target}_port")
                if previous not in used:
                    used.add(previous)
                    continue
                if project.id in running_projects:
                    unresolved.append(project.id)
                    continue
                current = self._next_project_port(preferred, used)
                command_name = f"{target}_command"
                setattr(project.runtime, command_name, self._replace_command_port(
                    getattr(project.runtime, command_name), previous, current
                ))
                setattr(project.runtime, f"{target}_port", current)
                used.add(current)
                changes.append(PortChange(
                    project_id=project.id,
                    target=target,
                    previous_port=previous,
                    port=current,
                ))
                changed = True
            if changed:
                self.save(project)
                declared = {item.key for item in project.runtime.environment}
                if {"BACKEND_PORT", "FRONTEND_PORT"} & declared:
                    values = self.read_env(project.id)
                    if "BACKEND_PORT" in declared:
                        values["BACKEND_PORT"] = str(project.runtime.backend_port)
                    if "FRONTEND_PORT" in declared:
                        values["FRONTEND_PORT"] = str(project.runtime.frontend_port)
                    self.write_env(project.id, values)
        report = self.port_conflict_report()
        report.changes = changes
        report.unresolved_projects = sorted(set(unresolved))
        return report

    def list(self, include_archived: bool = False) -> list[ProjectManifest]:
        projects = []
        for manifest_path in self.root.glob("*/pocket.json"):
            try:
                project = self._read_model_with_backup(manifest_path, ProjectManifest)
                if include_archived or not project.archived_at:
                    projects.append(project)
            except (OSError, ValueError):
                continue
        return sorted(projects, key=lambda item: item.updated_at, reverse=True)

    def search(self, query: str, limit: int = 30) -> list[SearchResult]:
        needle = query.strip().casefold()
        if not needle:
            return []
        labels = {
            "generation": "최초 생성",
            "improvement": "개선 적용",
            "repair": "오류 수정",
        }
        matches: list[tuple[int, SearchResult]] = []
        for project in self.list():
            name = project.name.casefold()
            if needle in name or needle in project.id.casefold() or needle in project.description.casefold():
                score = 0 if name.startswith(needle) else 1 if needle in name else 2
                matches.append((score, SearchResult(
                    kind="project",
                    project_id=project.id,
                    project_name=project.name,
                    title=project.name,
                    subtitle=project.description[:180],
                    status=project.status,
                    updated_at=project.updated_at,
                )))
            for job in self.list_jobs(project.id):
                label = labels.get(job.kind, job.kind)
                haystack = " ".join((label, job.message or "", job.error or "", job.status)).casefold()
                if needle not in haystack:
                    continue
                score = 1 if needle in label.casefold() else 3
                detail = job.error or job.message
                matches.append((score, SearchResult(
                    kind="job",
                    project_id=project.id,
                    project_name=project.name,
                    title=f"{label} · {job.message}",
                    subtitle=(detail or "")[:180],
                    status=job.status,
                    updated_at=job.updated_at,
                )))
        matches.sort(key=lambda item: item[1].updated_at, reverse=True)
        matches.sort(key=lambda item: item[0])
        return [item for _, item in matches[:limit]]

    def clone(self, project_id: str, name: str) -> ProjectManifest:
        source = self.get(project_id)
        clone = self.create(name, source.description)
        backend_port = clone.runtime.backend_port
        frontend_port = clone.runtime.frontend_port
        clone_root = self.project_dir(clone.id)
        source_root = self.project_dir(project_id)
        ignored = shutil.ignore_patterns("node_modules", ".venv", "dist", "build", "__pycache__", ".next", ".env")
        for area in ("back", "front"):
            shutil.rmtree(clone_root / area)
            shutil.copytree(source_root / area, clone_root / area, ignore=ignored)
        clone.runtime = source.runtime.model_copy(deep=True)
        clone.runtime.backend_command = self._replace_command_port(clone.runtime.backend_command, source.runtime.backend_port, backend_port)
        clone.runtime.frontend_command = self._replace_command_port(clone.runtime.frontend_command, source.runtime.frontend_port, frontend_port)
        clone.runtime.backend_port = backend_port
        clone.runtime.frontend_port = frontend_port
        clone.llm_policy = source.llm_policy.model_copy(deep=True)
        clone.status = "ready" if source.status == "ready" else "draft"
        self.save(clone)
        if plan := self.get_plan(project_id):
            copied = plan.model_copy(deep=True)
            copied.approved = False
            self.save_plan(clone.id, copied)
        return clone

    def set_archived(self, project_id: str, archived: bool) -> ProjectManifest:
        project = self.get(project_id)
        if not archived:
            self._reassign_conflicting_ports(project)
        project.archived_at = now_iso() if archived else None
        self.save(project)
        return project

    def move_to_trash(self, project_id: str) -> None:
        project = self.get(project_id)
        trash = self.root / ".trash"
        trash.mkdir(exist_ok=True)
        shutil.move(str(self.project_dir(project_id)), str(trash / f"{project.id}-{uuid4().hex[:8]}"))

    def list_trash(self) -> list[TrashItem]:
        trash = self.root / ".trash"
        result = []
        if not trash.is_dir():
            return result
        for directory in trash.iterdir():
            manifest_path = directory / "pocket.json"
            if not directory.is_dir() or not manifest_path.is_file():
                continue
            try:
                project = ProjectManifest.model_validate_json(manifest_path.read_text("utf-8"))
                result.append(TrashItem(
                    id=directory.name,
                    project_id=project.id,
                    name=project.name,
                    description=project.description,
                    deleted_at=datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc).isoformat(),
                ))
            except (OSError, ValueError):
                continue
        return sorted(result, key=lambda item: item.deleted_at, reverse=True)

    def restore_trash(self, trash_id: str) -> ProjectManifest:
        source = self._trash_dir(trash_id)
        project = ProjectManifest.model_validate_json((source / "pocket.json").read_text("utf-8"))
        destination = self.project_dir(project.id)
        if destination.exists():
            raise FileExistsError("같은 ID의 서비스가 이미 있어 복구할 수 없습니다")
        self._reassign_conflicting_ports(project)
        shutil.move(str(source), str(destination))
        project.archived_at = None
        self.save(project)
        return project

    def delete_trash(self, trash_id: str) -> None:
        shutil.rmtree(self._trash_dir(trash_id))

    def _trash_dir(self, trash_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", trash_id):
            raise ProjectNotFoundError(trash_id)
        trash = (self.root / ".trash").resolve()
        path = (trash / trash_id).resolve()
        if trash not in path.parents or not (path / "pocket.json").is_file():
            raise ProjectNotFoundError(trash_id)
        return path

    def get_global_settings(self) -> GlobalSettings:
        path = self.root / ".pocket-settings.json"
        if not path.is_file() and not self._backup_path(path).is_file():
            return GlobalSettings()
        try:
            raw = self._read_model_with_backup(path, GlobalSettings).model_dump(mode="json")
            if raw.get("llm_provider") == "openai_compatible":
                raw["llm_provider"] = "custom"
            return GlobalSettings.model_validate(raw)
        except (OSError, ValueError):
            return GlobalSettings()

    def save_global_settings(self, settings: GlobalSettings) -> None:
        self._write_text_atomic(self.root / ".pocket-settings.json", settings.model_dump_json(indent=2), backup=True)

    def _llm_api_keys(self) -> dict[str, str]:
        path = self.root / ".pocket-llm-key"
        if not path.exists():
            return {}
        value = path.read_text("utf-8").strip()
        if not value:
            return {}
        try:
            loaded = json.loads(value)
            if isinstance(loaded, dict):
                return {str(key): str(item) for key, item in loaded.items() if item}
        except ValueError:
            pass
        return {"openai": value}

    def legacy_llm_api_keys(self) -> dict[str, str]:
        return self._llm_api_keys()

    def clear_legacy_llm_api_keys(self) -> None:
        (self.root / ".pocket-llm-key").unlink(missing_ok=True)

    def get(self, project_id: str) -> ProjectManifest:
        path = self.project_dir(project_id) / "pocket.json"
        if not path.is_file() and not self._backup_path(path).is_file():
            raise ProjectNotFoundError(project_id)
        return self._read_model_with_backup(path, ProjectManifest)

    def save(self, manifest: ProjectManifest) -> None:
        manifest.updated_at = now_iso()
        self._write_text_atomic(
            self.project_dir(manifest.id) / "pocket.json",
            manifest.model_dump_json(indent=2),
            backup=True,
        )


__all__ = ["ProjectNotFoundError", "ProjectStore"]
