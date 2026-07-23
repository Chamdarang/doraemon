import pytest

from app.core.config import Settings
from app.services.generation.service import GenerationService
from app.schemas import (
    GenerationBundle,
    GenerationCoverage,
    GenerationKeyFile,
    ImprovementBundle,
    ImprovementChange,
    ImprovementDraft,
    ImprovementFile,
    ImprovementPlan,
    GeneratedFile,
    RuntimeConfig,
    Job,
    PlanDraft,
    ProjectPlan,
)
from app.repositories.store import ProjectStore


def test_generator_blocks_path_traversal(tmp_path):
    config = Settings(root=tmp_path)
    store = ProjectStore(config)
    project = store.create("Safe", "경로 이탈을 방지하는 테스트 서비스")
    generator = GenerationService(config, store)
    bundle = GenerationBundle(
        summary="x",
        files=[GeneratedFile(path="back/../escape.py", content="x")],
        runtime=RuntimeConfig(),
    )
    with pytest.raises(ValueError):
        generator._write_bundle(project.id, bundle)


def test_invalid_bundle_writes_nothing(tmp_path):
    config = Settings(root=tmp_path)
    store = ProjectStore(config)
    project = store.create("Atomic", "유효하지 않은 번들은 전혀 기록하지 않는 서비스")
    generator = GenerationService(config, store)
    bundle = GenerationBundle(
        summary="x",
        files=[
            GeneratedFile(path="back/valid.py", content="valid = True"),
            GeneratedFile(path="front/../invalid.md", content="invalid"),
        ],
        runtime=RuntimeConfig(),
    )
    with pytest.raises(ValueError):
        generator._write_bundle(project.id, bundle)
    assert not (store.project_dir(project.id) / "back" / "valid.py").exists()


def test_improvement_bundle_normalizes_model_shorthand():
    bundle = GenerationService._parse_improvement_bundle(
        '{"summary":"updated","files":{"front/app.tsx":"export {}"},'
        '"deleted_files":"not run","runtime":"not run"}'
    )
    assert bundle.files[0].path == "front/app.tsx"
    assert bundle.deleted_files == []
    assert bundle.runtime is None


def test_improvement_files_pass_generation_safety_validation(tmp_path):
    config = Settings(root=tmp_path)
    store = ProjectStore(config)
    project = store.create("Patch", "개선 파일 타입 변환을 검증하는 테스트 서비스")
    target = store.project_dir(project.id) / "front" / "app.tsx"
    target.write_text("old", encoding="utf-8")
    generator = GenerationService(config, store)
    bundle = ImprovementBundle(
        summary="updated",
        files=[ImprovementFile(path="front/app.tsx", content="new")],
    )
    plan = ImprovementPlan(
        draft=ImprovementDraft(
            reply="ready",
            goal="update",
            analysis="update one file",
            changes=[ImprovementChange(path="front/app.tsx", action="modify", reason="test")],
            ready_to_apply=True,
        ),
        approved=True,
    )
    generator._validate_improvement(project.id, bundle, plan)


def test_improvement_addition_accepts_approved_wildcard_path(tmp_path):
    config = Settings(root=tmp_path)
    store = ProjectStore(config)
    project = store.create("Patch folder", "승인된 폴더에 새 파일을 추가하는 서비스")
    generator = GenerationService(config, store)
    bundle = ImprovementBundle(
        summary="shared api client",
        files=[ImprovementFile(path="front/src/api/client.ts", content="export {}")],
    )
    plan = ImprovementPlan(
        draft=ImprovementDraft(
            reply="ready",
            goal="add api layer",
            analysis="separate fetch handling",
            changes=[
                ImprovementChange(
                    path="front/src/api/*",
                    action="add",
                    reason="공통 API 레이어",
                )
            ],
            ready_to_apply=True,
        ),
        approved=True,
    )

    generator._validate_improvement(project.id, bundle, plan)


def test_improvement_wildcard_does_not_approve_nested_or_other_actions(tmp_path):
    config = Settings(root=tmp_path)
    store = ProjectStore(config)
    project = store.create("Scoped patch", "와일드카드 범위를 제한하는 서비스")
    generator = GenerationService(config, store)
    plan = ImprovementPlan(
        draft=ImprovementDraft(
            reply="ready",
            goal="add api layer",
            analysis="one directory only",
            changes=[ImprovementChange(path="front/src/api/*", action="add", reason="API 파일")],
            ready_to_apply=True,
        ),
        approved=True,
    )

    nested = ImprovementBundle(
        summary="nested",
        files=[ImprovementFile(path="front/src/api/internal/client.ts", content="export {}")],
    )
    with pytest.raises(ValueError, match="승인되지 않은 파일 변경"):
        generator._validate_improvement(project.id, nested, plan)

    existing = store.project_dir(project.id) / "front" / "src" / "api" / "client.ts"
    existing.parent.mkdir(parents=True)
    existing.write_text("old", encoding="utf-8")
    modified = ImprovementBundle(
        summary="modify",
        files=[ImprovementFile(path="front/src/api/client.ts", content="new")],
    )
    with pytest.raises(ValueError, match="승인되지 않은 파일 변경"):
        generator._validate_improvement(project.id, modified, plan)


def test_improvement_bundle_cache_survives_local_validation_retry(tmp_path):
    config = Settings(root=tmp_path)
    store = ProjectStore(config)
    project = store.create("Cache", "LLM 개선 결과 재사용을 검증하는 테스트 서비스")
    generator = GenerationService(config, store)
    bundle = ImprovementBundle(
        summary="cached",
        files=[ImprovementFile(path="front/app.tsx", content="new")],
    )
    generator._save_cached_improvement(project.id, "same-plan", bundle)
    loaded = generator._load_cached_improvement(project.id, "same-plan")
    assert loaded is not None
    assert loaded.files[0].content == "new"
    assert generator._load_cached_improvement(project.id, "changed-plan") is None


def test_generation_cache_is_scoped_to_quality_mode(tmp_path):
    config = Settings(root=tmp_path)
    store = ProjectStore(config)
    project = store.create("Mode cache", "생성 품질 모드별 캐시를 구분하는 서비스")
    generator = GenerationService(config, store)
    bundle = GenerationBundle(
        summary="balanced result",
        files=[GeneratedFile(path="back/app.py", content="value = True")],
        runtime=RuntimeConfig(),
    )

    generator._save_cached_generation(project.id, "same-plan", bundle, "balanced")

    assert generator._load_cached_generation(project.id, "same-plan", "balanced") is not None
    assert generator._load_cached_generation(project.id, "same-plan", "quality") is None


@pytest.mark.asyncio
async def test_initial_generation_completes_without_validation(tmp_path):
    config = Settings(root=tmp_path, OPENAI_API_KEY="test-key")
    store = ProjectStore(config)
    project = store.create("Repairable", "검증 실패 산출물을 오류 수정에 남기는 테스트 서비스")
    plan = ProjectPlan(
        draft=PlanDraft(
            reply="ready",
            stage="review",
            ready_to_generate=True,
            specification="approved specification",
        ),
        approved=True,
    )
    store.save_plan(project.id, plan)
    bundle = GenerationBundle(
        summary="broken output",
        files=[GeneratedFile(path="back/app.py", content="raise RuntimeError('broken')")],
        runtime=RuntimeConfig(backend_port=8123),
        coverage=GenerationCoverage(
            apis=["GET /health"],
            core_flows=["서비스 상태 확인"],
            key_files=[GenerationKeyFile(path="back/app.py", purpose="백엔드 진입점")],
        ),
    )
    generator = GenerationService(config, store)
    generator._save_cached_generation(project.id, plan.updated_at, bundle)

    job = Job(id="failed-generation", project_id=project.id)
    store.save_job(job)
    await generator._run(job)

    assert (store.project_dir(project.id) / "back" / "app.py").is_file()
    assert store.get(project.id).runtime.backend_port == 8123
    assert store.get_job(project.id, job.id).status == "completed"
    assert store.get_job(project.id, job.id).diagnostics
    assert store.get_job(project.id, job.id).generation_report.apis == ["GET /health"]


@pytest.mark.asyncio
async def test_repair_completes_after_applying_files_without_validation(tmp_path):
    config = Settings(root=tmp_path, OPENAI_API_KEY="test-key")
    store = ProjectStore(config)
    project = store.create("Iterative repair", "오류 수정 실패 결과를 다음 시도에 넘기는 테스트 서비스")
    root = store.project_dir(project.id)
    target = root / "back" / "app.py"
    target.write_text("first failure", "utf-8")
    project.status = "error"
    store.save(project)
    generator = GenerationService(config, store)
    bundle = ImprovementBundle(
        summary="partial repair",
        files=[ImprovementFile(path="back/app.py", content="second failure")],
    )

    job = Job(id="repair-progress", project_id=project.id, kind="repair")
    store.save_job(job)
    await generator._run_repair(job, "fix it", bundle)

    assert target.read_text("utf-8") == "second failure"
    assert (root / ".pocket" / "repair-bundles" / f"{job.id}.json").exists()
    assert store.get_job(project.id, job.id).status == "completed"
