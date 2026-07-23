import shutil
from pathlib import Path

from app.schemas import MaintenanceSummary
from app.repositories.store import ProjectStore


class MaintenanceService:
    def __init__(self, store: ProjectStore):
        self.store = store

    def summary(self, project_id: str) -> MaintenanceSummary:
        root = self.store.project_dir(project_id)
        pocket = root / ".pocket"
        return MaintenanceSummary(
            disk_bytes=self._size(root),
            logs_bytes=self._size(pocket / "logs"),
            cache_bytes=sum(
                self._size(pocket / name)
                for name in (
                    "generation-bundle.json",
                    "generation-backend-segment.json",
                    "generation-frontend-segment.json",
                    "improvement-bundle.json",
                    "repair-bundles",
                )
            ),
            versions_bytes=self._size(pocket / "versions"),
            version_count=len(self.store.list_versions(project_id)),
        )

    def cleanup(self, project_id: str, clear_logs: bool, clear_cache: bool, keep_versions: int) -> MaintenanceSummary:
        root = self.store.project_dir(project_id)
        pocket = root / ".pocket"
        if clear_logs:
            logs = pocket / "logs"
            if logs.exists():
                for path in logs.glob("*.log*"):
                    if path.suffix == ".log":
                        path.write_text("", encoding="utf-8")
                    else:
                        path.unlink(missing_ok=True)
        if clear_cache:
            self.store.clear_generation_cache(project_id)
            repair_cache = pocket / "repair-bundles"
            if repair_cache.exists():
                shutil.rmtree(repair_cache)
        for version in self.store.list_versions(project_id)[keep_versions:]:
            directory = pocket / "versions" / version.id
            metadata = pocket / "versions" / f"{version.id}.json"
            if directory.exists():
                shutil.rmtree(directory)
            if metadata.exists():
                metadata.unlink()
            self.store._backup_path(metadata).unlink(missing_ok=True)
        return self.summary(project_id)

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_file():
            try:
                return path.stat().st_size
            except OSError:
                return 0
        if not path.exists():
            return 0
        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
        return total
