from fastapi import APIRouter, Depends

from app.api.dependencies import settings_service
from app.services.settings import SettingsService

router = APIRouter()


@router.get("/health")
def health(service: SettingsService = Depends(settings_service)) -> dict[str, str | bool]:
    return service.health()
