"""Compact, structured context for the paid initial generation request."""

import json

from app.schemas import ProjectManifest, ProjectPlan
from app.services.generation.recipes import select_stack_recipes


def build_generation_input(manifest: ProjectManifest, plan: ProjectPlan) -> str:
    draft = plan.draft
    confirmed = [
        {
            "category": item.category,
            "choice": item.choice,
            "rationale": item.rationale,
        }
        for item in draft.decisions
        if item.confirmed
    ]
    contract = {
        "generation_mode": manifest.llm_policy.mode,
        "confirmed_decisions": confirmed,
        "implementation_plan": (
            draft.implementation_plan.model_dump(mode="json")
            if draft.implementation_plan is not None
            else None
        ),
        "runtime_defaults": {
            "backend_port": manifest.runtime.backend_port,
            "frontend_port": manifest.runtime.frontend_port,
        },
        "stack_recipes": select_stack_recipes(plan),
    }
    return (
        f"Service name: {manifest.name}\n"
        f"Generation mode: {manifest.llm_policy.mode}\n"
        f"Approved specification:\n{draft.specification}\n\n"
        "Authoritative implementation contract (JSON):\n"
        f"{json.dumps(contract, ensure_ascii=False, separators=(',', ':'))}"
    )
