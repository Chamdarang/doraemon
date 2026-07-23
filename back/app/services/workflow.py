from __future__ import annotations

from app.repositories.errors import ProjectNotFoundError
from app.repositories.store import ProjectStore
from app.schemas import (
    ChatMessage,
    ChatMessageCreate,
    ImprovementExchange,
    ImprovementPlan,
    Job,
    PlanningExchange,
    ProjectPlan,
    RepairRequest,
    SpecificationUpdate,
)
from app.services.errors import (
    ApplicationConflictError,
    ApplicationUnavailableError,
    ResourceNotFoundError,
)
from app.services.generation.service import GenerationService
from app.services.improvement import ImprovementService
from app.services.planning import PlanNotApprovedError, PlanningService
from app.services.runtime import RuntimeService


class WorkflowService:
    def __init__(
        self,
        store: ProjectStore,
        runtime: RuntimeService,
        generator: GenerationService,
        planning: PlanningService,
        improvement: ImprovementService,
    ):
        self.store = store
        self.runtime = runtime
        self.generator = generator
        self.planning = planning
        self.improvement = improvement

    async def generate(self, project_id: str) -> Job:
        await self.runtime.stop_project(project_id)
        return self._generation_call(self.generator.start, project_id)

    def improvement_messages(self, project_id: str) -> list[ChatMessage]:
        self._project(project_id)
        return self.store.list_improvement_messages(project_id)

    async def send_improvement(
        self, project_id: str, payload: ChatMessageCreate
    ) -> ImprovementExchange:
        try:
            return await self.improvement.chat(project_id, payload)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None
        except PlanNotApprovedError as exc:
            raise ApplicationConflictError(str(exc)) from exc
        except ValueError as exc:
            raise ApplicationConflictError(str(exc)) from exc
        except RuntimeError as exc:
            raise ApplicationUnavailableError(str(exc)) from exc

    def get_improvement(self, project_id: str) -> ImprovementPlan:
        self._project(project_id)
        plan = self.store.get_improvement(project_id)
        if not plan:
            raise ResourceNotFoundError("아직 작성된 개선안이 없습니다")
        return plan

    def approve_improvement(self, project_id: str) -> ImprovementPlan:
        try:
            return self.improvement.approve(project_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None
        except PlanNotApprovedError as exc:
            raise ApplicationConflictError(str(exc)) from exc

    async def apply_improvement(self, project_id: str) -> Job:
        await self.runtime.stop_project(project_id)
        return self._generation_call(self.generator.start_improvement, project_id)

    def messages(self, project_id: str) -> list[ChatMessage]:
        self._project(project_id)
        return self.store.list_messages(project_id)

    async def send_message(self, project_id: str, payload: ChatMessageCreate) -> PlanningExchange:
        try:
            return await self.planning.chat(project_id, payload)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None
        except RuntimeError as exc:
            raise ApplicationUnavailableError(str(exc)) from exc
        except ValueError as exc:
            raise ApplicationConflictError(str(exc)) from exc

    def get_plan(self, project_id: str) -> ProjectPlan:
        self._project(project_id)
        plan = self.store.get_plan(project_id)
        if not plan:
            raise ResourceNotFoundError("아직 작성된 기획이 없습니다")
        return plan

    def approve_plan(self, project_id: str) -> ProjectPlan:
        try:
            return self.planning.approve(project_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None
        except PlanNotApprovedError as exc:
            raise ApplicationConflictError(str(exc)) from exc

    def update_specification(
        self, project_id: str, payload: SpecificationUpdate
    ) -> ProjectPlan:
        self._project(project_id)
        plan = self.store.get_plan(project_id)
        if not plan:
            raise ResourceNotFoundError("수정할 명세가 없습니다")
        plan.draft.service_specification = payload.service_specification.strip()
        plan.draft.technical_specification = payload.technical_specification.strip()
        plan.draft.specification = (
            f"# 서비스 명세\n{plan.draft.service_specification}\n\n"
            f"# 기술 명세\n{plan.draft.technical_specification}"
        )
        plan.approved = False
        self.store.save_plan(project_id, plan)
        return plan

    def jobs(self, project_id: str) -> list[Job]:
        self._project(project_id)
        return self.store.list_jobs(project_id)

    def get_job(self, project_id: str, job_id: str) -> Job:
        try:
            return self.store.get_job(project_id, job_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("작업을 찾을 수 없습니다") from None

    async def cancel_job(self, project_id: str, job_id: str) -> Job:
        try:
            return await self.generator.cancel(project_id, job_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("작업을 찾을 수 없습니다") from None

    async def resume_job(self, project_id: str, job_id: str) -> Job:
        await self.runtime.stop_project(project_id)
        return self._generation_call(self.generator.resume, project_id, job_id)

    def repair_messages(self, project_id: str) -> list[ChatMessage]:
        self._project(project_id)
        return self.store.list_repair_messages(project_id)

    async def start_repair(self, project_id: str, payload: RepairRequest) -> Job:
        await self.runtime.stop_project(project_id)
        return self._generation_call(self.generator.start_repair, project_id, payload.content)

    def _project(self, project_id: str) -> None:
        try:
            self.store.get(project_id)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None

    def _generation_call(self, operation, *args) -> Job:
        try:
            return operation(*args)
        except ProjectNotFoundError:
            raise ResourceNotFoundError("서비스를 찾을 수 없습니다") from None
        except PlanNotApprovedError as exc:
            raise ApplicationConflictError(str(exc)) from exc
