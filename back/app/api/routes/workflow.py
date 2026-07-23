from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import workflow
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
from app.services.workflow import WorkflowService

router = APIRouter(tags=["workflow"])


def _raise_workflow_error(exc: Exception) -> None:
    if isinstance(exc, ResourceNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ApplicationUnavailableError):
        raise HTTPException(503, str(exc)) from exc
    raise HTTPException(409, str(exc)) from exc


@router.post(
    "/projects/{project_id}/generate", response_model=Job, status_code=status.HTTP_202_ACCEPTED
)
async def generate_project(project_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return await service.generate(project_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_workflow_error(exc)


@router.get("/projects/{project_id}/improvements/messages", response_model=list[ChatMessage])
def list_improvement_messages(
    project_id: str, service: WorkflowService = Depends(workflow)
):
    try:
        return service.improvement_messages(project_id)
    except ResourceNotFoundError as exc:
        _raise_workflow_error(exc)


@router.post("/projects/{project_id}/improvements/messages", response_model=ImprovementExchange)
async def send_improvement_message(
    project_id: str,
    payload: ChatMessageCreate,
    service: WorkflowService = Depends(workflow),
):
    try:
        return await service.send_improvement(project_id, payload)
    except (ResourceNotFoundError, ApplicationConflictError, ApplicationUnavailableError) as exc:
        _raise_workflow_error(exc)


@router.get("/projects/{project_id}/improvement", response_model=ImprovementPlan)
def get_improvement(project_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return service.get_improvement(project_id)
    except ResourceNotFoundError as exc:
        _raise_workflow_error(exc)


@router.post("/projects/{project_id}/improvement/approve", response_model=ImprovementPlan)
def approve_improvement(project_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return service.approve_improvement(project_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_workflow_error(exc)


@router.post(
    "/projects/{project_id}/improvement/apply",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
async def apply_improvement(project_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return await service.apply_improvement(project_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_workflow_error(exc)


@router.get("/projects/{project_id}/messages", response_model=list[ChatMessage])
def list_messages(project_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return service.messages(project_id)
    except ResourceNotFoundError as exc:
        _raise_workflow_error(exc)


@router.post("/projects/{project_id}/messages", response_model=PlanningExchange)
async def send_message(
    project_id: str,
    payload: ChatMessageCreate,
    service: WorkflowService = Depends(workflow),
):
    try:
        return await service.send_message(project_id, payload)
    except (ResourceNotFoundError, ApplicationConflictError, ApplicationUnavailableError) as exc:
        _raise_workflow_error(exc)


@router.get("/projects/{project_id}/plan", response_model=ProjectPlan)
def get_plan(project_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return service.get_plan(project_id)
    except ResourceNotFoundError as exc:
        _raise_workflow_error(exc)


@router.post("/projects/{project_id}/plan/approve", response_model=ProjectPlan)
def approve_plan(project_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return service.approve_plan(project_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_workflow_error(exc)


@router.put("/projects/{project_id}/specification", response_model=ProjectPlan)
def update_specification(
    project_id: str,
    payload: SpecificationUpdate,
    service: WorkflowService = Depends(workflow),
):
    try:
        return service.update_specification(project_id, payload)
    except ResourceNotFoundError as exc:
        _raise_workflow_error(exc)


@router.get("/projects/{project_id}/jobs", response_model=list[Job])
def list_jobs(project_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return service.jobs(project_id)
    except ResourceNotFoundError as exc:
        _raise_workflow_error(exc)


@router.get("/projects/{project_id}/jobs/{job_id}", response_model=Job)
def get_job(project_id: str, job_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return service.get_job(project_id, job_id)
    except ResourceNotFoundError as exc:
        _raise_workflow_error(exc)


@router.post("/projects/{project_id}/jobs/{job_id}/cancel", response_model=Job)
async def cancel_job(
    project_id: str, job_id: str, service: WorkflowService = Depends(workflow)
):
    try:
        return await service.cancel_job(project_id, job_id)
    except ResourceNotFoundError as exc:
        _raise_workflow_error(exc)


@router.post(
    "/projects/{project_id}/jobs/{job_id}/resume",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_job(
    project_id: str, job_id: str, service: WorkflowService = Depends(workflow)
):
    try:
        return await service.resume_job(project_id, job_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_workflow_error(exc)


@router.get("/projects/{project_id}/repairs/messages", response_model=list[ChatMessage])
def list_repair_messages(project_id: str, service: WorkflowService = Depends(workflow)):
    try:
        return service.repair_messages(project_id)
    except ResourceNotFoundError as exc:
        _raise_workflow_error(exc)


@router.post(
    "/projects/{project_id}/repairs", response_model=Job, status_code=status.HTTP_202_ACCEPTED
)
async def start_repair(
    project_id: str, payload: RepairRequest, service: WorkflowService = Depends(workflow)
):
    try:
        return await service.start_repair(project_id, payload)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_workflow_error(exc)
