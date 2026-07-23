import asyncio
import socket
import shutil
import sys
from io import BytesIO

import pytest

from app.core.config import Settings
from app.schemas import HealthCheckSpec, ProcessState
from app.runtime.manager import ManagedProcess, ProcessManager
from app.runtime.adapters import RuntimeDependencyManager
from app.runtime.plugins import (
    GoRuntimeAdapter,
    JavaRuntimeAdapter,
    NodeRuntimeAdapter,
    PythonRuntimeAdapter,
    RuntimeAdapterRegistry,
)
from app.repositories.store import ProjectStore


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def process_state(target: str, running: bool) -> ProcessState:
    return ProcessState(
        target=target,
        running=running,
        pid=100 if running else None,
        port=8001 if target == "backend" else 5174,
        phase="ready" if running else "stopped",
        command=["run"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_already_running", [False, True])
async def test_start_all_rolls_back_only_processes_started_by_the_call(
    tmp_path, monkeypatch, backend_already_running
):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Bulk runtime", "전체 실행 롤백을 검증합니다")
    manager = ProcessManager(store)
    running = {"backend": backend_already_running, "frontend": False}
    stopped: list[str] = []

    def fake_state(project_id, target):
        assert project_id == project.id
        return process_state(target, running[target])

    async def fake_start(project_id, target):
        assert project_id == project.id
        if target == "frontend":
            raise ValueError("frontend failed")
        running[target] = True
        return fake_state(project_id, target)

    async def fake_stop(project_id, target):
        stopped.append(target)
        running[target] = False
        return fake_state(project_id, target)

    monkeypatch.setattr(manager, "state", fake_state)
    monkeypatch.setattr(manager, "start", fake_start)
    monkeypatch.setattr(manager, "stop", fake_stop)

    with pytest.raises(ValueError, match="전체 실행에 실패했습니다"):
        await manager.start_all(project.id)

    assert stopped == ([] if backend_already_running else ["backend"])
    assert running["backend"] is backend_already_running


@pytest.mark.asyncio
async def test_stop_all_attempts_both_targets_after_partial_failure(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Bulk stop", "전체 중지의 부분 실패를 검증합니다")
    manager = ProcessManager(store)
    running = {"backend": True, "frontend": True}
    attempted: list[str] = []

    def fake_state(_project_id, target):
        return process_state(target, running[target])

    async def fake_stop(_project_id, target):
        attempted.append(target)
        if target == "frontend":
            raise OSError("cannot stop frontend")
        running[target] = False
        return fake_state(project.id, target)

    monkeypatch.setattr(manager, "state", fake_state)
    monkeypatch.setattr(manager, "stop", fake_stop)

    with pytest.raises(ValueError, match="일부 작업에 실패했습니다"):
        await manager.stop_all(project.id)

    assert attempted == ["frontend", "backend"]
    assert running == {"backend": False, "frontend": True}


@pytest.mark.asyncio
async def test_bulk_runtime_prepares_and_rolls_back_dependency_infrastructure(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Infrastructure runtime", "전체 실행이 필수 인프라를 함께 관리합니다")
    events: list[object] = []

    class FakeInfrastructure:
        async def start_dependencies(self, project_id):
            events.append(("start-infrastructure", project_id))
            return [("back/infra/compose.yaml", "db")]

        async def rollback_started(self, project_id, started):
            events.append(("rollback-infrastructure", project_id, started))

        async def stop_dependencies(self, project_id):
            events.append(("stop-infrastructure", project_id))

    manager = ProcessManager(store, FakeInfrastructure())
    running = {"backend": False, "frontend": False}

    def fake_state(_project_id, target):
        return process_state(target, running[target])

    async def fake_start(_project_id, target):
        if target == "frontend":
            raise ValueError("frontend failed")
        running[target] = True
        return fake_state(project.id, target)

    async def fake_stop(_project_id, target):
        running[target] = False
        events.append(("stop-process", target))
        return fake_state(project.id, target)

    monkeypatch.setattr(manager, "state", fake_state)
    monkeypatch.setattr(manager, "start", fake_start)
    monkeypatch.setattr(manager, "stop", fake_stop)

    with pytest.raises(ValueError, match="전체 실행에 실패했습니다"):
        await manager.start_all(project.id)

    assert events == [
        ("start-infrastructure", project.id),
        ("stop-process", "backend"),
        ("rollback-infrastructure", project.id, [("back/infra/compose.yaml", "db")]),
    ]


@pytest.mark.asyncio
async def test_windows_stop_terminates_detached_recorded_listener(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Detached frontend", "분리된 Node 자식 프로세스 종료를 검증합니다")
    manager = ProcessManager(store)
    key = (project.id, "frontend")

    class FakeProcess:
        pid = 100
        returncode = None

    log_task = asyncio.create_task(asyncio.sleep(0))
    manager.processes[key] = ManagedProcess(FakeProcess(), "now", log_task, 5174)
    record = {"pid": 100, "listener_pid": 200, "port": 5174, "started_at": "now"}
    listener_alive = True
    terminated: list[int] = []

    async def terminate_parent(_process):
        terminated.append(100)

    async def terminate_tree(pid):
        nonlocal listener_alive
        terminated.append(pid)
        if pid == 200:
            listener_alive = False

    monkeypatch.setattr("app.runtime.manager.sys.platform", "win32")
    monkeypatch.setattr(manager, "_load_process_record", lambda *_args: record)
    monkeypatch.setattr(manager, "_record_owns_listener", lambda _record: listener_alive)
    monkeypatch.setattr(manager, "_terminate_process", terminate_parent)
    monkeypatch.setattr(manager, "_terminate_windows_tree", terminate_tree)
    monkeypatch.setattr(manager, "_delete_process_record", lambda *_args: None)

    stopped = await manager.stop(project.id, "frontend")

    assert terminated == [100, 200]
    assert stopped.running is False


@pytest.mark.asyncio
async def test_windows_stop_reports_listener_that_survives_taskkill(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Stubborn frontend", "종료 실패 상태를 숨기지 않는지 검증합니다")
    manager = ProcessManager(store)
    record = {"pid": 100, "listener_pid": 200, "port": 5174, "started_at": "now"}
    deleted = False

    async def terminate_tree(_pid):
        return None

    def delete_record(*_args):
        nonlocal deleted
        deleted = True

    monkeypatch.setattr("app.runtime.manager.sys.platform", "win32")
    monkeypatch.setattr(manager, "_load_process_record", lambda *_args: record)
    monkeypatch.setattr(manager, "_record_owns_listener", lambda _record: True)
    monkeypatch.setattr(manager, "_terminate_windows_tree", terminate_tree)
    monkeypatch.setattr(manager, "_delete_process_record", delete_record)

    with pytest.raises(ValueError, match="종료하지 못했습니다"):
        await manager.stop(project.id, "frontend")

    assert deleted is False


@pytest.mark.asyncio
async def test_start_all_skips_target_without_a_command(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Single target", "실행 명령이 있는 대상만 시작합니다")
    manager = ProcessManager(store)
    started: list[str] = []

    def fake_state(_project_id, target):
        state = process_state(target, target in started)
        state.command = ["run"] if target == "backend" else []
        return state

    async def fake_start(_project_id, target):
        started.append(target)
        return fake_state(project.id, target)

    monkeypatch.setattr(manager, "state", fake_state)
    monkeypatch.setattr(manager, "start", fake_start)

    result = await manager.start_all(project.id)

    assert started == ["backend"]
    assert result[0].running is True
    assert result[1].running is False


def test_runtime_resolves_maven_and_gradle_wrappers(tmp_path):
    maven = tmp_path / ("mvnw.cmd" if sys.platform == "win32" else "mvnw")
    gradle = tmp_path / ("gradlew.bat" if sys.platform == "win32" else "gradlew")
    maven.write_text("wrapper", "utf-8")
    gradle.write_text("wrapper", "utf-8")

    resolved_maven = RuntimeDependencyManager.resolve_command(tmp_path, ["mvn", "spring-boot:run"])
    resolved_gradle = RuntimeDependencyManager.resolve_command(tmp_path, ["gradle", "bootRun"])

    assert resolved_maven == (str(maven.resolve()), ["spring-boot:run"])
    assert resolved_gradle == (str(gradle.resolve()), ["bootRun"])


@pytest.mark.parametrize(
    ("lock_name", "available", "expected_executable", "expected_arguments"),
    [
        ("package-lock.json", {"npm.cmd": "C:/tools/npm.cmd"}, "C:/tools/npm.cmd", ["install", "--no-audit", "--no-fund"]),
        ("pnpm-lock.yaml", {"corepack.cmd": "C:/tools/corepack.cmd"}, "C:/tools/corepack.cmd", ["pnpm", "install", "--frozen-lockfile"]),
        ("yarn.lock", {"yarn.cmd": "C:/tools/yarn.cmd"}, "C:/tools/yarn.cmd", ["install"]),
        ("bun.lock", {"bun": "C:/tools/bun.exe"}, "C:/tools/bun.exe", ["install", "--frozen-lockfile"]),
    ],
)
def test_node_lockfile_selects_matching_package_manager(
    tmp_path, monkeypatch, lock_name, available, expected_executable, expected_arguments
):
    (tmp_path / lock_name).write_text("lock", "utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: available.get(name))

    executable, arguments, _label = RuntimeDependencyManager._node_installer(tmp_path)

    assert executable == expected_executable
    assert arguments == expected_arguments


@pytest.mark.asyncio
async def test_go_modules_download_only_when_manifest_changes(tmp_path, monkeypatch):
    go_mod = tmp_path / "go.mod"
    go_mod.write_text("module example.test/demo\n", "utf-8")
    calls = []

    async def fake_run(executable, arguments, cwd, log_handle, env, error):
        calls.append((executable, arguments))

    manager = RuntimeDependencyManager()
    monkeypatch.setattr(shutil, "which", lambda name: "C:/tools/go.exe" if name == "go" else None)
    monkeypatch.setattr(manager, "_run", fake_run)
    log = BytesIO()

    await manager.prepare(tmp_path, log, {})
    await manager.prepare(tmp_path, log, {})
    go_mod.write_text("module example.test/demo\n\ngo 1.24\n", "utf-8")
    await manager.prepare(tmp_path, log, {})

    assert calls == [
        ("C:/tools/go.exe", ["mod", "download"]),
        ("C:/tools/go.exe", ["mod", "download"]),
    ]


def test_node_command_prefers_project_local_binary(tmp_path, monkeypatch):
    local = tmp_path / "node_modules" / ".bin" / ("vite.cmd" if sys.platform == "win32" else "vite")
    local.parent.mkdir(parents=True)
    local.write_text("local vite", "utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    resolved = RuntimeDependencyManager.resolve_command(tmp_path, ["vite", "--host"])

    assert resolved == (str(local.resolve()), ["--host"])


def test_registry_detects_every_manifest_in_a_mixed_target(tmp_path):
    for name in ("pyproject.toml", "package.json", "go.mod", "pom.xml"):
        (tmp_path / name).write_text("manifest", "utf-8")
    registry = RuntimeAdapterRegistry(
        [PythonRuntimeAdapter(), NodeRuntimeAdapter(), GoRuntimeAdapter(), JavaRuntimeAdapter()]
    )

    assert [adapter.name for adapter in registry.detected(tmp_path)] == ["python", "node", "go", "java"]


@pytest.mark.asyncio
async def test_custom_runtime_adapter_can_be_injected_without_manager_changes(tmp_path):
    calls = []

    class CustomAdapter:
        name = "custom"

        def detect(self, cwd):
            return (cwd / "custom.runtime").is_file()

        async def prepare(self, host, cwd, log_handle, env):
            calls.append((cwd, env["MODE"]))

        def resolve_command(self, cwd, command):
            return ("custom-runner", command[1:]) if command and command[0] == "custom" else None

    (tmp_path / "custom.runtime").write_text("enabled", "utf-8")
    manager = RuntimeDependencyManager(adapters=[CustomAdapter()])
    await manager.prepare(tmp_path, BytesIO(), {"MODE": "test"})

    assert calls == [(tmp_path, "test")]
    assert manager._resolve_command(tmp_path, ["custom", "serve"]) == ("custom-runner", ["serve"])


@pytest.mark.asyncio
async def test_pyproject_dependencies_are_installed_once_per_signature(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\nversion='1'", "utf-8")
    calls: list[tuple[str, list[str]]] = []

    async def fake_run(executable, arguments, cwd, log_handle, env, error):
        calls.append((str(executable), arguments))
        if arguments == ["-m", "venv", ".venv"]:
            python = cwd / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            python.parent.mkdir(parents=True)
            python.write_text("python", "utf-8")

    manager = RuntimeDependencyManager(python_executable=sys.executable)
    monkeypatch.setattr(manager, "_run", fake_run)
    log_path = tmp_path / "setup.log"
    with log_path.open("wb") as log:
        await manager.prepare(tmp_path, log, {})
        await manager.prepare(tmp_path, log, {})

    assert [arguments for _, arguments in calls] == [
        ["-m", "venv", ".venv"],
        ["-m", "pip", "install", "-e", "."],
    ]


@pytest.mark.asyncio
async def test_process_start_waits_for_real_http_readiness_and_stops_tree(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Runtime", "실제 HTTP 준비 상태와 종료 동작을 확인하는 서비스")
    port = free_port()
    project.runtime.backend_port = port
    project.runtime.backend_command = [sys.executable, "-m", "http.server", str(port)]
    project.runtime.startup_timeout_seconds = 8
    project.runtime.health_checks = [
        HealthCheckSpec(name="HTTP", target="backend", path="/", expected_status=200)
    ]
    store.save(project)
    manager = ProcessManager(store)

    started = await manager.start(project.id, "backend")
    assert started.running is True
    assert started.phase == "ready"
    assert started.pid is not None
    assert started.command == [sys.executable, "-m", "http.server", str(port)]

    stopped = await manager.stop(project.id, "backend")
    assert stopped.running is False
    assert stopped.phase == "stopped"


@pytest.mark.asyncio
async def test_failed_readiness_is_retained_in_process_state(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Broken runtime", "준비 실패 원인을 프로세스 상태에 보존하는 서비스")
    project.runtime.backend_command = [sys.executable, "-c", "raise SystemExit('boom')"]
    project.runtime.startup_timeout_seconds = 3
    store.save(project)
    manager = ProcessManager(store)
    monkeypatch.setattr(manager, "_startup_detail", lambda path: "\n\n최근 로그:\nboom")

    with pytest.raises(ValueError, match="최근 로그"):
        await manager.start(project.id, "backend")

    state = manager.state(project.id, "backend")
    assert state.phase == "error"
    assert state.running is False
    assert state.command == [sys.executable, "-c", "raise SystemExit('boom')"]
    assert "boom" in (state.message or "")


@pytest.mark.asyncio
async def test_starting_process_is_tracked_and_early_exit_becomes_error(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Starting runtime", "준비 중 프로세스 상태 전환을 검증합니다")
    project.runtime.backend_port = free_port()
    project.runtime.backend_command = [
        sys.executable,
        "-c",
        "import time; time.sleep(0.5); raise SystemExit(7)",
    ]
    project.runtime.startup_timeout_seconds = 3
    store.save(project)
    manager = ProcessManager(store)

    start_task = asyncio.create_task(manager.start(project.id, "backend"))
    starting = manager.state(project.id, "backend")
    for _ in range(20):
        if starting.running or start_task.done():
            break
        await asyncio.sleep(0.05)
        starting = manager.state(project.id, "backend")

    assert starting.running is True
    assert starting.phase == "starting"
    with pytest.raises(ValueError, match="시작 직후 종료"):
        await start_task
    failed = manager.state(project.id, "backend")
    assert failed.running is False
    assert failed.phase == "error"


def test_runtime_logs_rotate_and_return_only_new_chunks(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Rolling logs", "로그 파일 회전과 증분 조회를 검증합니다")
    manager = ProcessManager(store)
    path = store.project_dir(project.id) / ".pocket" / "logs" / "backend.log"
    path.parent.mkdir(parents=True)

    manager._append_log_chunk(path, b"A" * 40_000, 65_536)
    manager._append_log_chunk(path, b"B" * 40_000, 65_536)

    assert path.with_suffix(".log.1").stat().st_size == 40_000
    first = manager.log_chunk(project.id, "backend")
    assert first["reset"] is True
    assert first["logs"] == "B" * 40_000

    manager._append_log_chunk(path, b"next", 65_536)
    second = manager.log_chunk(
        project.id,
        "backend",
        int(first["cursor"]),
        str(first["log_id"]),
    )
    assert second["reset"] is False
    assert second["logs"] == "next"


def test_new_start_archives_old_log_and_exposes_only_current_run(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Fresh logs", "실행별 로그 분리를 검증합니다")
    manager = ProcessManager(store)
    path = store.project_dir(project.id) / ".pocket" / "logs" / "frontend.log"
    path.parent.mkdir(parents=True)
    path.write_text("previous run error\n", "utf-8")

    manager._reset_log_for_start(path)
    path.write_text("current run started\n", "utf-8")

    assert path.with_suffix(".log.1").read_text("utf-8") == "previous run error\n"
    assert manager.logs(project.id, "frontend") == "current run started"
    chunk = manager.log_chunk(project.id, "frontend")
    assert chunk["reset"] is True
    assert str(chunk["logs"]).strip() == "current run started"


@pytest.mark.asyncio
async def test_log_write_failure_is_reported_without_raising(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Log failure", "로그 저장 실패가 프로세스 정지를 막지 않는지 검증합니다")
    manager = ProcessManager(store)

    class Reader:
        chunks = [b"output", b""]

        async def read(self, _size):
            return self.chunks.pop(0)

    def fail_write(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(manager, "_append_log_chunk", fail_write)
    await manager._pump_logs(
        (project.id, "backend"),
        Reader(),
        store.project_dir(project.id) / ".pocket" / "logs" / "backend.log",
        65_536,
    )

    assert "disk full" in manager.log_errors[(project.id, "backend")]
