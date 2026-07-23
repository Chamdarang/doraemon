from fastapi import Request

from app.core.container import ApplicationContainer
from app.services.environment import EnvironmentService
from app.services.operations import OperationsService
from app.services.projects import ProjectService
from app.services.runtime import RuntimeService
from app.services.settings import SettingsService
from app.services.workflow import WorkflowService


def container(request: Request) -> ApplicationContainer:
    return request.app.state.container


def projects(request: Request) -> ProjectService:
    return container(request).project_service


def environment(request: Request) -> EnvironmentService:
    return container(request).environment_service


def runtime(request: Request) -> RuntimeService:
    return container(request).runtime_service


def settings_service(request: Request) -> SettingsService:
    return container(request).settings_service


def workflow(request: Request) -> WorkflowService:
    return container(request).workflow_service


def operations(request: Request) -> OperationsService:
    return container(request).operations_service
