import asyncio
import os
import socket
import subprocess
import sys
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import TYPE_CHECKING

from app.schemas import ProcessState, now_iso
from app.runtime.logs import ProcessLogStore
from app.runtime.command import replace_command_port
from app.runtime.adapters import RuntimeDependencyManager
from app.repositories.store import ProjectStore

if TYPE_CHECKING:
    from app.services.infrastructure import InfrastructureService


@dataclass
class ManagedProcess:
    process: asyncio.subprocess.Process
    started_at: str
    log_task: asyncio.Task[None]
    port: int


class ProcessManager:
    def __init__(self, store: ProjectStore, infrastructure: "InfrastructureService | None" = None):
        self.store = store
        self.infrastructure = infrastructure
        self.processes: dict[tuple[str, str], ManagedProcess] = {}
        self.locks: dict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)
        self.bulk_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.phases: dict[tuple[str, str], str] = {}
        self.messages: dict[tuple[str, str], str] = {}
        self.log_errors: dict[tuple[str, str], str] = {}
        self.dependencies = RuntimeDependencyManager()

    async def start(self, project_id: str, target: str) -> ProcessState:
        manifest = self.store.get(project_id)
        key = (project_id, target)
        async with self.locks[key]:
            self.phases[key] = "starting"
            self.messages[key] = "의존성과 실행 환경을 준비하고 있습니다"
            current = self.processes.get(key)
            if current and current.process.returncode is None:
                self.phases[key] = "ready"
                self.messages.pop(key, None)
                return self.state(project_id, target)
            if sys.platform == "win32":
                record = self._load_process_record(project_id, target)
                if record and self._record_owns_listener(record):
                    return self.state(project_id, target)
                if record:
                    self._delete_process_record(project_id, target)
            command = getattr(manifest.runtime, f"{target}_command")
            configured_port = getattr(manifest.runtime, f"{target}_port")
            available_port = self._available_port(configured_port)
            if available_port != configured_port:
                setattr(manifest.runtime, f"{target}_port", available_port)
                self.store.save(manifest)
            command = self._command_with_port(command, available_port, configured_port)
            cwd = self.store.project_dir(project_id) / ("back" if target == "backend" else "front")
            if not cwd.is_dir() or not command:
                raise ValueError("실행 설정 또는 서비스 폴더가 없습니다")
            logs = self.store.project_dir(project_id) / ".pocket" / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            log_path = logs / f"{target}.log"
            max_log_bytes = self.store.get_global_settings().log_max_bytes
            self._reset_log_for_start(log_path)
            handle = log_path.open("ab")
            env = os.environ.copy()
            env.update(self.store.runtime_env(project_id))
            env.setdefault("PORT", str(available_port))
            env.setdefault("POCKET_BACKEND_URL", f"http://localhost:{manifest.runtime.backend_port}")
            env.setdefault("VITE_API_URL", f"http://localhost:{manifest.runtime.backend_port}")
            try:
                await self._prepare_dependencies(cwd, handle, env)
                resolved = self.dependencies.resolve_command(cwd, command)
                if not resolved:
                    raise ValueError(
                        f"실행 파일을 찾을 수 없습니다: {command[0]}. "
                        "생성된 실행 명령과 의존성 설정을 확인해주세요"
                    )
                executable, arguments = resolved
                self.messages[key] = "프로세스를 시작하고 응답을 기다리고 있습니다"
                handle.close()
                self._rotate_log_if_needed(log_path, max_log_bytes)
                process = await asyncio.create_subprocess_exec(
                    executable,
                    *arguments,
                    cwd=cwd,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                if process.stdout is None:
                    raise ValueError("프로세스 로그 스트림을 열 수 없습니다")
                log_task = asyncio.create_task(
                    self._pump_logs(key, process.stdout, log_path, max_log_bytes)
                )
                self.processes[key] = ManagedProcess(
                    process, now_iso(), log_task, available_port
                )
                await self._wait_until_ready(
                    manifest,
                    target,
                    process,
                    available_port,
                    manifest.runtime.startup_timeout_seconds,
                )
            except Exception as exc:
                if "process" in locals() and process.returncode is None:
                    await self._terminate_process(process)
                if "log_task" in locals():
                    await log_task
                self.processes.pop(key, None)
                self.phases[key] = "error"
                detail = self._startup_detail(log_path)
                self.messages[key] = f"{exc}{detail}"
                if not handle.closed:
                    handle.close()
                raise ValueError(self.messages[key]) from exc
            self.phases[key] = "ready"
            self.messages.pop(key, None)
            listener_pid = self._windows_listener_pid(available_port) if sys.platform == "win32" else process.pid
            self._save_process_record(project_id, target, process.pid, available_port, listener_pid)
            return self.state(project_id, target)

    @staticmethod
    def _available_port(preferred: int) -> int:
        port = preferred
        while port <= 65535:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    port += 1
        raise ValueError("사용 가능한 포트를 찾을 수 없습니다")

    @staticmethod
    def _command_with_port(
        command: list[str], port: int, configured_port: int | None = None
    ) -> list[str]:
        return replace_command_port(command, port, configured_port)

    @staticmethod
    def _resolve_project_executable(cwd, value: str) -> str | None:
        """Compatibility helper retained for callers that only need the executable path."""
        resolved = RuntimeDependencyManager.resolve_command(Path(cwd), [value])
        return resolved[0] if resolved else None

    async def _prepare_dependencies(self, cwd, log_handle, env: dict[str, str]) -> None:
        await self.dependencies.prepare(Path(cwd), log_handle, env)

    async def _pump_logs(
        self,
        key: tuple[str, str],
        reader: asyncio.StreamReader,
        path: Path,
        max_bytes: int,
    ) -> None:
        try:
            while chunk := await reader.read(16_384):
                await asyncio.to_thread(self._append_log_chunk, path, chunk, max_bytes)
        except OSError as exc:
            self.log_errors[key] = f"로그를 저장하지 못했습니다: {exc}"

    @classmethod
    def _append_log_chunk(cls, path: Path, chunk: bytes, max_bytes: int) -> None:
        ProcessLogStore.append_chunk(path, chunk, max_bytes)

    @classmethod
    def _rotate_log_if_needed(cls, path: Path, max_bytes: int) -> None:
        ProcessLogStore.rotate_if_needed(path, max_bytes)

    @classmethod
    def _reset_log_for_start(cls, path: Path) -> None:
        ProcessLogStore.reset_for_start(path)

    @staticmethod
    def _rotate_log(path: Path) -> None:
        ProcessLogStore.rotate(path)

    async def _wait_until_ready(
        self,
        manifest,
        target: str,
        process: asyncio.subprocess.Process,
        port: int,
        timeout_seconds: int,
    ) -> None:
        checks = [item for item in manifest.runtime.health_checks if item.target == target]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        last_detail = "포트 응답을 기다리는 중"
        while loop.time() < deadline:
            if process.returncode is not None:
                raise ValueError(f"{target} 프로세스가 시작 직후 종료됐습니다")
            if checks:
                results = await asyncio.gather(*[
                    asyncio.to_thread(
                        self._http_status,
                        f"http://127.0.0.1:{port}{item.path}",
                        min(item.timeout_seconds, 2),
                    )
                    for item in checks
                ])
                failures = [
                    f"{item.name}: {status if status is not None else '연결 실패'}"
                    for item, status in zip(checks, results, strict=True)
                    if status != item.expected_status
                ]
                if not failures:
                    return
                last_detail = ", ".join(failures)
            elif await asyncio.to_thread(self._port_accepts_connections, port):
                return
            await asyncio.sleep(0.3)
        raise ValueError(
            f"{target} 서비스가 {timeout_seconds}초 안에 준비되지 않았습니다 ({last_detail})"
        )

    @staticmethod
    def _port_accepts_connections(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            return False

    @staticmethod
    def _http_status(url: str, timeout: int) -> int | None:
        try:
            with urlopen(Request(url, method="GET"), timeout=timeout) as response:
                return response.status
        except HTTPError as exc:
            return exc.code
        except (OSError, URLError):
            return None

    @staticmethod
    def _startup_detail(log_path: Path) -> str:
        return ProcessLogStore.startup_detail(log_path)

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if sys.platform == "win32":
            await self._terminate_windows_tree(process.pid)
        else:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=8)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def stop(self, project_id: str, target: str) -> ProcessState:
        key = (project_id, target)
        async with self.locks[key]:
            managed = self.processes.get(key)
            record = self._load_process_record(project_id, target) if sys.platform == "win32" else None
            if managed and managed.process.returncode is None:
                await self._terminate_process(managed.process)
                await managed.log_task
            if record and self._record_owns_listener(record):
                # npm/corepack can leave a detached Node child behind after its parent exits.
                # Only terminate the listener when the saved record still proves ownership.
                await self._terminate_windows_tree(int(record["listener_pid"]))
                await asyncio.sleep(0.1)
                if self._record_owns_listener(record):
                    raise ValueError(
                        f"{target} 포트 {record['port']}의 프로세스를 종료하지 못했습니다 "
                        f"(PID {record['listener_pid']})"
                    )
            self.processes.pop(key, None)
            self.phases.pop(key, None)
            self.messages.pop(key, None)
            self.log_errors.pop(key, None)
            self._delete_process_record(project_id, target)
            return self.state(project_id, target)

    async def start_all(self, project_id: str) -> list[ProcessState]:
        """Start both service targets and roll back only targets started by this call."""
        async with self.bulk_locks[project_id]:
            initial = {
                target: self.state(project_id, target)
                for target in ("backend", "frontend")
            }
            targets = [target for target, state in initial.items() if state.command]
            was_running = {target: state.running for target, state in initial.items()}
            started: list[str] = []
            infrastructure_started: list[tuple[str, str]] = []
            try:
                if self.infrastructure:
                    infrastructure_started = await self.infrastructure.start_dependencies(project_id)
                for target in targets:
                    state = await self.start(project_id, target)
                    if not was_running[target] and state.running:
                        started.append(target)
            except (OSError, ValueError) as exc:
                rollback_errors: list[str] = []
                for target in reversed(started):
                    try:
                        await self.stop(project_id, target)
                    except (OSError, ValueError) as rollback_exc:
                        rollback_errors.append(f"{target}: {rollback_exc}")
                if self.infrastructure and infrastructure_started:
                    try:
                        await self.infrastructure.rollback_started(project_id, infrastructure_started)
                    except (OSError, ValueError) as rollback_exc:
                        rollback_errors.append(f"infrastructure: {rollback_exc}")
                rollback_detail = (
                    f" (롤백 실패: {', '.join(rollback_errors)})" if rollback_errors else ""
                )
                raise ValueError(f"전체 실행에 실패했습니다: {exc}{rollback_detail}") from exc
            return [self.state(project_id, target) for target in ("backend", "frontend")]

    async def stop_all(self, project_id: str) -> list[ProcessState]:
        """Stop both targets, continuing with the other target after a partial failure."""
        async with self.bulk_locks[project_id]:
            errors: list[str] = []
            for target in ("frontend", "backend"):
                try:
                    if self.state(project_id, target).running:
                        await self.stop(project_id, target)
                except (OSError, ValueError) as exc:
                    errors.append(f"{target}: {exc}")
            if self.infrastructure:
                try:
                    await self.infrastructure.stop_dependencies(project_id)
                except (OSError, ValueError) as exc:
                    errors.append(f"infrastructure: {exc}")
            if errors:
                raise ValueError(f"전체 중지 중 일부 작업에 실패했습니다: {', '.join(errors)}")
            return [self.state(project_id, target) for target in ("backend", "frontend")]

    async def _terminate_windows_tree(self, pid: int) -> None:
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()

    def _process_record_path(self, project_id: str, target: str):
        directory = self.store.project_dir(project_id) / ".pocket" / "processes"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{target}.json"

    def _save_process_record(self, project_id: str, target: str, pid: int, port: int, listener_pid: int | None) -> None:
        self._process_record_path(project_id, target).write_text(
            json.dumps({"pid": pid, "listener_pid": listener_pid, "port": port, "started_at": now_iso()}),
            encoding="utf-8",
        )

    def _load_process_record(self, project_id: str, target: str) -> dict | None:
        path = self._process_record_path(project_id, target)
        try:
            return json.loads(path.read_text("utf-8")) if path.is_file() else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _delete_process_record(self, project_id: str, target: str) -> None:
        path = self._process_record_path(project_id, target)
        if path.exists():
            path.unlink()

    def _record_owns_listener(self, record: dict) -> bool:
        try:
            listener_pid = int(record.get("listener_pid") or 0)
            port = int(record["port"])
        except (TypeError, ValueError, KeyError):
            return False
        return listener_pid > 0 and self._windows_listener_pid(port) == listener_pid

    @staticmethod
    def _windows_listener_pid(port: int) -> int | None:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) >= 5 and columns[0] == "TCP" and columns[1].endswith(f":{port}") and columns[3] == "LISTENING":
                try:
                    return int(columns[4])
                except ValueError:
                    return None
        return None

    def state(self, project_id: str, target: str) -> ProcessState:
        manifest = self.store.get(project_id)
        managed = self.processes.get((project_id, target))
        running = bool(managed and managed.process.returncode is None)
        if managed and not running:
            self.processes.pop((project_id, target), None)
            self.phases[(project_id, target)] = "error"
            self.messages[(project_id, target)] = (
                f"프로세스가 종료되었습니다 (exit code {managed.process.returncode})"
            )
        if not running and sys.platform == "win32":
            record = self._load_process_record(project_id, target)
            if record and self._record_owns_listener(record):
                return ProcessState(
                    target=target,
                    running=True,
                    pid=int(record["listener_pid"]),
                    port=int(record["port"]),
                    started_at=record.get("started_at"),
                    phase="ready",
                    command=getattr(manifest.runtime, f"{target}_command"),
                )
            if record:
                self._delete_process_record(project_id, target)
        return ProcessState(
            target=target,
            running=running,
            pid=managed.process.pid if running else None,
            port=getattr(manifest.runtime, f"{target}_port"),
            started_at=managed.started_at if running else None,
            phase=self.phases.get((project_id, target), "ready" if running else "stopped"),
            message=self.messages.get((project_id, target)) or self.log_errors.get((project_id, target)),
            command=getattr(manifest.runtime, f"{target}_command"),
        )

    def logs(self, project_id: str, target: str, tail: int = 300) -> str:
        path = self.store.project_dir(project_id) / ".pocket" / "logs" / f"{target}.log"
        return ProcessLogStore.tail(path, tail)

    def log_chunk(
        self,
        project_id: str,
        target: str,
        cursor: int = 0,
        log_id: str = "",
        max_bytes: int = 131_072,
    ) -> dict[str, str | int | bool]:
        path = self.store.project_dir(project_id) / ".pocket" / "logs" / f"{target}.log"
        return ProcessLogStore.chunk(path, cursor, log_id, max_bytes)

    async def shutdown(self) -> None:
        for project_id, target in list(self.processes):
            await self.stop(project_id, target)
