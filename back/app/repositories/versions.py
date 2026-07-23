import re

from app.schemas import VersionRecord
from app.repositories.errors import ProjectNotFoundError


class VersionRepositoryMixin:
    def save_version(self, record: VersionRecord) -> None:
        path = self.project_dir(record.project_id) / ".pocket" / "versions" / f"{record.id}.json"
        self._write_text_atomic(path, record.model_dump_json(indent=2), backup=True)

    def get_version(self, project_id: str, version_id: str) -> VersionRecord:
        if not re.fullmatch(r"[a-f0-9]{32}", version_id):
            raise ProjectNotFoundError(version_id)
        path = self.project_dir(project_id) / ".pocket" / "versions" / f"{version_id}.json"
        if not path.is_file() and not self._backup_path(path).is_file():
            raise ProjectNotFoundError(version_id)
        return self._read_model_with_backup(path, VersionRecord)

    def list_versions(self, project_id: str) -> list[VersionRecord]:
        directory = self.project_dir(project_id) / ".pocket" / "versions"
        versions = []
        if directory.exists():
            for path in directory.glob("*.json"):
                try:
                    versions.append(self._read_model_with_backup(path, VersionRecord))
                except (OSError, ValueError):
                    continue
        return sorted(versions, key=lambda item: item.created_at, reverse=True)
