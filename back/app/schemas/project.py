from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .common import now_iso
from .runtime import ProcessState, ProjectOverview, RuntimeConfig
from .workflow import ChatMessage, ImprovementPlan, Job, ProjectPlan


class LlmPolicy(BaseModel):
    mode: Literal["economy", "balanced", "quality"] = "balanced"
    planning_source_limit: int = Field(default=40_000, ge=10_000, le=120_000)
    generation_source_limit: int = Field(default=70_000, ge=20_000, le=180_000)


class ProjectManifest(BaseModel):
    id: str
    name: str
    description: str
    status: Literal["draft", "generating", "ready", "error"] = "draft"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    last_error: str | None = None
    llm_policy: LlmPolicy = Field(default_factory=LlmPolicy)
    archived_at: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=10, max_length=10_000)

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, min_length=10, max_length=10_000)
    runtime: RuntimeConfig | None = None
    llm_policy: LlmPolicy | None = None


class UsageRecord(BaseModel):
    id: str
    kind: Literal["planning", "improvement_planning", "generation", "improvement_generation", "repair"]
    model: str
    provider: str = "openai"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    created_at: str = Field(default_factory=now_iso)


class UsageTotals(BaseModel):
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0


class UsageSummary(BaseModel):
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    by_kind: dict[str, UsageTotals] = {}


class VersionRecord(BaseModel):
    id: str
    project_id: str
    label: str
    source_job_id: str | None = None
    runtime: RuntimeConfig | None = None
    created_at: str = Field(default_factory=now_iso)


class CloneRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class Notification(BaseModel):
    id: str
    level: Literal["info", "success", "warning", "error"]
    title: str
    message: str
    read: bool = False
    created_at: str = Field(default_factory=now_iso)


class TrashItem(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    deleted_at: str


class ProjectWorkspace(BaseModel):
    messages: list[ChatMessage] = []
    jobs: list[Job] = []
    processes: list[ProcessState] = []
    improvement_messages: list[ChatMessage] = []
    plan: ProjectPlan | None = None
    improvement_plan: ImprovementPlan | None = None
    usage: UsageSummary = Field(default_factory=UsageSummary)
    versions: list[VersionRecord] = []
    repair_messages: list[ChatMessage] = []
    overview: ProjectOverview
    notifications: list[Notification] = []
