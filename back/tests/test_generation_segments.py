from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.generation.segments import merge_generation_segments, should_split_generation
from app.services.generation.service import GenerationService
from app.schemas import (
    BackendGeneratedFile,
    BackendGenerationSegment,
    FrontendGeneratedFile,
    FrontendGenerationSegment,
    GenerationCoverage,
    GenerationKeyFile,
    ImplementationPlan,
    Job,
    PlanDecision,
    PlanDraft,
    ProjectPlan,
    ProjectStructureItem,
    RuntimeConfig,
)
from app.repositories.store import ProjectStore


def complex_plan() -> ProjectPlan:
    return ProjectPlan(
        draft=PlanDraft(
            reply="ready",
            stage="review",
            specification="x" * 8_000,
            decisions=[
                PlanDecision(category="backend_stack", choice="FastAPI", rationale="API", confirmed=True),
                PlanDecision(category="frontend_stack", choice="React + Vite", rationale="Web", confirmed=True),
            ],
            implementation_plan=ImplementationPlan(
                architecture="modular monolith",
                technology_choices=[],
                components=["api", "web"],
                directories=[ProjectStructureItem(path="back/app", purpose="API")],
                data_and_state="local",
                api_and_integrations="REST",
                runtime_and_configuration="Pocket",
                testing_strategy="manual",
            ),
        ),
        approved=True,
    )


def test_only_complex_quality_full_stack_generation_is_split():
    plan = complex_plan()

    assert should_split_generation(plan, "quality") is True
    assert should_split_generation(plan, "balanced") is False
    plan.draft.specification = "small"
    assert should_split_generation(plan, "quality") is False
    plan.draft.decisions[1].choice = "not applicable"
    plan.draft.specification = "x" * 8_000
    assert should_split_generation(plan, "quality") is False


def test_generation_segments_merge_files_runtime_and_honest_coverage():
    backend = BackendGenerationSegment(
        summary="backend complete",
        files=[BackendGeneratedFile(path="back/app.py", content="app = True")],
        runtime=RuntimeConfig(backend_port=8100),
        coverage=GenerationCoverage(
            apis=["GET /api/items"],
            core_flows=["항목 조회"],
            key_files=[
                GenerationKeyFile(path="back/app.py", purpose="API"),
                GenerationKeyFile(path="back/missing.py", purpose="not returned"),
            ],
        ),
    )
    frontend = FrontendGenerationSegment(
        summary="frontend complete",
        files=[FrontendGeneratedFile(path="front/src/App.tsx", content="export default function App() {}")],
        coverage=GenerationCoverage(
            screens=["목록"],
            core_flows=["항목 조회"],
            key_files=[GenerationKeyFile(path="front/src/App.tsx", purpose="화면")],
        ),
    )

    bundle = merge_generation_segments(backend, frontend)

    assert [item.path for item in bundle.files] == ["back/app.py", "front/src/App.tsx"]
    assert bundle.runtime.backend_port == 8100
    assert bundle.coverage.core_flows == ["항목 조회"]
    assert [item.path for item in bundle.coverage.key_files] == ["back/app.py", "front/src/App.tsx"]


@pytest.mark.asyncio
async def test_split_retry_reuses_paid_backend_segment(tmp_path, monkeypatch):
    config = Settings(root=tmp_path)
    store = ProjectStore(config)
    project = store.create("Split cache", "영역별 생성 결과를 재사용하는 복잡한 서비스")
    project.llm_policy.mode = "quality"
    store.save(project)
    plan = complex_plan()
    store.save_plan(project.id, plan)
    generator = GenerationService(config, store)
    backend = BackendGenerationSegment(
        summary="cached backend",
        files=[BackendGeneratedFile(path="back/app.py", content="app = True")],
        runtime=RuntimeConfig(),
    )
    generator._save_cached_generation_segment(
        project.id,
        plan.updated_at,
        "quality",
        "backend",
        backend,
    )
    calls = []

    async def fake_parse(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=FrontendGenerationSegment(
                summary="new frontend",
                files=[FrontendGeneratedFile(path="front/src/App.tsx", content="export default 1")],
            ),
            usage=None,
        )

    monkeypatch.setattr("app.services.generation.service.parse_structured", fake_parse)
    job = Job(id="split-job", project_id=project.id)

    bundle = await generator._generate_split_bundle(job, project, plan)

    assert len(calls) == 1
    assert calls[0]["operation"] == "generation_frontend"
    assert [item.path for item in bundle.files] == ["back/app.py", "front/src/App.tsx"]
    assert generator._cached_result_available(job) is True
