from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.api.dependencies import operations
from app.schemas import (
    ApiProbeRequest,
    ApiProbeResult,
    DiagnosticReport,
    InfrastructureControlRequest,
    InfrastructureLogs,
    InfrastructureOverview,
    InfrastructurePortsUpdate,
    MaintenanceRequest,
    MaintenanceSummary,
    Notification,
    SqliteDatabase,
    TechnologyStack,
    UsageRecord,
    UsageSummary,
    VersionDiff,
    VersionRecord,
)
from app.services.errors import (
    ApplicationConflictError,
    ApplicationValidationError,
    ResourceNotFoundError,
)
from app.services.operations import OperationsService

router = APIRouter(tags=["operations"])


def _raise_operations_error(exc: Exception) -> None:
    if isinstance(exc, ResourceNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ApplicationValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise HTTPException(409, str(exc)) from exc


@router.get("/projects/{project_id}/infrastructure", response_model=InfrastructureOverview)
async def infrastructure_overview(
    project_id: str, service: OperationsService = Depends(operations)
):
    try:
        return await service.infrastructure_overview(project_id)
    except (ResourceNotFoundError, ApplicationValidationError) as exc:
        _raise_operations_error(exc)


@router.get(
    "/projects/{project_id}/infrastructure/logs", response_model=InfrastructureLogs
)
async def infrastructure_logs(
    project_id: str,
    source: str = Query(...),
    service_name: str = Query(..., alias="service"),
    tail: int = Query(200, ge=10, le=2_000),
    service: OperationsService = Depends(operations),
):
    try:
        return await service.infrastructure_logs(project_id, source, service_name, tail)
    except (ResourceNotFoundError, ApplicationValidationError) as exc:
        _raise_operations_error(exc)


@router.post(
    "/projects/{project_id}/infrastructure/control", response_model=InfrastructureOverview
)
async def control_infrastructure(
    project_id: str,
    payload: InfrastructureControlRequest,
    service: OperationsService = Depends(operations),
):
    try:
        return await service.control_infrastructure(project_id, payload)
    except (ResourceNotFoundError, ApplicationValidationError) as exc:
        _raise_operations_error(exc)


@router.put(
    "/projects/{project_id}/infrastructure/ports", response_model=InfrastructureOverview
)
async def update_infrastructure_ports(
    project_id: str,
    payload: InfrastructurePortsUpdate,
    service: OperationsService = Depends(operations),
):
    try:
        return await service.update_infrastructure_ports(project_id, payload)
    except (ResourceNotFoundError, ApplicationValidationError, ApplicationConflictError) as exc:
        _raise_operations_error(exc)


@router.get("/projects/{project_id}/notifications", response_model=list[Notification])
def list_notifications(project_id: str, service: OperationsService = Depends(operations)):
    try:
        return service.notifications(project_id)
    except ResourceNotFoundError as exc:
        _raise_operations_error(exc)


@router.post("/projects/{project_id}/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
def read_notifications(project_id: str, service: OperationsService = Depends(operations)):
    try:
        service.mark_notifications_read(project_id)
    except ResourceNotFoundError as exc:
        _raise_operations_error(exc)


@router.post("/projects/{project_id}/api-probe", response_model=ApiProbeResult)
def api_probe(
    project_id: str,
    payload: ApiProbeRequest,
    service: OperationsService = Depends(operations),
):
    try:
        return service.api_probe(project_id, payload)
    except ApplicationConflictError as exc:
        _raise_operations_error(exc)


@router.get("/projects/{project_id}/diagnostics", response_model=DiagnosticReport)
def diagnostics(project_id: str, service: OperationsService = Depends(operations)):
    return service.diagnostics(project_id)


@router.get("/projects/{project_id}/technology-stack", response_model=TechnologyStack)
def technology_stack(project_id: str, service: OperationsService = Depends(operations)):
    return service.technology_stack(project_id)


@router.get("/projects/{project_id}/sqlite", response_model=list[SqliteDatabase])
def sqlite_databases(project_id: str, service: OperationsService = Depends(operations)):
    return service.sqlite_databases(project_id)


@router.get("/projects/{project_id}/sqlite/rows")
def sqlite_rows(
    project_id: str,
    path: str,
    table: str,
    limit: int = Query(100, ge=1, le=500),
    service: OperationsService = Depends(operations),
):
    try:
        return service.sqlite_rows(project_id, path, table, limit)
    except ApplicationValidationError as exc:
        _raise_operations_error(exc)


@router.post("/projects/{project_id}/export", response_class=FileResponse)
def export_project(project_id: str, service: OperationsService = Depends(operations)):
    path = service.export(project_id)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.get("/projects/{project_id}/usage", response_model=UsageSummary)
def get_usage(project_id: str, service: OperationsService = Depends(operations)):
    try:
        return service.usage(project_id)
    except ResourceNotFoundError as exc:
        _raise_operations_error(exc)


@router.get("/projects/{project_id}/usage/records", response_model=list[UsageRecord])
def get_usage_records(
    project_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: OperationsService = Depends(operations),
):
    try:
        return service.usage_records(project_id, offset, limit)
    except ResourceNotFoundError as exc:
        _raise_operations_error(exc)


@router.delete("/projects/{project_id}/cache", status_code=status.HTTP_204_NO_CONTENT)
def clear_cache(project_id: str, service: OperationsService = Depends(operations)):
    try:
        service.clear_cache(project_id)
    except ResourceNotFoundError as exc:
        _raise_operations_error(exc)


@router.get("/projects/{project_id}/maintenance", response_model=MaintenanceSummary)
def maintenance_summary(project_id: str, service: OperationsService = Depends(operations)):
    try:
        return service.maintenance_summary(project_id)
    except ResourceNotFoundError as exc:
        _raise_operations_error(exc)


@router.post("/projects/{project_id}/maintenance", response_model=MaintenanceSummary)
def run_maintenance(
    project_id: str,
    payload: MaintenanceRequest,
    service: OperationsService = Depends(operations),
):
    try:
        return service.run_maintenance(project_id, payload)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_operations_error(exc)


@router.get("/projects/{project_id}/versions", response_model=list[VersionRecord])
def list_versions(project_id: str, service: OperationsService = Depends(operations)):
    try:
        return service.versions(project_id)
    except ResourceNotFoundError as exc:
        _raise_operations_error(exc)


@router.get("/projects/{project_id}/versions/{version_id}/diff", response_model=VersionDiff)
def diff_version(
    project_id: str, version_id: str, service: OperationsService = Depends(operations)
):
    try:
        return service.diff_version(project_id, version_id)
    except ResourceNotFoundError as exc:
        _raise_operations_error(exc)


@router.post(
    "/projects/{project_id}/versions/{version_id}/restore", response_model=VersionRecord
)
def restore_version(
    project_id: str, version_id: str, service: OperationsService = Depends(operations)
):
    try:
        return service.restore_version(project_id, version_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_operations_error(exc)


@router.delete(
    "/projects/{project_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_version(
    project_id: str, version_id: str, service: OperationsService = Depends(operations)
):
    try:
        service.delete_version(project_id, version_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_operations_error(exc)
