"""Deterministic compatibility recipes for commonly generated service stacks."""

import re

from app.schemas import ProjectPlan


def _matches(value: str, pattern: str) -> bool:
    return re.search(pattern, value, re.IGNORECASE) is not None


def select_stack_recipes(plan: ProjectPlan) -> list[dict[str, object]]:
    choices: dict[str, list[str]] = {}
    for item in plan.draft.decisions:
        if item.confirmed:
            choices.setdefault(item.category, []).append(item.choice)
    if plan.draft.implementation_plan is not None:
        for item in plan.draft.implementation_plan.technology_choices:
            if item.confirmed:
                choices.setdefault(item.category, []).append(item.choice)

    backend = " ".join(choices.get("backend_stack", [])).lower()
    frontend = " ".join(choices.get("frontend_stack", [])).lower()
    infrastructure = " ".join(choices.get("runtime_infrastructure", [])).lower()
    persistence = " ".join(choices.get("persistence", [])).lower()
    recipes: list[dict[str, object]] = []

    if _matches(backend, r"\bfastapi\b"):
        recipes.append({
            "id": "python-fastapi",
            "required_artifacts": ["back/pyproject.toml or back/requirements.txt", "importable FastAPI application module"],
            "runtime_contract": "backend_command must use the generated venv through python -m uvicorn and reference an existing module:app",
            "consistency_rules": [
                "choose exactly one primary Python dependency manifest and declare every imported package",
                "keep router/package imports valid from the back working directory",
                "provide a cheap HTTP health endpoint matching runtime.health_checks",
            ],
        })
    if _matches(backend, r"\b(node(?:\.js|js)?|express|fastify|nestjs?)\b"):
        recipes.append({
            "id": "node-typescript-backend",
            "required_artifacts": ["back/package.json", "back/tsconfig.json when TypeScript is selected", "existing server entrypoint referenced by scripts"],
            "runtime_contract": "backend_command must invoke a declared package.json script or dependency available in back/node_modules/.bin",
            "consistency_rules": [
                "declare the development runner such as tsx when a script uses it",
                "bind the server to the configured backend port and expose a matching health endpoint",
                "keep ESM/CommonJS settings consistent across package.json, tsconfig, imports, and file extensions",
            ],
        })
    if _matches(backend, r"\bspring(?:\s*boot)?\b"):
        recipes.append({
            "id": "java-spring-boot",
            "required_artifacts": ["back/pom.xml or back/build.gradle(.kts), never both", "back/src/main/java package tree", "application configuration"],
            "runtime_contract": "use mvn spring-boot:run or gradle bootRun; reference a wrapper only when its complete required wrapper files are generated",
            "consistency_rules": [
                "align Java, Spring Boot, plugin, and dependency versions",
                "match source directories, declared package names, and the main application class",
                "do not emit a fake wrapper script without the wrapper support files",
            ],
        })
    if _matches(backend, r"(?:^|[\s+/(,])(?:go|golang)(?:$|[\s+/),])"):
        recipes.append({
            "id": "go-backend",
            "required_artifacts": ["back/go.mod", "existing main package entrypoint"],
            "runtime_contract": "backend_command must use go run with an existing package path or run a generated executable",
            "consistency_rules": [
                "keep the go.mod module path and internal imports identical",
                "declare all external modules and bind to the configured backend port",
                "provide graceful startup errors and a matching health endpoint",
            ],
        })

    if _matches(frontend, r"\bnext(?:\.js|js)?\b"):
        recipes.append({
            "id": "nextjs-typescript",
            "required_artifacts": ["front/package.json", "front/tsconfig.json", "one coherent app-router or pages-router entry structure"],
            "runtime_contract": "frontend_command must invoke an existing package.json dev script and accept Doraemon's appended port argument",
            "consistency_rules": [
                "do not mix App Router and Pages Router conventions",
                "keep server-only values out of client components and never expose secret environment variables",
                "provide product-specific responsive loading, empty, error, and success states",
            ],
        })
    elif _matches(frontend, r"\b(react|vite)\b"):
        recipes.append({
            "id": "react-vite-typescript",
            "required_artifacts": ["front/package.json", "front/index.html", "front/src entrypoint", "front/vite.config.ts or .js"],
            "runtime_contract": "frontend_command must invoke the declared Vite dev script and accept Doraemon's appended --port argument",
            "consistency_rules": [
                "declare @vitejs/plugin-react when the Vite config imports it",
                "keep alias, tsconfig, import paths, and filename casing consistent",
                "when using relative /api requests, configure a development proxy to POCKET_BACKEND_URL with a safe localhost fallback",
                "build a cohesive service-specific design system rather than a generic HTML demo",
            ],
        })

    if _matches(infrastructure, r"\b(docker|compose|container)\b"):
        recipes.append({
            "id": "docker-compose",
            "required_artifacts": ["back/infra/compose.yaml", ".dockerignore in every referenced build context", "Dockerfile for each build service"],
            "runtime_contract": "Compose service roles, health checks, dependency readiness, ports, and build contexts must match Doraemon local-process runtime",
            "consistency_rules": [
                "resolve every Dockerfile COPY source inside its declared build context",
                "use variable-based published ports and safe empty substitutions for secrets",
                "label dependencies, backend, and frontend with the matching io.pocket.role",
            ],
        })
    if _matches(persistence, r"\bmysql\b"):
        recipes.append({
            "id": "mysql-driver",
            "required_artifacts": ["explicit MySQL client/ORM driver in the backend dependency manifest"],
            "runtime_contract": "database URL scheme, imported driver, migration configuration, and Compose credentials must select the same driver",
            "consistency_rules": [
                "never rely on implicit MySQLdb; explicitly choose and declare the selected driver",
                "provide a safe local database URL fallback without embedding a real secret",
            ],
        })
    if _matches(persistence, r"\b(postgres|postgresql)\b"):
        recipes.append({
            "id": "postgresql-driver",
            "required_artifacts": ["explicit PostgreSQL client/ORM driver in the backend dependency manifest"],
            "runtime_contract": "database URL scheme, imported driver, migration configuration, and Compose credentials must select the same driver",
            "consistency_rules": [
                "for Python, explicitly choose psycopg 3 or asyncpg and use the matching SQLAlchemy URL scheme; do not rely on an undeclared psycopg2",
                "for Node, declare the selected pg/ORM adapter and keep generated client steps consistent with the start command",
                "when Compose is selected, use pg_isready for dependency health and variable-based host credentials with safe local fallbacks",
                "do not expose database credentials to browser code",
            ],
        })
    return recipes
