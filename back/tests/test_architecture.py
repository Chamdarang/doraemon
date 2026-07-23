from pathlib import Path

from app.schemas.project import ProjectManifest as DomainProjectManifest
from app.schemas.runtime import RuntimeConfig as DomainRuntimeConfig
from app.schemas.workflow import Job as DomainJob
from app.schemas import Job, ProjectManifest, RuntimeConfig
from app.repositories.jobs import JobRepositoryMixin
from app.repositories.notifications import NotificationRepositoryMixin
from app.repositories.store import ProjectStore
from app.repositories.versions import VersionRepositoryMixin
from app.repositories.workflow import WorkflowRepositoryMixin


def test_public_model_facade_preserves_domain_class_identity():
    assert ProjectManifest is DomainProjectManifest
    assert RuntimeConfig is DomainRuntimeConfig
    assert Job is DomainJob


def test_project_store_composes_domain_repositories():
    assert issubclass(ProjectStore, JobRepositoryMixin)
    assert issubclass(ProjectStore, NotificationRepositoryMixin)
    assert issubclass(ProjectStore, VersionRepositoryMixin)
    assert issubclass(ProjectStore, WorkflowRepositoryMixin)


def test_routes_only_depend_on_api_schemas_and_services():
    route_root = Path(__file__).parents[1] / "app" / "api" / "routes"
    for path in route_root.glob("*.py"):
        source = path.read_text("utf-8")
        assert "app.repositories" not in source, path.name
        assert "app.runtime" not in source, path.name
        assert "request.app.state" not in source, path.name
        assert "service.store" not in source, path.name


def test_application_container_wires_shared_singletons(client):
    container = client.app.state.container
    assert container.project_service.store is container.store
    assert container.runtime_service.manager is container.processes
    assert container.workflow_service.generator is container.generator
    assert container.operations_service.versioning is container.versioning


def test_main_uses_application_container_as_composition_root():
    main_path = Path(__file__).parents[1] / "app" / "main.py"
    source = main_path.read_text("utf-8")
    assert "ApplicationContainer.build(settings)" in source
    assert "app.state.container = container" in source
    assert "ProjectStore(" not in source
    assert "GenerationService(" not in source
    assert "ProcessManager(" not in source
