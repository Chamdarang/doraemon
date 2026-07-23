import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.schemas import (
    ChatMessage,
    ImprovementPlan,
    ProjectPlan,
    UsageRecord,
    UsageSummary,
    UsageTotals,
    now_iso,
)


class WorkflowRepositoryMixin:
    @staticmethod
    def request_fingerprint(content: str, apply_recommendations: bool = False) -> str:
        canonical = json.dumps(
            {"content": content, "apply_recommendations": apply_recommendations},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def load_idempotent_exchange(self, project_id: str, scope: str, request_id: str, fingerprint: str, model):
        path = self.project_dir(project_id) / ".pocket" / "idempotency" / f"{scope}-{request_id}.json"
        if not path.is_file() and not self._backup_path(path).is_file():
            return None
        raw = self._read_json_with_backup(path)
        if raw.get("fingerprint") != fingerprint:
            raise ValueError("같은 요청 ID가 다른 내용에 사용되었습니다. 새 요청으로 다시 시도해 주세요.")
        return model.model_validate(raw.get("response"))

    def save_idempotent_exchange(self, project_id: str, scope: str, request_id: str, fingerprint: str, exchange) -> None:
        path = self.project_dir(project_id) / ".pocket" / "idempotency" / f"{scope}-{request_id}.json"
        payload = {"fingerprint": fingerprint, "response": exchange.model_dump(mode="json")}
        self._write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2), backup=True)

    def add_message(self, project_id: str, role: str, content: str) -> ChatMessage:
        message = ChatMessage(id=uuid4().hex, role=role, content=content)
        path = self.project_dir(project_id) / ".pocket" / "messages" / f"{message.id}.json"
        self._write_text_atomic(path, message.model_dump_json(indent=2), backup=True)
        return message

    def list_messages(self, project_id: str) -> list[ChatMessage]:
        return sorted(self._read_messages(self.project_dir(project_id) / ".pocket" / "messages"), key=lambda item: item.created_at)

    def get_plan(self, project_id: str) -> ProjectPlan | None:
        path = self.project_dir(project_id) / ".pocket" / "plan.json"
        if not path.exists() and not self._backup_path(path).exists():
            return None
        return self._read_model_with_backup(path, ProjectPlan)

    def save_plan(self, project_id: str, plan: ProjectPlan) -> None:
        plan.updated_at = now_iso()
        path = self.project_dir(project_id) / ".pocket" / "plan.json"
        self._write_text_atomic(path, plan.model_dump_json(indent=2), backup=True)

    def get_improvement(self, project_id: str) -> ImprovementPlan | None:
        path = self.project_dir(project_id) / ".pocket" / "improvement.json"
        if not path.exists() and not self._backup_path(path).exists():
            return None
        return self._read_model_with_backup(path, ImprovementPlan)

    def save_improvement(self, project_id: str, plan: ImprovementPlan) -> None:
        plan.updated_at = now_iso()
        path = self.project_dir(project_id) / ".pocket" / "improvement.json"
        self._write_text_atomic(path, plan.model_dump_json(indent=2), backup=True)

    def _add_scoped_message(self, project_id: str, scope: str, role: str, content: str) -> ChatMessage:
        message = ChatMessage(id=uuid4().hex, role=role, content=content)
        directory = self.project_dir(project_id) / ".pocket" / scope
        self._write_text_atomic(directory / f"{message.id}.json", message.model_dump_json(indent=2), backup=True)
        return message

    def add_improvement_message(self, project_id: str, role: str, content: str) -> ChatMessage:
        return self._add_scoped_message(project_id, "improvement-messages", role, content)

    def list_improvement_messages(self, project_id: str) -> list[ChatMessage]:
        directory = self.project_dir(project_id) / ".pocket" / "improvement-messages"
        return sorted(self._read_messages(directory), key=lambda item: item.created_at) if directory.exists() else []

    def add_repair_message(self, project_id: str, role: str, content: str) -> ChatMessage:
        return self._add_scoped_message(project_id, "repair-messages", role, content)

    def list_repair_messages(self, project_id: str) -> list[ChatMessage]:
        directory = self.project_dir(project_id) / ".pocket" / "repair-messages"
        return sorted(self._read_messages(directory), key=lambda item: item.created_at) if directory.exists() else []

    def _read_messages(self, directory: Path) -> list[ChatMessage]:
        messages = []
        for path in directory.glob("*.json"):
            try:
                messages.append(self._read_model_with_backup(path, ChatMessage))
            except (OSError, ValueError):
                continue
        return messages

    def record_usage(
        self,
        project_id: str,
        kind: str,
        model: str,
        usage,
        provider: str = "openai",
    ) -> UsageRecord:
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        details = getattr(usage, "input_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0)
        record = UsageRecord(
            id=uuid4().hex,
            kind=kind,
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0),
            cached_input_tokens=cached,
        )
        path = self.project_dir(project_id) / ".pocket" / "usage" / f"{record.id}.json"
        self._write_text_atomic(path, record.model_dump_json(indent=2), backup=True)
        return record

    def usage_summary(self, project_id: str) -> UsageSummary:
        records = self.usage_records(project_id)
        by_kind: dict[str, UsageTotals] = {}
        for item in records:
            totals = by_kind.setdefault(item.kind, UsageTotals())
            totals.requests += 1
            totals.input_tokens += item.input_tokens
            totals.output_tokens += item.output_tokens
            totals.total_tokens += item.total_tokens
            totals.cached_input_tokens += item.cached_input_tokens
        return UsageSummary(
            requests=len(records),
            input_tokens=sum(item.input_tokens for item in records),
            output_tokens=sum(item.output_tokens for item in records),
            total_tokens=sum(item.total_tokens for item in records),
            cached_input_tokens=sum(item.cached_input_tokens for item in records),
            by_kind=by_kind,
        )

    def usage_records(
        self,
        project_id: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[UsageRecord]:
        directory = self.project_dir(project_id) / ".pocket" / "usage"
        records = []
        if directory.exists():
            for path in directory.glob("*.json"):
                try:
                    records.append(self._read_model_with_backup(path, UsageRecord))
                except (OSError, ValueError):
                    continue
        records.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        return records[offset:] if limit is None else records[offset : offset + limit]

    def clear_generation_cache(self, project_id: str) -> None:
        for name in (
            "generation-bundle.json",
            "generation-backend-segment.json",
            "generation-frontend-segment.json",
            "improvement-bundle.json",
        ):
            (self.project_dir(project_id) / ".pocket" / name).unlink(missing_ok=True)
