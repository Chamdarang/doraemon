import json

from app.core.config import Settings
from app.services.generation.contract import build_generation_input
from app.services.generation.prompts import generation_prompt
from app.schemas import ImplementationPlan, PlanDecision, PlanDraft, ProjectPlan, ProjectStructureItem
from app.services.generation.recipes import select_stack_recipes
from app.repositories.store import ProjectStore


def test_generation_input_includes_confirmed_structured_contract(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Structured generation", "확정된 구현 계약을 생성에 전달하는 서비스")
    project.llm_policy.mode = "quality"
    plan = ProjectPlan(
        draft=PlanDraft(
            reply="ready",
            stage="review",
            specification="approved specification",
            decisions=[
                PlanDecision(category="backend_stack", choice="Go + Chi", rationale="small API", confirmed=True),
                PlanDecision(category="testing", choice="not decided", rationale="pending", confirmed=False),
            ],
            implementation_plan=ImplementationPlan(
                architecture="modular monolith",
                technology_choices=[],
                components=["API", "web"],
                directories=[ProjectStructureItem(path="back/cmd/api", purpose="API entrypoint")],
                data_and_state="in memory",
                api_and_integrations="REST",
                runtime_and_configuration="local processes",
                testing_strategy="manual smoke checks",
            ),
        ),
        approved=True,
    )

    value = build_generation_input(project, plan)
    contract = json.loads(value.split("Authoritative implementation contract (JSON):\n", 1)[1])

    assert contract["generation_mode"] == "quality"
    assert contract["confirmed_decisions"] == [
        {"category": "backend_stack", "choice": "Go + Chi", "rationale": "small API"}
    ]
    assert contract["implementation_plan"]["directories"][0]["path"] == "back/cmd/api"
    assert "approved specification" in value


def test_initial_generation_modes_have_distinct_quality_instructions():
    economy = generation_prompt("economy")
    balanced = generation_prompt("balanced")
    quality = generation_prompt("quality")

    assert "coherent, runnable MVP" in economy
    assert "complete maintainable implementation" in balanced
    assert "second internal audit" in quality
    assert len({economy, balanced, quality}) == 3


def test_confirmed_common_stacks_add_compatibility_recipes():
    plan = ProjectPlan(
        draft=PlanDraft(
            reply="ready",
            stage="review",
            decisions=[
                PlanDecision(category="backend_stack", choice="Python + FastAPI", rationale="API", confirmed=True),
                PlanDecision(category="frontend_stack", choice="React + Vite + TypeScript", rationale="SPA", confirmed=True),
                PlanDecision(category="persistence", choice="MySQL", rationale="relational", confirmed=True),
                PlanDecision(category="runtime_infrastructure", choice="Docker Compose", rationale="local", confirmed=True),
                PlanDecision(category="backend_stack", choice="Spring Boot", rationale="rejected", confirmed=False),
            ],
        )
    )

    recipes = select_stack_recipes(plan)
    ids = [item["id"] for item in recipes]

    assert ids == ["python-fastapi", "react-vite-typescript", "docker-compose", "mysql-driver"]
    mysql = next(item for item in recipes if item["id"] == "mysql-driver")
    assert any("MySQLdb" in rule for rule in mysql["consistency_rules"])


def test_nextjs_frontend_does_not_imply_a_node_backend_recipe():
    plan = ProjectPlan(
        draft=PlanDraft(
            reply="ready",
            stage="review",
            decisions=[
                PlanDecision(category="frontend_stack", choice="Next.js + TypeScript", rationale="web", confirmed=True),
            ],
        )
    )

    assert [item["id"] for item in select_stack_recipes(plan)] == ["nextjs-typescript"]


def test_backend_recipe_detection_covers_node_spring_and_go():
    cases = {
        "Node.js + Fastify + TypeScript": "node-typescript-backend",
        "Java + Spring Boot": "java-spring-boot",
        "Go + Chi": "go-backend",
    }
    for choice, expected in cases.items():
        plan = ProjectPlan(
            draft=PlanDraft(
                reply="ready",
                stage="review",
                decisions=[
                    PlanDecision(category="backend_stack", choice=choice, rationale="selected", confirmed=True),
                ],
            )
        )
        assert [item["id"] for item in select_stack_recipes(plan)] == [expected]


def test_postgresql_recipe_requires_an_explicit_matching_driver():
    plan = ProjectPlan(
        draft=PlanDraft(
            reply="ready",
            stage="review",
            decisions=[
                PlanDecision(category="persistence", choice="PostgreSQL", rationale="relational", confirmed=True),
            ],
        )
    )

    recipes = select_stack_recipes(plan)

    assert [item["id"] for item in recipes] == ["postgresql-driver"]
    rules = recipes[0]["consistency_rules"]
    assert any("psycopg 3 or asyncpg" in rule for rule in rules)
    assert any("pg_isready" in rule for rule in rules)
