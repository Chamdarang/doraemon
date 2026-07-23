from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .common import now_iso
from .runtime import RuntimeConfig


class GeneratedFile(BaseModel):
    path: str = Field(pattern=r"^(back|front)/")
    content: str


class GenerationKeyFile(BaseModel):
    path: str = Field(pattern=r"^(back|front)/")
    purpose: str


class GenerationCoverage(BaseModel):
    screens: list[str] = Field(default_factory=list)
    apis: list[str] = Field(default_factory=list)
    core_flows: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    key_files: list[GenerationKeyFile] = Field(default_factory=list)


class GenerationBundle(BaseModel):
    summary: str
    files: list[GeneratedFile]
    runtime: RuntimeConfig
    coverage: GenerationCoverage = Field(default_factory=GenerationCoverage)


class BackendGeneratedFile(BaseModel):
    path: str = Field(pattern=r"^back/")
    content: str


class FrontendGeneratedFile(BaseModel):
    path: str = Field(pattern=r"^front/")
    content: str


class BackendGenerationSegment(BaseModel):
    summary: str
    files: list[BackendGeneratedFile]
    runtime: RuntimeConfig
    coverage: GenerationCoverage = Field(default_factory=GenerationCoverage)


class FrontendGenerationSegment(BaseModel):
    summary: str
    files: list[FrontendGeneratedFile]
    coverage: GenerationCoverage = Field(default_factory=GenerationCoverage)


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    apply_recommendations: bool = False
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,80}$")

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return value.strip()


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str = Field(default_factory=now_iso)


class PlanDecision(BaseModel):
    category: str
    choice: str
    rationale: str
    confirmed: bool = False


class ProjectStructureItem(BaseModel):
    path: str
    purpose: str


class ImplementationPlan(BaseModel):
    architecture: str
    technology_choices: list[PlanDecision]
    components: list[str]
    directories: list[ProjectStructureItem]
    data_and_state: str
    api_and_integrations: str
    runtime_and_configuration: str
    testing_strategy: str


class PlanDraft(BaseModel):
    reply: str
    stage: Literal["discovery", "design", "technical", "review"]
    decisions: list[PlanDecision] = []
    open_questions: list[str] = []
    implementation_plan: ImplementationPlan | None = None
    ready_to_generate: bool = False
    specification: str | None = None
    service_specification: str | None = None
    technical_specification: str | None = None


class ProjectPlan(BaseModel):
    draft: PlanDraft
    approved: bool = False
    updated_at: str = Field(default_factory=now_iso)


class PlanningExchange(BaseModel):
    user_message: ChatMessage
    assistant_message: ChatMessage
    plan: ProjectPlan


class ImprovementChange(BaseModel):
    path: str = Field(pattern=r"^(back|front)/")
    action: Literal["add", "modify", "delete"]
    reason: str


class ImprovementDraft(BaseModel):
    reply: str
    goal: str
    analysis: str
    changes: list[ImprovementChange] = []
    acceptance_criteria: list[str] = []
    open_questions: list[str] = []
    ready_to_apply: bool = False


class ImprovementPlan(BaseModel):
    draft: ImprovementDraft
    approved: bool = False
    applied_at: str | None = None
    updated_at: str = Field(default_factory=now_iso)


class ImprovementExchange(BaseModel):
    user_message: ChatMessage
    assistant_message: ChatMessage
    plan: ImprovementPlan


class ImprovementFile(BaseModel):
    path: str = Field(pattern=r"^(back|front)/")
    content: str


class ImprovementBundle(BaseModel):
    summary: str
    files: list[ImprovementFile]
    deleted_files: list[str] = []
    runtime: RuntimeConfig | None = None


class JobStatus(StrEnum):
    queued = "queued"
    planning = "planning"
    generating = "generating"
    writing = "writing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Job(BaseModel):
    id: str
    project_id: str
    status: JobStatus = JobStatus.queued
    message: str = "생성 대기 중"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    error: str | None = None
    kind: Literal["generation", "improvement", "repair"] = "generation"
    request_content: str | None = None
    interrupted: bool = False
    retry_available: bool | None = None
    cached_result_available: bool = False
    diagnostics: list[str] = []
    generation_report: GenerationCoverage | None = None

    @model_validator(mode="after")
    def infer_legacy_retry_state(self):
        if self.retry_available is None:
            self.retry_available = self.status in {JobStatus.failed, JobStatus.cancelled}
        return self


class RepairRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class SpecificationUpdate(BaseModel):
    service_specification: str = Field(min_length=20, max_length=100_000)
    technical_specification: str = Field(min_length=20, max_length=100_000)
