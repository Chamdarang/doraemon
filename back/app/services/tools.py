import json
import re
import socket
import sqlite3
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from uuid import uuid4

from app.schemas import ApiProbeRequest, ApiProbeResult, DiagnosticItem, DiagnosticReport, SqliteDatabase, TechnologyStack
from app.repositories.store import ProjectStore


class ProjectToolsService:
    IGNORED = {"node_modules", ".venv", "dist", "build", "__pycache__", ".next", ".pocket", "coverage"}

    def __init__(self, store: ProjectStore):
        self.store = store

    def api_probe(self, project_id: str, payload: ApiProbeRequest) -> ApiProbeResult:
        project = self.store.get(project_id)
        port = project.runtime.backend_port if payload.target == "backend" else project.runtime.frontend_port
        url = f"http://127.0.0.1:{port}{payload.path}"
        data = None if payload.body is None else json.dumps(payload.body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=payload.method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read(100_000).decode("utf-8", errors="replace")
                return ApiProbeResult(url=url, status_code=response.status, headers=dict(response.headers.items()), body=body)
        except urllib.error.HTTPError as exc:
            return ApiProbeResult(url=url, status_code=exc.code, headers=dict(exc.headers.items()), body=exc.read(100_000).decode("utf-8", errors="replace"))

    def diagnostics(self, project_id: str) -> DiagnosticReport:
        project = self.store.get(project_id)
        root = self.store.project_dir(project_id)
        security: list[DiagnosticItem] = []
        for path in self._source_files(root):
            text = path.read_text("utf-8", errors="replace")
            rel = path.relative_to(root).as_posix()
            if re.search(r"(?:sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----)", text):
                security.append(DiagnosticItem(level="error", category="secret", message=f"하드코딩된 비밀값 의심: {rel}"))
            if re.search(r"allow_origins\s*=\s*\[?['\"]\*", text):
                security.append(DiagnosticItem(level="warning", category="cors", message=f"전체 Origin 허용 의심: {rel}"))
        declared = {item.key for item in project.runtime.environment}
        discovered = self.store.discover_env_keys(project_id)
        consistency = [DiagnosticItem(level="warning", category="environment", message=f"코드에서 사용하지만 명세에 없는 환경변수: {key}") for key in sorted(discovered - declared)]
        external = []
        for service in project.runtime.external_services:
            try:
                with socket.create_connection((service.host, service.port), timeout=2):
                    external.append(DiagnosticItem(level="info", category="external", message=f"{service.name} 연결 가능 ({service.host}:{service.port})"))
            except OSError:
                level = "error" if service.required else "warning"
                external.append(DiagnosticItem(level=level, category="external", message=f"{service.name} 연결 실패 ({service.host}:{service.port})"))
        return DiagnosticReport(security=security, consistency=consistency, external_services=external)

    def technology_stack(self, project_id: str) -> TechnologyStack:
        project = self.store.get(project_id)
        root = self.store.project_dir(project_id)
        backend: set[str] = set()
        frontend: set[str] = set()
        infrastructure = {item.name for item in project.runtime.external_services}
        requirements = root / "back" / "requirements.txt"
        backend_text = requirements.read_text("utf-8", errors="replace").lower() if requirements.is_file() else ""
        command = " ".join(project.runtime.backend_command).lower()
        for marker, label in (("fastapi", "FastAPI"), ("django", "Django"), ("flask", "Flask"), ("sqlalchemy", "SQLAlchemy"), ("alembic", "Alembic")):
            if marker in backend_text or marker in command:
                backend.add(label)
        if any(marker in backend_text for marker in ("pymysql", "mysqlclient", "mysql-connector", "aiomysql", "asyncmy")):
            infrastructure.add("MySQL")
        if any(marker in backend_text for marker in ("psycopg", "asyncpg", "pg8000")):
            infrastructure.add("PostgreSQL")
        if any(marker in backend_text for marker in ("pymongo", "motor")):
            infrastructure.add("MongoDB")
        if any(marker in backend_text for marker in ("aio-pika", "pika")):
            infrastructure.add("RabbitMQ")
        if "redis" in backend_text:
            infrastructure.add("Redis")
        if "aiosqlite" in backend_text:
            infrastructure.add("SQLite")
        java_manifests = [root / "back" / name for name in ("pom.xml", "build.gradle", "build.gradle.kts")]
        java_text = "\n".join(path.read_text("utf-8", errors="replace").lower() for path in java_manifests if path.is_file())
        if java_text:
            backend.add("Java / Spring")
            for marker, label in (
                ("postgresql", "PostgreSQL"),
                ("mysql-connector", "MySQL"),
                ("data-redis", "Redis"),
                ("spring-rabbit", "RabbitMQ"),
                ("amqp", "RabbitMQ"),
                ("data-mongodb", "MongoDB"),
                ("sqlite-jdbc", "SQLite"),
            ):
                if marker in java_text:
                    infrastructure.add(label)
        go_mod = root / "back" / "go.mod"
        go_text = go_mod.read_text("utf-8", errors="replace").lower() if go_mod.is_file() else ""
        if go_text:
            backend.add("Go")
            for marker, label in (
                ("jackc/pgx", "PostgreSQL"),
                ("lib/pq", "PostgreSQL"),
                ("go-sql-driver/mysql", "MySQL"),
                ("redis/go-redis", "Redis"),
                ("rabbitmq/amqp091-go", "RabbitMQ"),
                ("mongo-driver", "MongoDB"),
                ("mattn/go-sqlite3", "SQLite"),
                ("modernc.org/sqlite", "SQLite"),
            ):
                if marker in go_text:
                    infrastructure.add(label)
        cargo = root / "back" / "Cargo.toml"
        cargo_text = cargo.read_text("utf-8", errors="replace").lower() if cargo.is_file() else ""
        if cargo_text:
            backend.add("Rust")
            for marker, label in (
                ("sqlx", "SQL database"),
                ("tokio-postgres", "PostgreSQL"),
                ("mysql_async", "MySQL"),
                ("redis", "Redis"),
                ("lapin", "RabbitMQ"),
                ("mongodb", "MongoDB"),
                ("rusqlite", "SQLite"),
            ):
                if marker in cargo_text:
                    infrastructure.add(label)
        backend_dependencies = self._package_dependencies(root / "back" / "package.json")
        if backend_dependencies is not None:
            backend.add("Node.js")
            for name, label in (
                ("typescript", "TypeScript"),
                ("express", "Express"),
                ("fastify", "Fastify"),
                ("@nestjs/core", "NestJS"),
                ("koa", "Koa"),
                ("hono", "Hono"),
                ("@prisma/client", "Prisma"),
                ("sequelize", "Sequelize"),
                ("typeorm", "TypeORM"),
                ("drizzle-orm", "Drizzle ORM"),
            ):
                if name in backend_dependencies:
                    backend.add(label)
            if "mysql2" in backend_dependencies or "mysql" in backend_dependencies:
                infrastructure.add("MySQL")
            if "pg" in backend_dependencies or "postgres" in backend_dependencies:
                infrastructure.add("PostgreSQL")
            if "mongodb" in backend_dependencies or "mongoose" in backend_dependencies:
                infrastructure.add("MongoDB")
            if "better-sqlite3" in backend_dependencies or "sqlite3" in backend_dependencies:
                infrastructure.add("SQLite")
            if "redis" in backend_dependencies or "ioredis" in backend_dependencies:
                infrastructure.add("Redis")
            if "amqplib" in backend_dependencies:
                infrastructure.add("RabbitMQ")
        package = root / "front" / "package.json"
        frontend_dependencies = self._package_dependencies(package)
        if frontend_dependencies is not None:
            for name, label in (("react", "React"), ("next", "Next.js"), ("vite", "Vite"), ("vue", "Vue"), ("svelte", "Svelte"), ("typescript", "TypeScript"), ("tailwindcss", "Tailwind CSS")):
                if name in frontend_dependencies:
                    frontend.add(label)
        for path in self._deployment_files(root):
            infrastructure.add("Docker")
            if not (path.name.lower().startswith("compose.") or path.name.lower().startswith("docker-compose.")):
                continue
            text = path.read_text("utf-8", errors="replace").lower()
            for markers, label in (
                (("postgres:", "postgresql:"), "PostgreSQL"),
                (("mysql:", "mariadb:"), "MySQL"),
                (("redis:",), "Redis"),
                (("rabbitmq:",), "RabbitMQ"),
                (("mongo:", "mongodb:"), "MongoDB"),
            ):
                if any(marker in text for marker in markers):
                    infrastructure.add(label)
        if any(path.is_file() for pattern in ("*.db", "*.sqlite", "*.sqlite3") for path in root.rglob(pattern)):
            infrastructure.add("SQLite")
        return TechnologyStack(
            backend=sorted(backend) or ["탐지되지 않음"],
            frontend=sorted(frontend) or ["탐지되지 않음"],
            infrastructure=sorted(infrastructure) or ["추가 인프라 없음"],
        )

    @staticmethod
    def _package_dependencies(path: Path) -> dict[str, str] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text("utf-8"))
        except (ValueError, OSError):
            return None
        dependencies = payload.get("dependencies") or {}
        development = payload.get("devDependencies") or {}
        if not isinstance(dependencies, dict) or not isinstance(development, dict):
            return {}
        return {**dependencies, **development}

    def _deployment_files(self, root: Path):
        root = root.resolve()
        for area in ("back", "front"):
            for path in (root / area).rglob("*"):
                name = path.name.lower()
                if not (name.startswith("dockerfile") or name.startswith("compose.") or name.startswith("docker-compose.")):
                    continue
                if path.is_symlink() or not path.is_file() or any(part in self.IGNORED for part in path.parts):
                    continue
                try:
                    path.resolve(strict=True).relative_to(root)
                except (OSError, ValueError):
                    continue
                yield path

    def sqlite_databases(self, project_id: str) -> list[SqliteDatabase]:
        root = self.store.project_dir(project_id)
        result = []
        for path in root.rglob("*"):
            if not path.is_file() or any(part in self.IGNORED for part in path.parts) or path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
                continue
            try:
                with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
                    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                result.append(SqliteDatabase(path=path.relative_to(root).as_posix(), tables=tables))
            except sqlite3.Error:
                continue
        return result

    def sqlite_rows(self, project_id: str, relative_path: str, table: str, limit: int = 100) -> list[dict]:
        root = self.store.project_dir(project_id)
        path = (root / relative_path).resolve()
        if root not in path.parents or path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
            raise ValueError("허용되지 않은 SQLite 경로입니다")
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            allowed = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if table not in allowed:
                raise ValueError("테이블을 찾을 수 없습니다")
            quoted_table = table.replace('"', '""')
            return [dict(row) for row in connection.execute(f'SELECT * FROM "{quoted_table}" LIMIT ?', (min(limit, 500),))]

    def export(self, project_id: str) -> Path:
        project = self.store.get(project_id)
        root = self.store.project_dir(project_id)
        directory = self.store.root / ".exports"
        directory.mkdir(exist_ok=True)
        destination = directory / f"{project.id}-{uuid4().hex[:8]}.zip"
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in self._source_files(root, include_docs=True):
                archive.write(path, path.relative_to(root).as_posix())
        return destination

    def _source_files(self, root: Path, include_docs: bool = False):
        root = root.resolve()
        for area in ("back", "front"):
            for path in (root / area).rglob("*"):
                if path.is_symlink() or not path.is_file() or any(part in self.IGNORED for part in path.parts) or path.name.startswith(".env") or path.name.endswith((".log", ".pyc")):
                    continue
                try:
                    path.resolve(strict=True).relative_to(root)
                except (OSError, ValueError):
                    continue
                if not include_docs and path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".html", ".toml", ".yaml", ".yml"}:
                    continue
                yield path
