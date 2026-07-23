import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class StateIOMixin:
    """Atomic text writes and last-known-good Pydantic JSON recovery."""

    @staticmethod
    def _backup_path(path: Path) -> Path:
        return path.with_name(f"{path.name}.bak")

    def _read_model_with_backup(self, path: Path, model):
        error: Exception | None = None
        for candidate in (path, self._backup_path(path)):
            if not candidate.is_file():
                continue
            try:
                result = model.model_validate_json(candidate.read_text("utf-8"))
                if candidate != path:
                    self._write_text_atomic(path, result.model_dump_json(indent=2))
                    self._record_recovery(path)
                return result
            except (OSError, ValueError) as exc:
                error = exc
        if error:
            raise error
        raise FileNotFoundError(path)

    def _read_json_with_backup(self, path: Path):
        error: Exception | None = None
        for candidate in (path, self._backup_path(path)):
            if not candidate.is_file():
                continue
            try:
                result = json.loads(candidate.read_text("utf-8"))
                if candidate != path:
                    self._write_text_atomic(path, json.dumps(result, ensure_ascii=False, indent=2))
                    self._record_recovery(path)
                return result
            except (OSError, ValueError) as exc:
                error = exc
        if error:
            raise error
        raise FileNotFoundError(path)

    def _record_recovery(self, path: Path) -> None:
        root = getattr(self, "root", path.parent)
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = path.name
        log_path = root / ".pocket-recovery.json"
        try:
            events = json.loads(log_path.read_text("utf-8")) if log_path.is_file() else []
            if not isinstance(events, list):
                events = []
        except (OSError, ValueError):
            events = []
        events.append({
            "path": relative,
            "recovered_at": datetime.now(timezone.utc).isoformat(),
        })
        self._write_text_atomic(log_path, json.dumps(events[-100:], ensure_ascii=False, indent=2))

    def recovery_events(self) -> list[dict[str, str]]:
        path = getattr(self, "root") / ".pocket-recovery.json"
        try:
            events = json.loads(path.read_text("utf-8")) if path.is_file() else []
            return [item for item in events if isinstance(item, dict)][-100:]
        except (OSError, ValueError):
            return []

    @classmethod
    def _write_text_atomic(cls, path: Path, content: str, *, backup: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        backup_path = cls._backup_path(path)
        try:
            temporary.write_text(content, encoding="utf-8")
            if backup and path.is_file():
                try:
                    json.loads(path.read_text("utf-8"))
                    shutil.copy2(path, backup_path)
                except (OSError, ValueError):
                    pass
            os.replace(temporary, path)
            if backup and not backup_path.is_file():
                shutil.copy2(path, backup_path)
        finally:
            if temporary.exists():
                temporary.unlink()
