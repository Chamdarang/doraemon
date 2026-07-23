from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from app.schemas import Job, JobStatus, ProjectManifest
from app.core.locks import ProjectLockRegistry
from app.runtime.diagnostics import RuntimeDiagnostics
from app.repositories.store import ProjectStore
from app.services.versioning import VersioningService


@dataclass(frozen=True)
class JobFailurePolicy:
    message: str
    notification_title: str
    cache_available: Callable[[], bool]
    notify_chat: Callable[[str], None]
    mark_project_error: bool = False


class JobExecution:
    def __init__(
        self,
        job: Job,
        manifest: ProjectManifest,
        store: ProjectStore,
        versioning: VersioningService,
        locks: ProjectLockRegistry,
    ):
        self.job = job
        self.manifest = manifest
        self.store = store
        self.versioning = versioning
        self.locks = locks
        self.original_runtime = manifest.runtime.model_copy(deep=True)
        self.checkpoint: Path | None = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self.locks.hold(self.job.project_id):
            self.checkpoint = self.versioning.create_checkpoint(self.job.project_id, self.job.id)
            try:
                yield
            except BaseException:
                raise
            else:
                self.versioning.delete_checkpoint(self.checkpoint)
                self.checkpoint = None

    def rollback(self) -> None:
        if self.checkpoint is not None:
            try:
                self.versioning.restore_checkpoint(self.job.project_id, self.checkpoint)
            finally:
                self.versioning.delete_checkpoint(self.checkpoint)
                self.checkpoint = None
        self.manifest.runtime = self.original_runtime


class JobPipeline:
    """Shared lifecycle for paid generation jobs and transactional source writes."""

    def __init__(
        self,
        store: ProjectStore,
        versioning: VersioningService,
        locks: ProjectLockRegistry,
        diagnostics: RuntimeDiagnostics,
    ):
        self.store = store
        self.versioning = versioning
        self.locks = locks
        self.diagnostics = diagnostics

    async def run(
        self,
        job: Job,
        operation: Callable[[JobExecution], Awaitable[None]],
        failure: JobFailurePolicy,
    ) -> None:
        execution = JobExecution(
            job,
            self.store.get(job.project_id),
            self.store,
            self.versioning,
            self.locks,
        )
        try:
            await operation(execution)
        except asyncio.CancelledError:
            execution.rollback()
            self.store.save(execution.manifest)
            raise
        except Exception as exc:
            execution.rollback()
            if failure.mark_project_error:
                execution.manifest.status = "error"
                execution.manifest.last_error = str(exc)
            self.store.save(execution.manifest)
            job.status = JobStatus.failed
            job.message = failure.message
            job.error = str(exc)
            job.retry_available = True
            job.cached_result_available = failure.cache_available()
            self.store.save_job(job)
            self.store.add_notification(job.project_id, "error", failure.notification_title, str(exc))
            failure.notify_chat(str(exc))

    def complete(self, job: Job, summary: str) -> None:
        job.diagnostics = self.diagnostics.inspect(job.project_id)
        job.status = JobStatus.completed
        job.message = summary
        self.store.save_job(job)
        self.store.add_notification(job.project_id, "success", "작업 완료", summary)
