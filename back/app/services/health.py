import asyncio
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.schemas import HealthCheckResult, ProjectOverview
from app.runtime.manager import ProcessManager
from app.repositories.store import ProjectStore


class HealthService:
    def __init__(self, store: ProjectStore, processes: ProcessManager):
        self.store = store
        self.processes = processes

    async def overview(self, project_id: str, probe: bool = True) -> ProjectOverview:
        project = self.store.get(project_id)
        backend = self.processes.state(project_id, "backend")
        frontend = self.processes.state(project_id, "frontend")
        missing: list[str] = []
        health = await asyncio.gather(*[
            self._check(project_id, item)
            for item in project.runtime.health_checks
            if probe and (backend.running if item.target == "backend" else frontend.running)
        ])
        return ProjectOverview(
            project_id=project_id,
            backend_running=backend.running,
            frontend_running=frontend.running,
            missing_environment=missing,
            health=list(health),
        )

    async def _check(self, project_id, spec) -> HealthCheckResult:
        project = self.store.get(project_id)
        port = project.runtime.backend_port if spec.target == "backend" else project.runtime.frontend_port
        url = f"http://127.0.0.1:{port}{spec.path}"
        try:
            status = await asyncio.to_thread(self._request_status, url, spec.timeout_seconds)
            return HealthCheckResult(name=spec.name, target=spec.target, url=url, healthy=status == spec.expected_status, status_code=status)
        except (OSError, URLError) as exc:
            return HealthCheckResult(name=spec.name, target=spec.target, url=url, healthy=False, error=str(exc))

    @staticmethod
    def _request_status(url: str, timeout: int) -> int:
        try:
            with urlopen(Request(url, method="GET"), timeout=timeout) as response:
                return response.status
        except HTTPError as exc:
            return exc.code
