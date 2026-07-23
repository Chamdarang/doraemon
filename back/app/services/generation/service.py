import asyncio
import shutil
from uuid import uuid4


from app.core.config import Settings
from app.schemas import (
    BackendGenerationSegment,
    FrontendGenerationSegment,
    GenerationBundle,
    ImprovementBundle,
    Job,
    JobStatus,
    now_iso,
)
from app.services.generation.context import (
    changed_context_paths,
    load_context_manifest,
    project_snapshot,
    save_context_manifest,
    select_context_paths,
)
from app.services.planning import PlanNotApprovedError
from app.repositories.store import ProjectStore
from app.services.versioning import VersioningService
from app.integrations.llm.client import parse_structured
from app.services.generation.artifacts import GenerationArtifactsMixin
from app.services.generation.contract import build_generation_input
from app.core.locks import ProjectLockRegistry
from app.runtime.diagnostics import RuntimeDiagnostics
from app.services.generation.prompts import (
    IMPROVEMENT_GENERATION_PROMPT,
    REPAIR_PROMPT,
    generation_prompt,
    segment_generation_prompt,
)
from app.services.generation.segments import merge_generation_segments, should_split_generation
from app.services.generation.pipeline import JobExecution, JobFailurePolicy, JobPipeline

class GenerationService(GenerationArtifactsMixin):
    def __init__(self, config: Settings, store: ProjectStore, project_locks: ProjectLockRegistry | None = None):
        self.config = config
        self.store = store
        self.tasks: dict[str, asyncio.Task] = {}
        self.versioning = VersioningService(store)
        self.project_locks = project_locks or ProjectLockRegistry()
        self.runtime_diagnostics = RuntimeDiagnostics(store)
        self.job_pipeline = JobPipeline(store, self.versioning, self.project_locks, self.runtime_diagnostics)
        self._fail_interrupted_jobs()

    def _fail_interrupted_jobs(self) -> None:
        """Background tasks cannot survive a Doraemon backend restart."""
        for project in self.store.list():
            for job in self.store.list_jobs(project.id):
                if job.status not in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
                    checkpoint = self.store.project_dir(project.id) / ".pocket" / "transactions" / job.id
                    restored = False
                    if checkpoint.is_dir():
                        try:
                            self.versioning.restore_checkpoint(project.id, checkpoint)
                            self.versioning.delete_checkpoint(checkpoint)
                            restored = True
                        except OSError:
                            restored = False
                    shutil.rmtree(self.store.project_dir(project.id) / ".pocket" / "staging" / job.id, ignore_errors=True)
                    shutil.rmtree(self.store.project_dir(project.id) / ".pocket" / "backup" / job.id, ignore_errors=True)
                    shutil.rmtree(self.store.project_dir(project.id) / ".pocket" / "backup" / f"improvement-{job.id}", ignore_errors=True)
                    job.status = JobStatus.failed
                    job.interrupted = True
                    job.retry_available = True
                    job.cached_result_available = self._cached_result_available(job)
                    job.message = "서버 재시작으로 작업이 중단되어 원본을 복구했습니다" if restored else "서버 재시작으로 작업이 중단되었습니다"
                    job.error = "저장된 생성 결과로 이어갈 수 있습니다." if job.cached_result_available else "다시 실행하면 LLM 요청이 새로 발생할 수 있습니다."
                    self.store.save_job(job)

    def _cached_result_available(self, job: Job) -> bool:
        if job.kind == "repair":
            return self._load_cached_repair(job.project_id, job.id) is not None
        if job.kind == "improvement":
            plan = self.store.get_improvement(job.project_id)
            return bool(plan and self._load_cached_improvement(job.project_id, plan.updated_at))
        plan = self.store.get_plan(job.project_id)
        manifest = self.store.get(job.project_id)
        if not plan:
            return False
        if self._load_cached_generation(
            job.project_id,
            plan.updated_at,
            manifest.llm_policy.mode,
        ):
            return True
        if not should_split_generation(plan, manifest.llm_policy.mode):
            return False
        return any(
            self._load_cached_generation_segment(
                job.project_id,
                plan.updated_at,
                manifest.llm_policy.mode,
                target,
            )
            for target in ("backend", "frontend")
        )

    def start(self, project_id: str) -> Job:
        self.store.get(project_id)
        self._ensure_idle(project_id)
        plan = self.store.get_plan(project_id)
        if not plan or not plan.approved or not plan.draft.specification:
            raise PlanNotApprovedError("확정 명세를 먼저 승인해야 합니다")
        job = Job(id=uuid4().hex, project_id=project_id, kind="generation")
        self.store.save_job(job)
        self.store.add_message(
            project_id,
            "assistant",
            "확정 명세가 승인되어 코드 생성을 시작했습니다. 진행 상태는 실행 탭에서도 확인할 수 있습니다.",
        )
        task = asyncio.create_task(self._run(job))
        self.tasks[job.id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job.id, None))
        return job

    def start_improvement(self, project_id: str) -> Job:
        self.store.get(project_id)
        self._ensure_idle(project_id)
        plan = self.store.get_improvement(project_id)
        if (
            not plan
            or not plan.approved
            or plan.applied_at is not None
            or not plan.draft.changes
            or plan.draft.open_questions
        ):
            raise PlanNotApprovedError("개선안을 먼저 확정하고 승인해주세요")
        job = Job(id=uuid4().hex, project_id=project_id, message="개선 적용 대기 중", kind="improvement")
        self.store.save_job(job)
        self.store.add_improvement_message(project_id, "assistant", "승인된 개선안 적용을 시작했습니다. 지정되지 않은 파일은 보존합니다.")
        task = asyncio.create_task(self._run_improvement(job))
        self.tasks[job.id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job.id, None))
        return job

    def _ensure_idle(self, project_id: str) -> None:
        if any(job.status not in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled} for job in self.store.list_jobs(project_id)):
            raise PlanNotApprovedError("이미 진행 중인 생성 또는 개선 작업이 있습니다")

    def start_repair(self, project_id: str, content: str) -> Job:
        self.store.get(project_id)
        self._ensure_idle(project_id)
        self.store.add_repair_message(project_id, "user", content)
        job = Job(id=uuid4().hex, project_id=project_id, message="오류 진단 대기 중", kind="repair", request_content=content)
        self.store.save_job(job)
        task = asyncio.create_task(self._run_repair(job, content))
        self.tasks[job.id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job.id, None))
        return job

    def resume(self, project_id: str, job_id: str) -> Job:
        """Restart an interrupted terminal job, reusing an already paid-for bundle when possible."""
        self.store.get(project_id)
        self._ensure_idle(project_id)
        previous = self.store.get_job(project_id, job_id)
        if previous.status not in {JobStatus.failed, JobStatus.cancelled}:
            raise PlanNotApprovedError("실패하거나 취소된 작업만 다시 시작할 수 있습니다")

        job = Job(
            id=uuid4().hex,
            project_id=project_id,
            kind=previous.kind,
            request_content=previous.request_content,
            message="중단된 작업을 다시 시작하는 중",
            cached_result_available=previous.cached_result_available,
        )
        self.store.save_job(job)
        if previous.kind == "generation":
            task = asyncio.create_task(self._run(job))
        elif previous.kind == "improvement":
            task = asyncio.create_task(self._run_improvement(job))
        else:
            if not previous.request_content:
                raise PlanNotApprovedError("오류 수정 요청 내용이 없어 다시 시작할 수 없습니다")
            cached = self._load_cached_repair(project_id, previous.id)
            task = asyncio.create_task(self._run_repair(job, previous.request_content, cached))
        self.tasks[job.id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job.id, None))
        self.store.add_notification(project_id, "info", "작업 재개", "중단된 작업을 다시 시작했습니다")
        return job

    async def _run_repair(self, job: Job, symptom: str, cached_bundle: ImprovementBundle | None = None) -> None:
        async def operation(execution: JobExecution) -> None:
            manifest = execution.manifest
            cache = self.store.project_dir(job.project_id) / ".pocket" / "repair-bundles" / f"{job.id}.json"
            if cached_bundle is None and not self.config.llm_configured:
                raise RuntimeError("선택한 LLM 공급자의 API 키 또는 주소가 설정되지 않았습니다")
            self._progress(job, JobStatus.generating, "로그와 소스를 분석해 오류를 수정하고 있습니다")
            root = self.store.project_dir(job.project_id)
            bundle = cached_bundle
            if bundle is None:
                logs = []
                for target in ("backend", "frontend"):
                    path = root / ".pocket" / "logs" / f"{target}.log"
                    if path.is_file():
                        logs.append(f"--- {target} log ---\n{path.read_text('utf-8', errors='replace')[-12_000:]}")
                context_manifest = load_context_manifest(root, "repair")
                cached_paths = context_manifest.get("selected_paths", [])
                changed_paths = changed_context_paths(root, context_manifest)
                cached_set = set(cached_paths) if isinstance(cached_paths, list) else set()
                selected_paths = select_context_paths(
                    root,
                    symptom,
                    [path for path in changed_paths if path in cached_set],
                    changed_paths,
                )
                source = project_snapshot(
                    root,
                    limit=manifest.llm_policy.generation_source_limit,
                    per_file_limit=16_000,
                    focus_paths=selected_paths,
                    focused_only=True,
                )
                save_context_manifest(root, "repair", selected_paths)
                response = await parse_structured(
                    self.config,
                    instructions=REPAIR_PROMPT,
                    input=f"Reported symptom:\n{symptom}\nRuntime logs:\n{''.join(logs)}\nCurrent source:\n{source}",
                    text_format=ImprovementBundle,
                    project_id=job.project_id,
                    operation="repair",
                )
                if response.usage:
                    self.store.record_usage(job.project_id, "repair", self.config.openai_model, response.usage, self.config.llm_provider)
                bundle = response.output_parsed
                if bundle is None:
                    raise RuntimeError("LLM이 유효한 오류 수정 결과를 반환하지 않았습니다")
            self._validate_repair_bundle(job.project_id, bundle)
            self.store._write_text_atomic(cache, bundle.model_dump_json(indent=2))
            async with execution.transaction():
                self._progress(job, JobStatus.writing, f"{len(bundle.files)}개 오류 수정 파일을 적용하고 있습니다")
                self._write_improvement(job.project_id, bundle, job.id)
                if bundle.runtime:
                    manifest.runtime = bundle.runtime
                manifest.status, manifest.last_error = "ready", None
                self.store.save(manifest)
                self.versioning.save_version(job.project_id, f"오류 수정: {bundle.summary}", job.id)
            self.job_pipeline.complete(job, bundle.summary)
            self.store.add_repair_message(job.project_id, "assistant", f"오류 수정 파일을 적용했습니다. {bundle.summary}")

        await self.job_pipeline.run(
            job,
            operation,
            JobFailurePolicy(
                message="오류 수정에 실패했습니다",
                notification_title="오류 수정 실패",
                cache_available=lambda: self._load_cached_repair(job.project_id, job.id) is not None,
                notify_chat=lambda error: self.store.add_repair_message(
                    job.project_id, "assistant", f"오류 수정에 실패했습니다: {error}"
                ),
                mark_project_error=True,
            ),
        )

    async def _run_improvement(self, job: Job) -> None:
        async def operation(execution: JobExecution) -> None:
            manifest = execution.manifest
            if not self.config.llm_configured:
                raise RuntimeError("선택한 LLM 공급자의 API 키 또는 주소가 설정되지 않았습니다")
            plan = self.store.get_improvement(job.project_id)
            if not plan or not plan.approved:
                raise PlanNotApprovedError("승인된 개선안을 찾을 수 없습니다")
            self._progress(job, JobStatus.generating, "현재 코드에 맞는 변경 패치를 생성하고 있습니다")
            bundle = self._load_cached_improvement(job.project_id, plan.updated_at)
            if bundle is None:
                focus_paths = [
                    change.path
                    for change in plan.draft.changes
                    if change.action != "add"
                ]

                root = self.store.project_dir(job.project_id)
                context_manifest = load_context_manifest(root, "improvement-generation")
                cached_paths = context_manifest.get("selected_paths", [])
                changed_paths = changed_context_paths(root, context_manifest)
                cached_set = set(cached_paths) if isinstance(cached_paths, list) else set()
                selected_paths = select_context_paths(
                    root,
                    plan.draft.goal,
                    [*focus_paths, *(path for path in changed_paths if path in cached_set)],
                    changed_paths,
                )
                current_source = project_snapshot(
                    root,
                    limit=manifest.llm_policy.generation_source_limit,
                    per_file_limit=20_000,
                    focus_paths=selected_paths,
                    focused_only=True,
                )
                save_context_manifest(root, "improvement-generation", selected_paths)

                response = await parse_structured(
                    self.config,
                    instructions=IMPROVEMENT_GENERATION_PROMPT,
                    input=(
                        f"Approved improvement:\n"
                        f"{plan.model_dump_json()}\n"
                        f"Current source:\n"
                        f"{current_source}"
                    ),
                    text_format=ImprovementBundle,
                    project_id=job.project_id,
                    operation="improvement_generation",
                )
                bundle = response.output_parsed
                if response.usage:
                    self.store.record_usage(job.project_id, "improvement_generation", self.config.openai_model, response.usage, self.config.llm_provider)
                if bundle is None:
                    raise RuntimeError("LLM이 유효한 개선 결과를 반환하지 않았습니다")
                # Persist before local validation/writing. A local bug or process restart must not
                # force the user to pay for the same generation again.
                self._save_cached_improvement(job.project_id, plan.updated_at, bundle)
            self._validate_improvement(job.project_id, bundle, plan)
            async with execution.transaction():
                self._progress(job, JobStatus.writing, f"{len(bundle.files)}개 파일의 개선사항을 적용하고 있습니다")
                self._write_improvement(job.project_id, bundle, job.id)
                if bundle.runtime:
                    manifest.runtime = bundle.runtime
                manifest.status, manifest.last_error = "ready", None
                self.store.save(manifest)
                self.versioning.save_version(job.project_id, bundle.summary, job.id)
                applied_plan = self.store.get_improvement(job.project_id)
                if applied_plan:
                    applied_plan.applied_at = now_iso()
                    self.store.save_improvement(job.project_id, applied_plan)
            self.job_pipeline.complete(job, bundle.summary)
            self.store.add_improvement_message(job.project_id, "assistant", f"개선 적용을 완료했습니다. {bundle.summary}")

        await self.job_pipeline.run(
            job,
            operation,
            JobFailurePolicy(
                message="개선 적용에 실패했습니다",
                notification_title="개선 적용 실패",
                cache_available=lambda: self._cached_result_available(job),
                notify_chat=lambda error: self.store.add_improvement_message(
                    job.project_id, "assistant", f"개선 적용에 실패했습니다: {error}"
                ),
            ),
        )

    def _record_generation_usage(self, project_id: str, response) -> None:
        if response.usage:
            self.store.record_usage(
                project_id,
                "generation",
                self.config.openai_model,
                response.usage,
                self.config.llm_provider,
            )

    async def _generate_split_bundle(self, job: Job, manifest, plan) -> GenerationBundle:
        generation_input = build_generation_input(manifest, plan)
        mode = manifest.llm_policy.mode
        backend = self._load_cached_generation_segment(
            job.project_id,
            plan.updated_at,
            mode,
            "backend",
        )
        if not isinstance(backend, BackendGenerationSegment):
            self._progress(job, JobStatus.generating, "백엔드와 인프라 코드를 생성하고 있습니다 (1/2)")
            response = await parse_structured(
                self.config,
                instructions=segment_generation_prompt(mode, "backend"),
                input=generation_input,
                text_format=BackendGenerationSegment,
                project_id=job.project_id,
                operation="generation_backend",
            )
            backend = response.output_parsed
            self._record_generation_usage(job.project_id, response)
            if backend is None:
                raise RuntimeError("LLM이 유효한 백엔드 생성 결과를 반환하지 않았습니다")
            self._save_cached_generation_segment(
                job.project_id,
                plan.updated_at,
                mode,
                "backend",
                backend,
            )

        frontend = self._load_cached_generation_segment(
            job.project_id,
            plan.updated_at,
            mode,
            "frontend",
        )
        if not isinstance(frontend, FrontendGenerationSegment):
            self._progress(job, JobStatus.generating, "프론트엔드 코드를 생성하고 있습니다 (2/2)")
            response = await parse_structured(
                self.config,
                instructions=segment_generation_prompt(mode, "frontend"),
                input=generation_input,
                text_format=FrontendGenerationSegment,
                project_id=job.project_id,
                operation="generation_frontend",
            )
            frontend = response.output_parsed
            self._record_generation_usage(job.project_id, response)
            if frontend is None:
                raise RuntimeError("LLM이 유효한 프론트엔드 생성 결과를 반환하지 않았습니다")
            self._save_cached_generation_segment(
                job.project_id,
                plan.updated_at,
                mode,
                "frontend",
                frontend,
            )
        return merge_generation_segments(backend, frontend)

    async def _run(self, job: Job) -> None:
        async def operation(execution: JobExecution) -> None:
            manifest = execution.manifest
            manifest.status = "generating"
            manifest.last_error = None
            self.store.save(manifest)
            self._progress(job, JobStatus.planning, "서비스 구조를 설계하고 있습니다")
            if not self.config.llm_configured:
                raise RuntimeError("선택한 LLM 공급자의 API 키 또는 주소가 설정되지 않았습니다")
            self._progress(job, JobStatus.generating, "백엔드와 프론트엔드 코드를 생성하고 있습니다")
            plan = self.store.get_plan(job.project_id)
            if not plan or not plan.draft.specification:
                raise PlanNotApprovedError("승인된 명세를 찾을 수 없습니다")
            bundle = self._load_cached_generation(
                job.project_id,
                plan.updated_at,
                manifest.llm_policy.mode,
            )
            if bundle is None:
                if should_split_generation(plan, manifest.llm_policy.mode):
                    bundle = await self._generate_split_bundle(job, manifest, plan)
                else:
                    response = await parse_structured(
                        self.config,
                        instructions=generation_prompt(manifest.llm_policy.mode),
                        input=build_generation_input(manifest, plan),
                        text_format=GenerationBundle,
                        project_id=job.project_id,
                        operation="generation",
                    )
                    bundle = response.output_parsed
                    self._record_generation_usage(job.project_id, response)
                    if bundle is None:
                        raise RuntimeError("LLM이 유효한 생성 결과를 반환하지 않았습니다")
                self._save_cached_generation(
                    job.project_id,
                    plan.updated_at,
                    bundle,
                    manifest.llm_policy.mode,
                )
            self._validate_bundle(job.project_id, bundle)
            async with execution.transaction():
                self._progress(job, JobStatus.writing, f"{len(bundle.files)}개 파일을 저장하고 있습니다")
                self._write_bundle(job.project_id, bundle, job.id)
                manifest.runtime = bundle.runtime
                manifest.status = "ready"
                self.store.save(manifest)
                self.versioning.save_version(job.project_id, bundle.summary, job.id)
            job.generation_report = bundle.coverage
            self.job_pipeline.complete(job, bundle.summary)
            self.store.add_message(
                job.project_id,
                "assistant",
                f"코드 생성이 완료되었습니다. {bundle.summary}",
            )

        await self.job_pipeline.run(
            job,
            operation,
            JobFailurePolicy(
                message="생성에 실패했습니다",
                notification_title="코드 생성 실패",
                cache_available=lambda: self._cached_result_available(job),
                notify_chat=lambda error: self.store.add_message(
                    job.project_id, "assistant", f"코드 생성에 실패했습니다: {error}"
                ),
                mark_project_error=True,
            ),
        )

    def _progress(self, job: Job, status: JobStatus, message: str) -> None:
        job.status = status
        job.message = message
        self.store.save_job(job)

    async def cancel(self, project_id: str, job_id: str) -> Job:
        job = self.store.get_job(project_id, job_id)
        task = self.tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if job.status not in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
            job.status = JobStatus.cancelled
            job.message = "사용자가 작업을 취소했습니다"
            job.error = None
            job.retry_available = True
            job.cached_result_available = self._cached_result_available(job)
            self.store.save_job(job)
            self.store.add_notification(project_id, "warning", "작업 취소", job.message)
        manifest = self.store.get(project_id)
        root = self.store.project_dir(project_id)
        has_source = any((root / area).is_dir() and any((root / area).iterdir()) for area in ("back", "front"))
        manifest.status = "ready" if has_source else "draft"
        manifest.last_error = None
        self.store.save(manifest)
        return job
