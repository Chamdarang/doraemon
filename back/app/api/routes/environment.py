from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import environment
from app.schemas import EnvironmentUpdate
from app.services.environment import EnvironmentService
from app.services.errors import ApplicationValidationError, ResourceNotFoundError

router = APIRouter(prefix="/projects/{project_id}/environment", tags=["environment"])


@router.get("")
def get_environment(project_id: str, service: EnvironmentService = Depends(environment)):
    try:
        return service.get(project_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("")
def update_environment(
    project_id: str,
    payload: EnvironmentUpdate,
    service: EnvironmentService = Depends(environment),
):
    try:
        return service.update(project_id, payload)
    except ResourceNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ApplicationValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/{key}")
def delete_environment(
    project_id: str, key: str, service: EnvironmentService = Depends(environment)
):
    try:
        return service.delete(project_id, key)
    except ResourceNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
