from app.core.config import Settings
from app.services.improvement import ImprovementService, project_snapshot, select_context_paths
from app.schemas import ImprovementChange, ImprovementDraft, ImprovementPlan
from app.repositories.store import ProjectStore


def test_concrete_improvement_can_be_approved_without_extra_llm_turn(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Ready", "추가 대화 없이 개선 적용 가능한지 검증하는 서비스")
    plan = ImprovementPlan(
        draft=ImprovementDraft(
            reply="변경안이 정리되었습니다.",
            goal="화면 개선",
            analysis="수정 범위가 명확함",
            changes=[ImprovementChange(path="front/app.tsx", action="add", reason="화면")],
            acceptance_criteria=["화면이 표시된다"],
            open_questions=[],
            ready_to_apply=False,
        )
    )
    store.save_improvement(project.id, plan)
    approved = ImprovementService(Settings(root=tmp_path), store).approve(project.id)
    assert approved.approved is True
    assert approved.draft.ready_to_apply is True


def test_focused_snapshot_keeps_tree_but_omits_unrelated_content(tmp_path):
    root = tmp_path / "service"
    (root / "front" / "src").mkdir(parents=True)
    (root / "front" / "src" / "target.tsx").write_text("TARGET_CONTENT", "utf-8")
    (root / "front" / "src" / "unrelated.tsx").write_text("UNRELATED_CONTENT", "utf-8")
    snapshot = project_snapshot(
        root,
        focus_paths=["front/src/target.tsx"],
        focused_only=True,
    )
    assert "front/src/unrelated.tsx" in snapshot
    assert "TARGET_CONTENT" in snapshot
    assert "UNRELATED_CONTENT" not in snapshot


def test_context_selection_prefers_requested_application_area(tmp_path):
    root = tmp_path / "service"
    (root / "front" / "src").mkdir(parents=True)
    (root / "back" / "app").mkdir(parents=True)
    (root / "front" / "src" / "Dashboard.tsx").write_text("dashboard", "utf-8")
    (root / "back" / "app" / "main.py").write_text("api", "utf-8")
    selected = select_context_paths(root, "대시보드 화면과 CSS를 개선해줘")
    assert "front/src/Dashboard.tsx" in selected
    snapshot = project_snapshot(root, focus_paths=selected, focused_only=True)
    assert "sha256:" in snapshot
    assert "dashboard" in snapshot
