"""Complexity gating and deterministic merging for optional split generation."""

from app.schemas import (
    BackendGenerationSegment,
    FrontendGenerationSegment,
    GeneratedFile,
    GenerationBundle,
    GenerationCoverage,
    GenerationKeyFile,
    ProjectPlan,
)


def _component_selected(plan: ProjectPlan, category: str) -> bool:
    choices = [
        item.choice.strip().lower()
        for item in plan.draft.decisions
        if item.confirmed and item.category == category
    ]
    if not choices:
        return False
    unavailable = ("not applicable", "none", "없음", "미사용", "해당 없음")
    return any(not any(marker in choice for marker in unavailable) for choice in choices)


def should_split_generation(plan: ProjectPlan, mode: str) -> bool:
    if mode != "quality":
        return False
    if not _component_selected(plan, "backend_stack") or not _component_selected(plan, "frontend_stack"):
        return False
    draft = plan.draft
    implementation = draft.implementation_plan
    specification_size = len(draft.specification or "")
    directories = len(implementation.directories) if implementation else 0
    components = len(implementation.components) if implementation else 0
    return specification_size >= 8_000 or directories >= 10 or components >= 6


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if item.strip()))


def merge_generation_segments(
    backend: BackendGenerationSegment,
    frontend: FrontendGenerationSegment,
) -> GenerationBundle:
    files = [
        *(GeneratedFile.model_validate(item.model_dump()) for item in backend.files),
        *(GeneratedFile.model_validate(item.model_dump()) for item in frontend.files),
    ]
    paths = {item.path for item in files}
    key_files: list[GenerationKeyFile] = []
    seen_paths: set[str] = set()
    for item in [*backend.coverage.key_files, *frontend.coverage.key_files]:
        if item.path in paths and item.path not in seen_paths:
            key_files.append(item)
            seen_paths.add(item.path)
    coverage = GenerationCoverage(
        screens=_unique([*backend.coverage.screens, *frontend.coverage.screens]),
        apis=_unique([*backend.coverage.apis, *frontend.coverage.apis]),
        core_flows=_unique([*backend.coverage.core_flows, *frontend.coverage.core_flows]),
        limitations=_unique([*backend.coverage.limitations, *frontend.coverage.limitations]),
        key_files=key_files,
    )
    return GenerationBundle(
        summary=f"{backend.summary} {frontend.summary}".strip(),
        files=files,
        runtime=backend.runtime,
        coverage=coverage,
    )
