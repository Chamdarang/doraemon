import json
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.schemas import EnvironmentVariableSpec, ProjectManifest
from app.repositories.store import ProjectStore


class ProjectImportService:
    MAX_FILES = 5_000
    MAX_EXPANDED_BYTES = 500_000_000
    MAX_MEMBER_BYTES = 100_000_000
    MAX_COMPRESSION_RATIO = 1_000
    WINDOWS_RESERVED_NAMES = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
    IGNORED = {
        ".git",
        ".pocket",
        ".venv",
        "node_modules",
        "dist",
        "build",
        "coverage",
        "__pycache__",
        ".next",
        "target",
        "__MACOSX",
    }

    def __init__(self, store: ProjectStore):
        self.store = store

    def import_archive(self, name: str, description: str, archive_path: Path) -> ProjectManifest:
        staging = self.store.root / ".imports" / uuid4().hex
        project = None
        try:
            self._extract(archive_path, staging)
            source = self._content_root(staging)
            layout = self._layout(source)
            project = self.store.create(name, description)
            root = self.store.project_dir(project.id)
            for target, source_dir in layout.items():
                destination = root / target
                shutil.rmtree(destination)
                shutil.copytree(source_dir, destination)
            for target in ({"back", "front"} - layout.keys()):
                (root / target).mkdir(exist_ok=True)
            project.runtime.backend_command = self._backend_command(root / "back", project.runtime.backend_port)
            project.runtime.frontend_command = self._frontend_command(root / "front", project.runtime.frontend_port)
            self.store.save(project)
            project.runtime.environment = [
                EnvironmentVariableSpec(
                    key=key,
                    description="가져온 코드에서 발견된 환경변수",
                    required=False,
                )
                for key in sorted(self.store.discover_env_keys(project.id))
            ]
            project.status = "ready"
            project.last_error = None
            self.store.save(project)
            return project
        except Exception:
            if project is not None:
                shutil.rmtree(self.store.project_dir(project.id), ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _extract(self, archive_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True)
        seen: set[str] = set()
        files = 0
        expanded = 0
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                name = member.filename.replace("\\", "/")
                path = PurePosixPath(name)
                if (
                    not name
                    or path.is_absolute()
                    or ".." in path.parts
                    or any(":" in part for part in path.parts)
                    or any(self._unsafe_path_part(part) for part in path.parts)
                    or member.flag_bits & 0x1
                    or stat.S_ISLNK(member.external_attr >> 16)
                ):
                    raise ValueError(f"안전하지 않은 ZIP 항목입니다: {name}")
                if any(part in self.IGNORED or part.startswith(".env") for part in path.parts):
                    continue
                key = "/".join(part.casefold() for part in path.parts)
                if key in seen:
                    raise ValueError(f"중복된 ZIP 경로입니다: {name}")
                seen.add(key)
                if member.is_dir():
                    continue
                if (
                    member.file_size > self.MAX_MEMBER_BYTES
                    or (member.file_size > 0 and member.compress_size == 0)
                    or (
                        member.compress_size > 0
                        and member.file_size / member.compress_size > self.MAX_COMPRESSION_RATIO
                    )
                ):
                    raise ValueError(f"ZIP 파일의 압축 비율 또는 단일 파일 크기가 허용 범위를 넘었습니다: {name}")
                files += 1
                expanded += member.file_size
                if files > self.MAX_FILES or expanded > self.MAX_EXPANDED_BYTES:
                    raise ValueError("ZIP의 파일 수 또는 압축 해제 크기가 허용 범위를 넘었습니다")
                target = destination.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=65_536)
        if files == 0:
            raise ValueError("가져올 소스 파일이 없는 ZIP입니다")

    @classmethod
    def _unsafe_path_part(cls, part: str) -> bool:
        if not part or part.endswith((" ", ".")) or len(part) > 255:
            return True
        if any(ord(character) < 32 for character in part):
            return True
        return part.split(".", 1)[0].upper() in cls.WINDOWS_RESERVED_NAMES

    @staticmethod
    def _content_root(staging: Path) -> Path:
        entries = list(staging.iterdir())
        return entries[0] if len(entries) == 1 and entries[0].is_dir() else staging

    def _layout(self, source: Path) -> dict[str, Path]:
        explicit = {target: source / target for target in ("back", "front") if (source / target).is_dir()}
        if explicit:
            return explicit
        backend = next((source / name for name in ("backend", "server", "api") if (source / name).is_dir()), None)
        frontend = next((source / name for name in ("frontend", "client", "web") if (source / name).is_dir()), None)
        if backend and frontend:
            return {"back": backend, "front": frontend}
        return {"front" if self._looks_frontend(source) else "back": source}

    @staticmethod
    def _package(root: Path) -> dict:
        path = root / "package.json"
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _looks_frontend(self, root: Path) -> bool:
        package = self._package(root)
        dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        return bool({"react", "next", "vue", "svelte", "@angular/core"} & dependencies.keys())

    def _frontend_command(self, root: Path, port: int) -> list[str]:
        package = self._package(root)
        scripts = package.get("scripts", {})
        script = "dev" if "dev" in scripts else "start" if "start" in scripts else None
        if not script:
            return []
        manager = self._package_manager(root)
        dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        command = [*manager, "run", script]
        if "next" in dependencies:
            return [*command, "--", "--hostname", "0.0.0.0", "--port", str(port)]
        if "vite" in dependencies:
            return [*command, "--", "--host", "0.0.0.0", "--port", str(port)]
        return command

    def _backend_command(self, root: Path, port: int) -> list[str]:
        package = self._package(root)
        scripts = package.get("scripts", {})
        script = "dev" if "dev" in scripts else "start" if "start" in scripts else None
        if script:
            return [*self._package_manager(root), "run", script]
        if (root / "manage.py").is_file():
            return ["python", "manage.py", "runserver", "0.0.0.0:8001"]
        for path in root.rglob("*.py"):
            if any(part in self.IGNORED for part in path.parts):
                continue
            try:
                text = path.read_text("utf-8", errors="replace")
            except OSError:
                continue
            match = re.search(r"^(\w+)\s*=\s*FastAPI\s*\(", text, re.MULTILINE)
            if match:
                module = path.relative_to(root).with_suffix("").as_posix().replace("/", ".")
                return ["python", "-m", "uvicorn", f"{module}:{match.group(1)}", "--host", "0.0.0.0", "--port", str(port)]
        if (root / "go.mod").is_file():
            return ["go", "run", "."]
        if (root / "pom.xml").is_file():
            return ["mvn", "spring-boot:run"]
        if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
            return ["gradle", "bootRun"]
        return []

    @staticmethod
    def _package_manager(root: Path) -> list[str]:
        if (root / "pnpm-lock.yaml").is_file():
            return ["pnpm"]
        if (root / "yarn.lock").is_file():
            return ["yarn"]
        if (root / "bun.lock").is_file() or (root / "bun.lockb").is_file():
            return ["bun"]
        return ["npm"]
