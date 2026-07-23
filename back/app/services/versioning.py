import shutil
from dataclasses import dataclass
from difflib import unified_diff
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.schemas import VersionDiff, VersionDiffFile, VersionRecord
from app.repositories.store import ProjectStore


@dataclass(frozen=True)
class FileRevision:
    digest: str
    content: bytes | None


class VersioningService:
    IGNORED = {"node_modules", ".venv", "dist", "build", "__pycache__", ".next", "coverage"}
    MAX_DIFF_FILES = 200
    MAX_DIFF_LINES = 400
    MAX_DIFF_BYTES = 1_000_000

    def __init__(self, store: ProjectStore):
        self.store = store

    def create_checkpoint(self, project_id: str, key: str) -> Path:
        destination = self.store.project_dir(project_id) / ".pocket" / "transactions" / key
        if destination.exists():
            shutil.rmtree(destination)
        self._copy_project_areas(self.store.project_dir(project_id), destination)
        return destination

    def restore_checkpoint(self, project_id: str, checkpoint: Path) -> None:
        self._replace_project_areas(self.store.project_dir(project_id), checkpoint)

    def delete_checkpoint(self, checkpoint: Path) -> None:
        if checkpoint.exists():
            shutil.rmtree(checkpoint)

    def save_version(self, project_id: str, label: str, job_id: str | None) -> VersionRecord:
        record = VersionRecord(
            id=uuid4().hex,
            project_id=project_id,
            label=label,
            source_job_id=job_id,
            runtime=self.store.get(project_id).runtime.model_copy(deep=True),
        )
        directory = self.store.project_dir(project_id) / ".pocket" / "versions" / record.id
        self._copy_project_areas(self.store.project_dir(project_id), directory)
        self.store.save_version(record)
        keep = self.store.get_global_settings().keep_versions
        for expired in self.store.list_versions(project_id)[keep:]:
            self.delete_version(project_id, expired.id)
        return record

    def restore_version(self, project_id: str, version_id: str) -> VersionRecord:
        record = self.store.get_version(project_id, version_id)
        source = self.store.project_dir(project_id) / ".pocket" / "versions" / version_id
        if not source.is_dir():
            raise FileNotFoundError(version_id)
        self._replace_project_areas(self.store.project_dir(project_id), source)
        manifest = self.store.get(project_id)
        if record.runtime:
            manifest.runtime = record.runtime
        manifest.status = "ready"
        manifest.last_error = None
        self.store.save(manifest)
        return self.save_version(project_id, f"복원: {record.label}", None)

    def delete_version(self, project_id: str, version_id: str) -> None:
        self.store.get_version(project_id, version_id)
        directory = self.store.project_dir(project_id) / ".pocket" / "versions"
        snapshot = directory / version_id
        if snapshot.is_dir():
            shutil.rmtree(snapshot)
        (directory / f"{version_id}.json").unlink(missing_ok=True)
        self.store._backup_path(directory / f"{version_id}.json").unlink(missing_ok=True)

    def diff_version(self, project_id: str, version_id: str) -> VersionDiff:
        record = self.store.get_version(project_id, version_id)
        root = self.store.project_dir(project_id)
        snapshot = root / ".pocket" / "versions" / version_id
        if not snapshot.is_dir():
            raise FileNotFoundError(version_id)
        previous = self._file_map(snapshot)
        current = self._file_map(root)
        paths = sorted(previous.keys() | current.keys())
        files: list[VersionDiffFile] = []
        counts = {"added": 0, "modified": 0, "deleted": 0, "unchanged": 0}
        for path in paths:
            before = previous.get(path)
            after = current.get(path)
            if before == after:
                counts["unchanged"] += 1
                continue
            status: Literal["added", "modified", "deleted"] = (
                "added" if before is None else "deleted" if after is None else "modified"
            )
            counts[status] += 1
            if len(files) < self.MAX_DIFF_FILES:
                files.append(self._file_diff(path, status, before, after))
        changed_count = counts["added"] + counts["modified"] + counts["deleted"]
        return VersionDiff(
            version_id=version_id,
            files=files,
            added=counts["added"],
            modified=counts["modified"],
            deleted=counts["deleted"],
            unchanged=counts["unchanged"],
            runtime_changed=record.runtime != self.store.get(project_id).runtime,
            truncated_files=max(0, changed_count - len(files)),
        )

    def _file_map(self, root: Path) -> dict[str, FileRevision]:
        result: dict[str, FileRevision] = {}
        for area in ("back", "front"):
            directory = root / area
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                relative_parts = path.relative_to(root).parts
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or any(part in self.IGNORED or part.startswith(".pocket-") for part in relative_parts)
                ):
                    continue
                digest = sha256()
                content = bytearray() if path.stat().st_size <= self.MAX_DIFF_BYTES else None
                with path.open("rb") as handle:
                    while chunk := handle.read(65_536):
                        digest.update(chunk)
                        if content is not None:
                            content.extend(chunk)
                result[Path(*relative_parts).as_posix()] = FileRevision(
                    digest.hexdigest(),
                    bytes(content) if content is not None else None,
                )
        return result

    def _file_diff(
        self,
        path: str,
        status: Literal["added", "modified", "deleted"],
        before: FileRevision | None,
        after: FileRevision | None,
    ) -> VersionDiffFile:
        if (before and before.content is None) or (after and after.content is None):
            return VersionDiffFile(path=path, status=status, binary=True, truncated=True)
        try:
            before_content = before.content if before else b""
            after_content = after.content if after else b""
            assert before_content is not None and after_content is not None
            before_lines = before_content.decode("utf-8").splitlines()
            after_lines = after_content.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return VersionDiffFile(path=path, status=status, binary=True)
        lines = list(unified_diff(before_lines, after_lines, f"a/{path}", f"b/{path}", lineterm=""))
        additions = sum(line.startswith("+") and not line.startswith("+++") for line in lines)
        deletions = sum(line.startswith("-") and not line.startswith("---") for line in lines)
        truncated = len(lines) > self.MAX_DIFF_LINES
        return VersionDiffFile(
            path=path,
            status=status,
            additions=additions,
            deletions=deletions,
            diff="\n".join(lines[: self.MAX_DIFF_LINES]),
            truncated=truncated,
        )

    def _copy_project_areas(self, root: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for area in ("back", "front"):
            source = root / area
            target = destination / area
            if source.exists():
                shutil.copytree(source, target, ignore=self._ignore, dirs_exist_ok=True)
            else:
                target.mkdir()

    def _replace_project_areas(self, root: Path, source: Path) -> None:
        transaction = root / ".pocket" / "restore" / uuid4().hex
        prepared = transaction / "prepared"
        previous = transaction / "previous"
        moved: list[str] = []
        try:
            for area in ("back", "front"):
                source_area = source / area
                prepared_area = prepared / area
                if source_area.is_dir():
                    shutil.copytree(source_area, prepared_area)
                else:
                    prepared_area.mkdir(parents=True)
            previous.mkdir(parents=True)
            for area in ("back", "front"):
                target = root / area
                if target.exists():
                    shutil.move(str(target), str(previous / area))
                    moved.append(area)
                shutil.move(str(prepared / area), str(target))
        except Exception:
            for area in ("back", "front"):
                target = root / area
                old = previous / area
                if target.exists():
                    shutil.rmtree(target)
                if area in moved and old.exists():
                    shutil.move(str(old), str(target))
            raise
        finally:
            shutil.rmtree(transaction, ignore_errors=True)

    def _ignore(self, _directory, names):
        return [name for name in names if name in self.IGNORED or name.startswith(".pocket-")]
