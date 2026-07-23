from fastapi import APIRouter

from app.api.routes.environment import router as environment_router
from app.api.routes.operations import router as operations_router
from app.api.routes.projects import router as projects_router
from app.api.routes.runtime import router as runtime_router
from app.api.routes.settings import router as settings_router
from app.api.routes.system import router as system_router
from app.api.routes.workflow import router as workflow_router

router = APIRouter()
router.include_router(projects_router)
router.include_router(settings_router)
router.include_router(system_router)
router.include_router(environment_router)
router.include_router(runtime_router)
router.include_router(workflow_router)
router.include_router(operations_router)
