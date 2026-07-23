import asyncio
import hashlib
import json
import re
import shutil
import socket
from pathlib import Path

from app.schemas import InfrastructureLogs, InfrastructureOverview, InfrastructurePortSetting, InfrastructureServiceState
from app.repositories.store import ProjectStore


class InfrastructureService:
    COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")

    def __init__(self, store: ProjectStore):
        self.store = store

    async def overview(self, project_id: str) -> InfrastructureOverview:
        project = self.store.get(project_id)
        docker = shutil.which("docker.exe") or shutil.which("docker")
        services: list[InfrastructureServiceState] = []
        errors: list[str] = []
        if docker:
            for compose in self._compose_files(project_id):
                try:
                    services.extend(await self._docker_states(project_id, docker, compose))
                except ValueError as exc:
                    source = compose.relative_to(self.store.project_dir(project_id)).as_posix()
                    errors.append(f"{source}: {str(exc)[-1_000:]}")
        for item in project.runtime.external_services:
            running = await asyncio.to_thread(self._tcp_open, item.host, item.port)
            services.append(InfrastructureServiceState(
                name=item.name,
                source=f"{item.host}:{item.port}",
                kind="external",
                running=running,
                status="connected" if running else "unreachable",
                ports=[f"{item.host}:{item.port}"],
                controllable=False,
            ))
        message = ""
        if not docker and self._compose_files(project_id):
            message = "Docker 실행 파일을 찾을 수 없어 Compose 서비스를 제어할 수 없습니다."
        elif not services:
            message = "프로젝트에 선언된 Docker Compose 또는 외부 인프라가 없습니다."
        return InfrastructureOverview(
            docker_available=bool(docker),
            services=services,
            port_settings=self._port_settings(project_id),
            message=message,
            errors=errors,
        )

    async def logs(
        self,
        project_id: str,
        source: str,
        service: str,
        tail: int = 200,
    ) -> InfrastructureLogs:
        docker = shutil.which("docker.exe") or shutil.which("docker")
        if not docker:
            raise ValueError("Docker 실행 파일을 찾을 수 없습니다")
        compose = self._resolve_compose(project_id, source)
        config = await self._compose_config(project_id, docker, compose)
        if service not in config.get("services", {}):
            raise ValueError("Compose 파일에 선언되지 않은 서비스입니다")
        code, output = await self._run(
            docker,
            [
                *self._compose_arguments(project_id, compose),
                "logs",
                "--no-color",
                "--tail",
                str(tail),
                service,
            ],
            compose.parent,
            timeout=30,
        )
        if code:
            raise ValueError(output[-4_000:] or "Docker Compose 로그를 읽지 못했습니다")
        return InfrastructureLogs(source=source, service=service, logs=output[-200_000:])

    async def update_ports(self, project_id: str, values: dict[str, int]) -> InfrastructureOverview:
        defaults = self._port_defaults(project_id)
        unknown = set(values) - defaults.keys()
        if unknown:
            raise ValueError(f"Compose에 선언되지 않은 포트 변수입니다: {', '.join(sorted(unknown))}")
        if any(port < 1024 or port > 65535 for port in values.values()):
            raise ValueError("인프라 포트는 1024~65535 범위여야 합니다")
        if len(set(values.values())) != len(values):
            raise ValueError("인프라 포트는 서로 달라야 합니다")
        current = await self.overview(project_id)
        if any(item.kind == "docker" and item.running for item in current.services):
            raise ValueError("실행 중인 Docker 인프라를 먼저 중지해주세요")
        for key, port in values.items():
            if not self._port_available(port):
                raise ValueError(f"인프라 포트 {port}는 이미 사용 중입니다 ({key})")
        env = self.store.read_env(project_id)
        env.update({key: str(value) for key, value in values.items()})
        self.store.write_env(project_id, env)
        project = self.store.get(project_id)
        if "BACKEND_PORT" in values:
            project.runtime.backend_port = values["BACKEND_PORT"]
        if "FRONTEND_PORT" in values:
            project.runtime.frontend_port = values["FRONTEND_PORT"]
        self.store.save(project)
        return await self.overview(project_id)

    async def control(
        self,
        project_id: str,
        source: str,
        service: str,
        action: str,
    ) -> InfrastructureOverview:
        docker = shutil.which("docker.exe") or shutil.which("docker")
        if not docker:
            raise ValueError("Docker 실행 파일을 찾을 수 없습니다")
        compose = self._resolve_compose(project_id, source)
        await self._control_service(project_id, docker, compose, service, action)
        return await self.overview(project_id)

    async def start_dependencies(self, project_id: str) -> list[tuple[str, str]]:
        docker = shutil.which("docker.exe") or shutil.which("docker")
        if not docker:
            if self._compose_files(project_id):
                raise ValueError("필수 인프라가 있지만 Docker 실행 파일을 찾을 수 없습니다")
            return []
        root = self.store.project_dir(project_id)
        started: list[tuple[str, str]] = []
        for compose in self._compose_files(project_id):
            config = await self._compose_config(project_id, docker, compose)
            states = await self._compose_state_map(project_id, docker, compose)
            for name, spec in config.get("services", {}).items():
                if self._service_role(spec) != "dependency" or self._is_running(states.get(name, {})):
                    continue
                await self._control_service(project_id, docker, compose, name, "start", config=config)
                started.append((compose.relative_to(root).as_posix(), name))
        return started

    async def stop_dependencies(self, project_id: str) -> None:
        docker = shutil.which("docker.exe") or shutil.which("docker")
        if not docker:
            return
        for compose in self._compose_files(project_id):
            config = await self._compose_config(project_id, docker, compose)
            states = await self._compose_state_map(project_id, docker, compose)
            for name, spec in config.get("services", {}).items():
                if self._service_role(spec) == "dependency" and self._is_running(states.get(name, {})):
                    await self._control_service(project_id, docker, compose, name, "stop", config=config)

    async def rollback_started(self, project_id: str, started: list[tuple[str, str]]) -> None:
        docker = shutil.which("docker.exe") or shutil.which("docker")
        if not docker:
            return
        for source, name in reversed(started):
            compose = self._resolve_compose(project_id, source)
            await self._control_service(project_id, docker, compose, name, "stop")

    async def _control_service(
        self,
        project_id: str,
        docker: str,
        compose: Path,
        service: str,
        action: str,
        *,
        config: dict | None = None,
    ) -> None:
        config = config or await self._compose_config(project_id, docker, compose)
        services = config.get("services", {})
        if service not in services:
            raise ValueError("Compose 파일에 선언되지 않은 서비스입니다")
        arguments = self._compose_arguments(project_id, compose)
        if action == "start":
            await self._check_port_conflicts(project_id, docker, compose, service, config)
            arguments.extend(["up", "-d"])
            if services[service].get("build"):
                arguments.append("--build")
            arguments.append(service)
        else:
            arguments.extend(["stop", service])
        code, output = await self._run(docker, arguments, compose.parent, timeout=300)
        if code:
            raise ValueError(output[-4_000:] or f"Docker Compose {action} 작업에 실패했습니다")

    def _compose_files(self, project_id: str) -> list[Path]:
        root = self.store.project_dir(project_id)
        result: list[Path] = []
        seen: set[Path] = set()
        for directory in (root, root / "back", root / "front"):
            for name in self.COMPOSE_NAMES:
                path = directory / name
                if path.is_file() and path.resolve() not in seen:
                    result.append(path)
                    seen.add(path.resolve())
        # Older generated services sometimes placed Compose below back/infra or front/infra.
        # Keep those services manageable while new generations use back/compose.yaml.
        ignored = {".pocket", ".git", ".venv", "node_modules", "dist", "build"}
        for directory in (root / "back", root / "front"):
            if not directory.is_dir():
                continue
            for name in self.COMPOSE_NAMES:
                for path in directory.rglob(name):
                    if any(part in ignored for part in path.relative_to(root).parts):
                        continue
                    resolved = path.resolve()
                    if resolved not in seen:
                        result.append(path)
                        seen.add(resolved)
        return result

    def _resolve_compose(self, project_id: str, source: str) -> Path:
        root = self.store.project_dir(project_id)
        candidate = (root / source).resolve()
        allowed = {path.resolve() for path in self._compose_files(project_id)}
        if candidate not in allowed:
            raise ValueError("프로젝트에 속한 Compose 파일이 아닙니다")
        return candidate

    async def _docker_states(
        self,
        project_id: str,
        docker: str,
        compose: Path,
    ) -> list[InfrastructureServiceState]:
        config = await self._compose_config(project_id, docker, compose)
        names = list(config.get("services", {}))
        states = await self._compose_state_map(project_id, docker, compose)
        source = compose.relative_to(self.store.project_dir(project_id)).as_posix()
        return [
            InfrastructureServiceState(
                name=name,
                source=source,
                kind="docker",
                running=self._is_running(states.get(name, {})),
                status=str(states.get(name, {}).get("Status") or states.get(name, {}).get("State") or "stopped"),
                health=str(states.get(name, {}).get("Health") or ""),
                exit_code=self._exit_code(states.get(name, {})),
                ports=self._ports(states.get(name, {})),
                controllable=True,
            )
            for name in names
        ]

    @staticmethod
    def _exit_code(state: dict) -> int | None:
        value = state.get("ExitCode")
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def _compose_services(self, project_id: str, docker: str, compose: Path) -> list[str]:
        code, output = await self._run(
            docker,
            [*self._compose_arguments(project_id, compose), "config", "--services"],
            compose.parent,
            timeout=30,
        )
        if code:
            raise ValueError(output[-4_000:] or "Docker Compose 구성을 읽지 못했습니다")
        return [line.strip() for line in output.splitlines() if line.strip()]

    async def _compose_config(self, project_id: str, docker: str, compose: Path) -> dict:
        code, output = await self._run(
            docker,
            [*self._compose_arguments(project_id, compose), "config", "--format", "json"],
            compose.parent,
            timeout=30,
        )
        if code:
            raise ValueError(output[-4_000:] or "Docker Compose 구성을 읽지 못했습니다")
        try:
            start = output.find("{")
            end = output.rfind("}")
            if start < 0 or end < start:
                raise json.JSONDecodeError("JSON object not found", output, 0)
            payload = json.loads(output[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("Docker Compose 구성이 올바른 JSON으로 해석되지 않았습니다") from exc
        return payload if isinstance(payload, dict) else {}

    async def _compose_state_map(self, project_id: str, docker: str, compose: Path) -> dict[str, dict]:
        code, output = await self._run(
            docker,
            [*self._compose_arguments(project_id, compose), "ps", "--format", "json"],
            compose.parent,
            timeout=30,
        )
        return self._parse_ps(output) if code == 0 else {}

    async def _check_port_conflicts(
        self,
        project_id: str,
        docker: str,
        compose: Path,
        service: str,
        config: dict,
    ) -> None:
        states = await self._compose_state_map(project_id, docker, compose)
        targets = self._dependency_closure(config.get("services", {}), service)
        for name in targets:
            if self._is_running(states.get(name, {})):
                continue
            for item in config.get("services", {}).get(name, {}).get("ports", []):
                try:
                    published = int(item.get("published") or 0)
                except (AttributeError, TypeError, ValueError):
                    continue
                if published and not self._port_available(published):
                    raise ValueError(
                        f"인프라 포트 {published}가 이미 사용 중입니다 ({name}). "
                        "환경변수 탭에서 해당 PORT 값을 변경해주세요"
                    )

    @staticmethod
    def _dependency_closure(services: dict, service: str) -> set[str]:
        result: set[str] = set()
        pending = [service]
        while pending:
            current = pending.pop()
            if current in result or current not in services:
                continue
            result.add(current)
            depends_on = services[current].get("depends_on", {})
            pending.extend(depends_on if isinstance(depends_on, list) else depends_on.keys())
        return result

    @staticmethod
    def _service_role(spec: dict) -> str:
        labels = spec.get("labels") or {}
        if isinstance(labels, list):
            labels = dict(item.split("=", 1) for item in labels if "=" in item)
        return str(labels.get("io.pocket.role", "")) if isinstance(labels, dict) else ""

    @staticmethod
    def _is_running(state: dict) -> bool:
        return str(state.get("State", "")).lower() == "running"

    @staticmethod
    def _port_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def _compose_arguments(self, project_id: str, compose: Path) -> list[str]:
        arguments = ["compose", "--project-name", self._project_name(project_id, compose)]
        env_file = self.store.project_dir(project_id) / ".env"
        if env_file.is_file():
            arguments.extend(["--env-file", str(env_file)])
        arguments.extend(["-f", str(compose)])
        return arguments

    def _project_name(self, project_id: str, compose: Path) -> str:
        root = self.store.project_dir(project_id)
        source = compose.resolve().relative_to(root.resolve()).as_posix()
        suffix = hashlib.sha256(source.encode()).hexdigest()[:8]
        return f"pocket-{project_id[:42]}-{suffix}"

    def _port_defaults(self, project_id: str) -> dict[str, int]:
        result: dict[str, int] = {}
        pattern = re.compile(r"\$\{([A-Z_][A-Z0-9_]*_PORT):-([0-9]{4,5})\}")
        for compose in self._compose_files(project_id):
            try:
                for key, value in pattern.findall(compose.read_text("utf-8")):
                    result[key] = int(value)
            except (OSError, UnicodeError):
                continue
        return result

    def _port_settings(self, project_id: str) -> list[InfrastructurePortSetting]:
        defaults = self._port_defaults(project_id)
        saved = self.store.read_env(project_id)
        result = []
        for key, default in sorted(defaults.items()):
            try:
                value = int(saved.get(key, default))
            except (TypeError, ValueError):
                value = default
            result.append(InfrastructurePortSetting(key=key, value=value, default=default))
        return result

    @staticmethod
    async def _run(
        executable: str,
        arguments: list[str],
        cwd: Path,
        timeout: int,
    ) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise ValueError("Docker Compose 명령 시간이 초과되었습니다") from None
        return process.returncode or 0, output.decode("utf-8", errors="replace")

    @staticmethod
    def _parse_ps(output: str) -> dict[str, dict]:
        if not output.strip():
            return {}
        try:
            payload = json.loads(output)
            rows = payload if isinstance(payload, list) else [payload]
        except json.JSONDecodeError:
            rows = []
            for line in output.splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {
            str(row.get("Service") or row.get("Name")): row
            for row in rows
            if isinstance(row, dict) and (row.get("Service") or row.get("Name"))
        }

    @staticmethod
    def _ports(state: dict) -> list[str]:
        publishers = state.get("Publishers") or []
        if not isinstance(publishers, list):
            return []
        result = []
        for item in publishers:
            if not isinstance(item, dict):
                continue
            target = item.get("TargetPort")
            published = item.get("PublishedPort")
            result.append(f"{published}:{target}" if published else str(target))
        return result

    @staticmethod
    def _tcp_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.7):
                return True
        except OSError:
            return False
