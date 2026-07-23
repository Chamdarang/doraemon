import json

import pytest

from app.core.config import Settings
from app.services.infrastructure import InfrastructureService
from app.repositories.store import ProjectStore


@pytest.mark.asyncio
async def test_compose_services_are_listed_and_individually_controlled(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Infrastructure", "Docker Compose 인프라 제어를 검증합니다")
    env_file = store.project_dir(project.id) / ".env"
    env_file.write_text("MYSQL_PORT=13307\n", "utf-8")
    compose = store.project_dir(project.id) / "back" / "compose.yaml"
    compose.write_text("services:\n  mysql:\n    image: mysql:8\n  redis:\n    image: redis:7\n", "utf-8")
    service = InfrastructureService(store)
    calls: list[list[str]] = []

    async def fake_run(_executable, arguments, _cwd, timeout):
        calls.append(arguments)
        assert timeout in {30, 300}
        if arguments[-2:] == ["config", "--services"]:
            return 0, "mysql\nredis\n"
        if arguments[-3:] == ["config", "--format", "json"]:
            return 0, "docker warning\n" + json.dumps({"services": {
                "mysql": {"image": "mysql:8", "ports": []},
                "redis": {"image": "redis:7", "ports": []},
            }})
        if arguments[-3:] == ["ps", "--format", "json"]:
            return 0, json.dumps([{
                "Service": "mysql",
                "State": "running",
                "Status": "Up 10 seconds",
                "Health": "healthy",
                "ExitCode": 0,
                "Publishers": [{"PublishedPort": 3306, "TargetPort": 3306}],
            }])
        return 0, "started"

    monkeypatch.setattr("app.services.infrastructure.shutil.which", lambda _name: "docker")
    monkeypatch.setattr(service, "_run", fake_run)

    overview = await service.overview(project.id)
    updated = await service.control(project.id, "back/compose.yaml", "redis", "start")

    assert [(item.name, item.running) for item in overview.services] == [
        ("mysql", True),
        ("redis", False),
    ]
    assert overview.services[0].ports == ["3306:3306"]
    assert overview.services[0].health == "healthy"
    assert overview.services[0].exit_code == 0
    assert any(arguments[-3:] == ["up", "-d", "redis"] for arguments in calls)
    assert any("--env-file" in arguments and str(env_file) in arguments for arguments in calls)
    project_names = {
        arguments[arguments.index("--project-name") + 1]
        for arguments in calls
        if "--project-name" in arguments
    }
    assert len(project_names) == 1
    assert next(iter(project_names)).startswith(f"pocket-{project.id}-")
    assert updated.docker_available is True


@pytest.mark.asyncio
async def test_infrastructure_logs_are_scoped_to_a_declared_service(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Infrastructure logs", "Read recent container logs")
    compose = store.project_dir(project.id) / "back" / "infra" / "compose.yaml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services:\n  api:\n    image: sample:latest\n", "utf-8")
    service = InfrastructureService(store)
    calls: list[list[str]] = []

    async def fake_run(_executable, arguments, _cwd, timeout):
        calls.append(arguments)
        assert timeout == 30
        if arguments[-3:] == ["config", "--format", "json"]:
            return 0, json.dumps({"services": {"api": {"image": "sample:latest"}}})
        return 0, "api-1 | ready\n"

    monkeypatch.setattr("app.services.infrastructure.shutil.which", lambda _name: "docker")
    monkeypatch.setattr(service, "_run", fake_run)

    result = await service.logs(project.id, "back/infra/compose.yaml", "api", 100)

    assert result.logs == "api-1 | ready\n"
    assert calls[-1][-5:] == ["logs", "--no-color", "--tail", "100", "api"]

    with pytest.raises(ValueError, match="선언되지 않은 서비스"):
        await service.logs(project.id, "back/infra/compose.yaml", "unknown")


@pytest.mark.asyncio
async def test_infrastructure_overview_keeps_other_compose_results_on_partial_failure(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Partial infrastructure", "Keep readable compose states")
    root = store.project_dir(project.id)
    broken = root / "back" / "compose.yaml"
    working = root / "front" / "compose.yaml"
    broken.write_text("services: [", "utf-8")
    working.write_text("services:\n  web:\n    image: sample:latest\n", "utf-8")
    service = InfrastructureService(store)

    async def fake_states(_project_id, _docker, compose):
        if compose == broken:
            raise ValueError("invalid compose")
        from app.schemas import InfrastructureServiceState
        return [InfrastructureServiceState(name="web", source="front/compose.yaml", kind="docker")]

    monkeypatch.setattr("app.services.infrastructure.shutil.which", lambda _name: "docker")
    monkeypatch.setattr(service, "_docker_states", fake_states)

    result = await service.overview(project.id)

    assert [item.name for item in result.services] == ["web"]
    assert result.errors == ["back/compose.yaml: invalid compose"]


def test_compose_project_names_are_isolated_by_service_and_source(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    first = store.create("First", "첫 번째 Docker 서비스")
    second = store.create("Second", "두 번째 Docker 서비스")
    service = InfrastructureService(store)
    first_compose = store.project_dir(first.id) / "back" / "infra" / "compose.yaml"
    alternate = store.project_dir(first.id) / "front" / "infra" / "compose.yaml"
    second_compose = store.project_dir(second.id) / "back" / "infra" / "compose.yaml"

    names = {
        service._project_name(first.id, first_compose),
        service._project_name(first.id, alternate),
        service._project_name(second.id, second_compose),
    }

    assert len(names) == 3


@pytest.mark.asyncio
async def test_infrastructure_control_rejects_unknown_compose_source(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Safe infrastructure", "프로젝트 밖 Compose 접근을 차단합니다")
    service = InfrastructureService(store)
    monkeypatch.setattr("app.services.infrastructure.shutil.which", lambda _name: "docker")

    with pytest.raises(ValueError, match="프로젝트에 속한 Compose"):
        await service.control(project.id, "../compose.yaml", "mysql", "start")


def test_nested_legacy_compose_is_discovered_without_scanning_generated_directories(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Legacy infrastructure", "기존 Compose 위치도 발견합니다")
    root = store.project_dir(project.id)
    legacy = root / "back" / "infra" / "docker-compose.yml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("services:\n  mysql:\n    image: mysql:8\n", "utf-8")
    ignored = root / "front" / "node_modules" / "sample" / "compose.yaml"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("services:\n  hidden:\n    image: redis:7\n", "utf-8")

    files = InfrastructureService(store)._compose_files(project.id)

    assert files == [legacy]


@pytest.mark.asyncio
async def test_compose_build_service_is_rebuilt_on_start(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Build service", "변경된 소스를 Docker 이미지에 반영합니다")
    compose = store.project_dir(project.id) / "back" / "infra" / "compose.yaml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services:\n  api:\n    build: ..\n", "utf-8")
    service = InfrastructureService(store)
    calls: list[list[str]] = []

    async def fake_run(_executable, arguments, _cwd, timeout):
        calls.append(arguments)
        assert timeout in {30, 300}
        if arguments[-3:] == ["config", "--format", "json"]:
            return 0, json.dumps({"services": {"api": {"build": {"context": ".."}, "ports": []}}})
        if arguments[-3:] == ["ps", "--format", "json"]:
            return 0, "[]"
        return 0, "ok"

    monkeypatch.setattr("app.services.infrastructure.shutil.which", lambda _name: "docker")
    monkeypatch.setattr(service, "_run", fake_run)

    await service.control(project.id, "back/infra/compose.yaml", "api", "start")

    assert any(arguments[-4:] == ["up", "-d", "--build", "api"] for arguments in calls)


@pytest.mark.asyncio
async def test_infrastructure_ports_are_saved_and_conflicts_are_rejected(tmp_path, monkeypatch):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Infrastructure ports", "인프라 포트를 서비스별로 설정합니다")
    compose = store.project_dir(project.id) / "back" / "infra" / "compose.yaml"
    compose.parent.mkdir(parents=True)
    compose.write_text(
        'services:\n  db:\n    ports:\n      - "${MYSQL_PORT:-3307}:3306"\n',
        "utf-8",
    )
    service = InfrastructureService(store)
    monkeypatch.setattr("app.services.infrastructure.shutil.which", lambda _name: None)
    monkeypatch.setattr(service, "_port_available", lambda _port: True)

    updated = await service.update_ports(project.id, {"MYSQL_PORT": 13307})

    assert store.read_env(project.id)["MYSQL_PORT"] == "13307"
    assert updated.port_settings[0].value == 13307

    monkeypatch.setattr(service, "_port_available", lambda _port: False)
    with pytest.raises(ValueError, match="이미 사용 중"):
        await service.update_ports(project.id, {"MYSQL_PORT": 13308})
