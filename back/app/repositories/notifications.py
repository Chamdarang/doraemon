from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.schemas import Notification


class NotificationRepositoryMixin:
    def add_notification(self, project_id: str, level: str, title: str, message: str) -> Notification:
        item = Notification(id=uuid4().hex, level=level, title=title, message=message)
        path = self.project_dir(project_id) / ".pocket" / "notifications" / f"{item.id}.json"
        self._write_text_atomic(path, item.model_dump_json(indent=2), backup=True)
        self.cleanup_notifications(project_id)
        return item

    def list_notifications(self, project_id: str) -> list[Notification]:
        self.cleanup_notifications(project_id)
        directory = self.project_dir(project_id) / ".pocket" / "notifications"
        result = []
        if directory.exists():
            for path in directory.glob("*.json"):
                try:
                    result.append(self._read_model_with_backup(path, Notification))
                except (OSError, ValueError):
                    continue
        return sorted(result, key=lambda item: item.created_at, reverse=True)

    def cleanup_notifications(self, project_id: str) -> int:
        directory = self.project_dir(project_id) / ".pocket" / "notifications"
        if not directory.is_dir():
            return 0
        settings = self.get_global_settings()
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.notification_retention_days)
        entries = []
        removed = 0
        for path in directory.glob("*.json"):
            try:
                item = self._read_model_with_backup(path, Notification)
                created = datetime.fromisoformat(item.created_at.replace("Z", "+00:00"))
            except (OSError, ValueError):
                continue
            if created < cutoff:
                path.unlink(missing_ok=True)
                self._backup_path(path).unlink(missing_ok=True)
                removed += 1
            else:
                entries.append((path, item))
        entries.sort(key=lambda entry: entry[1].created_at, reverse=True)
        for path, _ in entries[settings.notification_max_items:]:
            path.unlink(missing_ok=True)
            self._backup_path(path).unlink(missing_ok=True)
            removed += 1
        return removed

    def mark_notifications_read(self, project_id: str) -> None:
        for item in self.list_notifications(project_id):
            if not item.read:
                item.read = True
                path = self.project_dir(project_id) / ".pocket" / "notifications" / f"{item.id}.json"
                self._write_text_atomic(path, item.model_dump_json(indent=2), backup=True)
