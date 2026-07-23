from typing import Literal

from pydantic import BaseModel, Field

from .common import now_iso


class EnvironmentVariableSpec(BaseModel):
    key: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    description: str
    required: bool = False
    secret: bool = False
    client_exposed: bool = False
    format: Literal["text", "url", "integer", "boolean", "json"] = "text"
    restart_required: bool = True


class HealthCheckSpec(BaseModel):
    name: str
    target: Literal["backend", "frontend"]
    path: str = Field(default="/", pattern=r"^/")
    expected_status: int = Field(default=200, ge=100, le=599)
    timeout_seconds: int = Field(default=5, ge=1, le=30)


class ExternalServiceSpec(BaseModel):
    name: str
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    required: bool = True


class RuntimeConfig(BaseModel):
    backend_command: list[str] = ["python", "-m", "uvicorn", "app.main:app", "--port", "8001"]
    frontend_command: list[str] = ["npm", "run", "dev", "--", "--port", "5174"]
    backend_port: int = Field(default=8001, ge=1024, le=65535)
    frontend_port: int = Field(default=5174, ge=1024, le=65535)
    startup_timeout_seconds: int = Field(default=30, ge=3, le=180)
    environment: list[EnvironmentVariableSpec] = []
    health_checks: list[HealthCheckSpec] = []
    external_services: list[ExternalServiceSpec] = []


class EnvironmentUpdate(BaseModel):
    values: dict[str, str]


class RuntimePortsUpdate(BaseModel):
    backend_port: int = Field(ge=1024, le=65535)
    frontend_port: int = Field(ge=1024, le=65535)


class ProcessState(BaseModel):
    target: Literal["backend", "frontend"]
    running: bool
    pid: int | None = None
    port: int | None = None
    started_at: str | None = None
    phase: Literal["stopped", "starting", "ready", "error"] = "stopped"
    message: str | None = None
    command: list[str] = []


class HealthCheckResult(BaseModel):
    name: str
    target: Literal["backend", "frontend"]
    url: str
    healthy: bool
    status_code: int | None = None
    error: str | None = None
    checked_at: str = Field(default_factory=now_iso)


class ProjectOverview(BaseModel):
    project_id: str
    backend_running: bool = False
    frontend_running: bool = False
    missing_environment: list[str] = []
    health: list[HealthCheckResult] = []
