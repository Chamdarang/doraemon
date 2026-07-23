from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import settings_service
from app.schemas import (
    GlobalSettings,
    GlobalSettingsUpdate,
    LlmActivity,
    LlmConnectionResult,
    PortConflictReport,
    RecoveryStatus,
)
from app.services.errors import ApplicationValidationError
from app.services.settings import SettingsService

router = APIRouter()


@router.get("/settings/recovery-status", response_model=RecoveryStatus)
def recovery_status(service: SettingsService = Depends(settings_service)):
    return service.recovery_status()


@router.get("/settings/port-conflicts", response_model=PortConflictReport)
def port_conflicts(service: SettingsService = Depends(settings_service)):
    return service.port_conflicts()


@router.post("/settings/port-conflicts/resolve", response_model=PortConflictReport)
def resolve_port_conflicts(service: SettingsService = Depends(settings_service)):
    return service.resolve_port_conflicts()


@router.get("/settings/llm/activity", response_model=LlmActivity)
def llm_activity(service: SettingsService = Depends(settings_service)):
    return service.llm_activity()


@router.get("/settings", response_model=GlobalSettings)
def get_settings(service: SettingsService = Depends(settings_service)):
    return service.get()


@router.put("/settings", response_model=GlobalSettings)
def update_settings(
    payload: GlobalSettingsUpdate, service: SettingsService = Depends(settings_service)
):
    try:
        return service.update(payload)
    except ApplicationValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/settings/llm/test", response_model=LlmConnectionResult)
async def test_llm_settings(service: SettingsService = Depends(settings_service)):
    try:
        return await service.test_llm()
    except ApplicationValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
