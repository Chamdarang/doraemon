from typing import Literal

from pydantic import BaseModel, Field

from .project import Notification
from .runtime import ProcessState, ProjectOverview
from .workflow import Job


class MaintenanceRequest(BaseModel):
    clear_logs: bool = True
    clear_cache: bool = True
    keep_versions: int | None = Field(default=None, ge=1, le=100)


class MaintenanceSummary(BaseModel):
    disk_bytes: int
    logs_bytes: int
    cache_bytes: int
    versions_bytes: int
    version_count: int


class LogChunk(BaseModel):
    logs: str = ""
    cursor: int = 0
    log_id: str = ""
    reset: bool = False


class RuntimeSnapshot(BaseModel):
    processes: list[ProcessState] = []
    jobs: list[Job] = []
    overview: ProjectOverview
    notifications: list[Notification] = []
    logs: dict[str, LogChunk] = {}


class VersionDiffFile(BaseModel):
    path: str
    status: Literal["added", "modified", "deleted"]
    additions: int = 0
    deletions: int = 0
    diff: str = ""
    binary: bool = False
    truncated: bool = False


class VersionDiff(BaseModel):
    version_id: str
    files: list[VersionDiffFile] = []
    added: int = 0
    modified: int = 0
    deleted: int = 0
    unchanged: int = 0
    runtime_changed: bool = False
    truncated_files: int = 0


class SearchResult(BaseModel):
    kind: Literal["project", "job"]
    project_id: str
    project_name: str
    title: str
    subtitle: str = ""
    status: str = ""
    updated_at: str


class InfrastructureServiceState(BaseModel):
    name: str
    source: str
    kind: Literal["docker", "external"]
    running: bool = False
    status: str = "stopped"
    health: str = ""
    exit_code: int | None = None
    ports: list[str] = []
    controllable: bool = False


class InfrastructurePortSetting(BaseModel):
    key: str
    value: int
    default: int


class InfrastructureOverview(BaseModel):
    docker_available: bool = False
    services: list[InfrastructureServiceState] = []
    port_settings: list[InfrastructurePortSetting] = []
    message: str = ""
    errors: list[str] = []


class InfrastructureLogs(BaseModel):
    source: str
    service: str
    logs: str = ""


class InfrastructureControlRequest(BaseModel):
    source: str
    service: str
    action: Literal["start", "stop"]


class InfrastructurePortsUpdate(BaseModel):
    values: dict[str, int]


class ApiProbeRequest(BaseModel):
    target: Literal["backend", "frontend"]
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str = Field(default="/", pattern=r"^/")
    body: dict | list | str | None = None


class ApiProbeResult(BaseModel):
    url: str
    status_code: int
    headers: dict[str, str]
    body: str


class DiagnosticItem(BaseModel):
    level: Literal["info", "warning", "error"]
    category: str
    message: str


class DiagnosticReport(BaseModel):
    security: list[DiagnosticItem] = []
    consistency: list[DiagnosticItem] = []
    external_services: list[DiagnosticItem] = []


class TechnologyStack(BaseModel):
    backend: list[str] = []
    frontend: list[str] = []
    infrastructure: list[str] = []


class SqliteDatabase(BaseModel):
    path: str
    tables: list[str]


class PortConflict(BaseModel):
    port: int
    owners: list[str]


class PortChange(BaseModel):
    project_id: str
    target: Literal["backend", "frontend"]
    previous_port: int
    port: int


class PortConflictReport(BaseModel):
    conflicts: list[PortConflict] = []
    changes: list[PortChange] = []
    unresolved_projects: list[str] = []


class RecoveryEvent(BaseModel):
    path: str
    recovered_at: str


class RecoveryStatus(BaseModel):
    recovered_count: int = 0
    events: list[RecoveryEvent] = []
