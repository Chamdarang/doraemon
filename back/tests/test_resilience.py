import pytest

from app.core.config import Settings
from app.schemas import ChatMessage, PlanDraft, PlanningExchange, ProjectPlan
from app.repositories.store import ProjectStore


def _exchange(store: ProjectStore, project_id: str) -> PlanningExchange:
    user = ChatMessage(id="user", role="user", content="질문")
    assistant = ChatMessage(id="assistant", role="assistant", content="응답")
    return PlanningExchange(
        user_message=user,
        assistant_message=assistant,
        plan=ProjectPlan(draft=PlanDraft(reply="응답", stage="discovery")),
    )


def test_idempotent_exchange_survives_store_restart(tmp_path):
    root = tmp_path / "pocket"
    store = ProjectStore(Settings(root=root))
    project = store.create("Idempotent", "동일한 유료 요청의 재전송을 방지하는 서비스입니다.")
    fingerprint = store.request_fingerprint("질문")
    exchange = _exchange(store, project.id)
    store.save_idempotent_exchange(project.id, "planning", "request-1234", fingerprint, exchange)

    restarted = ProjectStore(Settings(root=root))
    cached = restarted.load_idempotent_exchange(
        project.id, "planning", "request-1234", fingerprint, PlanningExchange
    )

    assert cached == exchange
    with pytest.raises(ValueError, match="다른 내용"):
        restarted.load_idempotent_exchange(
            project.id,
            "planning",
            "request-1234",
            restarted.request_fingerprint("다른 질문"),
            PlanningExchange,
        )


def test_existing_port_conflicts_are_detected_and_resolved(tmp_path):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))
    first = store.create("First", "첫 번째 포트 충돌 점검용 서비스입니다.")
    second = store.create("Second", "두 번째 포트 충돌 점검용 서비스입니다.")
    second.runtime.backend_port = first.runtime.backend_port
    second.runtime.backend_command = ["uvicorn", "app:app", "--port", str(first.runtime.backend_port)]
    store.save(second)

    assert store.port_conflict_report().conflicts[0].port == first.runtime.backend_port
    report = store.resolve_port_conflicts()
    updated = store.get(second.id)

    assert report.conflicts == []
    assert len(report.changes) == 1
    assert updated.runtime.backend_port != first.runtime.backend_port
    assert updated.runtime.backend_command[-1] == str(updated.runtime.backend_port)


def test_corrupt_manifest_recovers_from_backup_and_records_status(tmp_path):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))
    project = store.create("Recovery", "자동 백업 복구 상태를 확인하는 서비스입니다.")
    manifest_path = store.project_dir(project.id) / "pocket.json"
    manifest_path.write_text("{broken", encoding="utf-8")

    recovered = store.get(project.id)

    assert recovered.id == project.id
    events = store.recovery_events()
    assert events[-1]["path"] == f"{project.id}/pocket.json"
