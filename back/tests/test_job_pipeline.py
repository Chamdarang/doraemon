import asyncio

import pytest

from app.core.config import Settings
from app.services.generation.pipeline import JobFailurePolicy, JobPipeline
from app.schemas import Job, RuntimeConfig
from app.core.locks import ProjectLockRegistry
from app.runtime.diagnostics import RuntimeDiagnostics
from app.repositories.store import ProjectStore
from app.services.versioning import VersioningService


def pipeline(store: ProjectStore) -> JobPipeline:
    return JobPipeline(
        store,
        VersioningService(store),
        ProjectLockRegistry(),
        RuntimeDiagnostics(store),
    )


@pytest.mark.asyncio
async def test_pipeline_rolls_back_source_runtime_and_records_failure(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Pipeline failure", "공통 작업 파이프라인 실패 복구를 확인합니다")
    target = store.project_dir(project.id) / "back" / "main.py"
    target.write_text("before", "utf-8")
    job = Job(id="failed-pipeline", project_id=project.id)
    store.save_job(job)
    chat_errors = []

    async def operation(execution):
        async with execution.transaction():
            target.write_text("after", "utf-8")
            execution.manifest.runtime = RuntimeConfig(backend_port=9123)
            store.save(execution.manifest)
            raise RuntimeError("write failed")

    await pipeline(store).run(
        job,
        operation,
        JobFailurePolicy(
            message="생성에 실패했습니다",
            notification_title="코드 생성 실패",
            cache_available=lambda: True,
            notify_chat=chat_errors.append,
            mark_project_error=True,
        ),
    )

    saved = store.get_job(project.id, job.id)
    assert target.read_text("utf-8") == "before"
    assert store.get(project.id).runtime.backend_port == 8001
    assert store.get(project.id).status == "error"
    assert saved.status == "failed"
    assert saved.cached_result_available is True
    assert chat_errors == ["write failed"]
    assert not (store.project_dir(project.id) / ".pocket" / "transactions" / job.id).exists()


@pytest.mark.asyncio
async def test_pipeline_rolls_back_cancel_and_propagates_cancellation(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Pipeline cancel", "공통 작업 파이프라인 취소 복구를 확인합니다")
    target = store.project_dir(project.id) / "front" / "App.tsx"
    target.write_text("before", "utf-8")
    job = Job(id="cancelled-pipeline", project_id=project.id)
    store.save_job(job)

    async def operation(execution):
        async with execution.transaction():
            target.write_text("after", "utf-8")
            execution.manifest.runtime = RuntimeConfig(frontend_port=6123)
            store.save(execution.manifest)
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await pipeline(store).run(
            job,
            operation,
            JobFailurePolicy(
                message="unused",
                notification_title="unused",
                cache_available=lambda: False,
                notify_chat=lambda _error: None,
            ),
        )

    assert target.read_text("utf-8") == "before"
    assert store.get(project.id).runtime.frontend_port == 5174
    assert store.get_job(project.id, job.id).status == "queued"
