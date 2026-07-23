from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import runtime
from app.schemas import ProcessState, ProjectManifest, RuntimePortsUpdate, RuntimeSnapshot
from app.services.errors import (
    ApplicationConflictError,
    ApplicationValidationError,
    ResourceNotFoundError,
)
from app.services.runtime import RuntimeService

router = APIRouter(prefix="/projects/{project_id}", tags=["runtime"])


def _raise_runtime_error(exc: Exception) -> None:
    if isinstance(exc, ResourceNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ApplicationValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise HTTPException(409, str(exc)) from exc


@router.get("/processes", response_model=list[ProcessState])
def process_states(project_id: str, service: RuntimeService = Depends(runtime)):
    try:
        return service.states(project_id)
    except ResourceNotFoundError as exc:
        _raise_runtime_error(exc)


@router.get("/runtime-snapshot", response_model=RuntimeSnapshot)
async def runtime_snapshot(
    project_id: str,
    include_logs: bool = Query(True),
    backend_cursor: int = Query(0, ge=0),
    backend_log_id: str = Query("", max_length=100),
    frontend_cursor: int = Query(0, ge=0),
    frontend_log_id: str = Query("", max_length=100),
    service: RuntimeService = Depends(runtime),
):
    try:
        return await service.snapshot(
            project_id,
            include_logs,
            backend_cursor,
            backend_log_id,
            frontend_cursor,
            frontend_log_id,
        )
    except ResourceNotFoundError as exc:
        _raise_runtime_error(exc)


@router.put("/runtime/ports", response_model=ProjectManifest)
def update_runtime_ports(
    project_id: str,
    payload: RuntimePortsUpdate,
    service: RuntimeService = Depends(runtime),
):
    try:
        return service.update_ports(project_id, payload)
    except (ResourceNotFoundError, ApplicationValidationError, ApplicationConflictError) as exc:
        _raise_runtime_error(exc)


@router.post("/processes/start-all", response_model=list[ProcessState])
async def start_all_processes(project_id: str, service: RuntimeService = Depends(runtime)):
    try:
        return await service.start_all(project_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_runtime_error(exc)


@router.post("/processes/stop-all", response_model=list[ProcessState])
async def stop_all_processes(project_id: str, service: RuntimeService = Depends(runtime)):
    try:
        return await service.stop_all(project_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_runtime_error(exc)


@router.post("/processes/{target}/start", response_model=ProcessState)
async def start_process(
    project_id: str,
    target: Literal["backend", "frontend"],
    service: RuntimeService = Depends(runtime),
):
    try:
        return await service.start(project_id, target)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_runtime_error(exc)


@router.post("/processes/{target}/stop", response_model=ProcessState)
async def stop_process(
    project_id: str,
    target: Literal["backend", "frontend"],
    service: RuntimeService = Depends(runtime),
):
    try:
        return await service.stop(project_id, target)
    except ResourceNotFoundError as exc:
        _raise_runtime_error(exc)


@router.get("/processes/{target}/logs")
def process_logs(
    project_id: str,
    target: Literal["backend", "frontend"],
    tail: int | None = Query(None, ge=1, le=5000),
    service: RuntimeService = Depends(runtime),
):
    return service.logs(project_id, target, tail)


@router.get("/processes/{target}/logs/chunk")
def process_log_chunk(
    project_id: str,
    target: Literal["backend", "frontend"],
    cursor: int = Query(0, ge=0),
    log_id: str = Query("", max_length=100),
    service: RuntimeService = Depends(runtime),
):
    return service.log_chunk(project_id, target, cursor, log_id)
