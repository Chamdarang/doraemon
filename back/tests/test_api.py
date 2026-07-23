import sys
import zipfile
from io import BytesIO
from types import SimpleNamespace

from app.runtime.manager import ProcessManager
from app.schemas import EnvironmentVariableSpec, Job
from app.services.versioning import VersioningService


def test_project_lifecycle_and_environment(client):
    response = client.post("/api/projects", json={
        "name": "Todo Service", "description": "할 일을 로컬에서 관리하는 서비스"
    })
    assert response.status_code == 201
    project = response.json()
    assert project["id"] == "todo-service"

    assert client.get("/api/projects").json()[0]["name"] == "Todo Service"
    update = client.put(
        "/api/projects/todo-service/environment", json={"values": {"API_TOKEN": "secret"}}
    )
    assert update.json() == {"values": {"API_TOKEN": "********"}, "schema": []}
    assert client.get("/api/projects/todo-service/environment").json() == update.json()


def test_project_overviews_are_returned_in_one_batch(client):
    first = client.post("/api/projects", json={
        "name": "First", "description": "첫 번째 목록 요약 테스트 서비스"
    }).json()
    second = client.post("/api/projects", json={
        "name": "Second", "description": "두 번째 목록 요약 테스트 서비스"
    }).json()

    response = client.get("/api/projects/overviews")

    assert response.status_code == 200
    assert {item["project_id"] for item in response.json()} == {first["id"], second["id"]}


def test_runtime_snapshot_combines_status_jobs_notifications_and_logs(client):
    project = client.post("/api/projects", json={
        "name": "Snapshot", "description": "런타임 스냅샷을 검증하는 테스트 서비스"
    }).json()
    store = client.app.state.container.store
    store.save_job(Job(id="snapshot-job", project_id=project["id"], status="completed"))
    store.add_notification(project["id"], "success", "완료", "스냅샷 알림")
    logs = store.project_dir(project["id"]) / ".pocket" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "backend.log").write_text("backend ready", "utf-8")

    response = client.get(f"/api/projects/{project['id']}/runtime-snapshot")

    assert response.status_code == 200
    body = response.json()
    assert len(body["processes"]) == 2
    assert body["jobs"][0]["id"] == "snapshot-job"
    assert body["notifications"][0]["title"] == "완료"
    assert "backend ready" in body["logs"]["backend"]["logs"]

    without_logs = client.get(
        f"/api/projects/{project['id']}/runtime-snapshot?include_logs=false"
    ).json()
    assert without_logs["logs"] == {}


def test_rejects_invalid_environment_name(client):
    client.post("/api/projects", json={
        "name": "Safe", "description": "안전한 테스트 서비스를 만듭니다"
    })
    response = client.put("/api/projects/safe/environment", json={"values": {"bad-key": "x"}})
    assert response.status_code == 422


def test_missing_project_is_404(client):
    assert client.get("/api/projects/none").status_code == 404


def test_global_search_finds_projects_and_jobs(client):
    project = client.post(
        "/api/projects",
        json={"name": "Travel Planner", "description": "여행 일정을 정리하는 서비스입니다"},
    ).json()
    client.app.state.container.store.save_job(Job(
        id="repair-search",
        project_id=project["id"],
        kind="repair",
        status="failed",
        message="지도 화면 오류 수정",
        error="marker rendering failed",
    ))

    project_results = client.get("/api/search?q=Travel").json()
    job_results = client.get("/api/search?q=marker").json()

    assert project_results[0]["kind"] == "project"
    assert project_results[0]["project_id"] == project["id"]
    assert job_results[0]["kind"] == "job"
    assert job_results[0]["project_name"] == "Travel Planner"
    assert client.get("/api/search?q=x").json() == []


def test_frontend_origin_is_allowed(client):
    response = client.options("/api/projects", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_dynamic_local_frontend_port_is_allowed(client):
    response = client.options("/api/projects", headers={
        "Origin": "http://localhost:3017",
        "Access-Control-Request-Method": "POST",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3017"


def test_non_local_origin_is_not_allowed(client):
    response = client.options("/api/projects", headers={
        "Origin": "https://example.com",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in response.headers


def test_usage_starts_empty(client):
    client.post("/api/projects", json={"name": "Usage", "description": "사용량 합계를 확인하는 테스트 서비스"})
    response = client.get("/api/projects/usage/usage")
    assert response.status_code == 200
    assert response.json()["total_tokens"] == 0


def test_usage_records_are_paginated_without_prompt_content(client):
    project = client.post(
        "/api/projects",
        json={"name": "Usage records", "description": "요청별 토큰 기록을 검증합니다"},
    ).json()
    usage = SimpleNamespace(
        input_tokens=120,
        output_tokens=30,
        total_tokens=150,
        input_tokens_details=SimpleNamespace(cached_tokens=80),
    )
    client.app.state.container.store.record_usage(project["id"], "planning", "test-model", usage)

    response = client.get(f"/api/projects/{project['id']}/usage/records?offset=0&limit=1")

    assert response.status_code == 200
    assert response.json()[0] == {
        "id": response.json()[0]["id"],
        "kind": "planning",
        "model": "test-model",
        "provider": "openai",
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "cached_input_tokens": 80,
        "created_at": response.json()[0]["created_at"],
    }
    assert "prompt" not in response.json()[0]


def test_health_reports_selected_llm_without_exposing_key(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["llm_provider"] == "openai"
    assert "llm_configured" in body
    assert "llm_model" in body
    assert "api_key" not in body


def test_runtime_command_uses_selected_port(client):
    manager = client.app.state.container.processes
    command = ["python", "-m", "uvicorn", "app.main:app", "--port", "8000"]
    assert manager._command_with_port(command, 8017)[-1] == "8017"
    positional = ["go", "run", ".", "8000"]
    assert manager._command_with_port(positional, 8017, 8000)[-1] == "8017"


def test_runtime_prefers_virtualenv_console_script(tmp_path):
    scripts = tmp_path / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    scripts.mkdir(parents=True)
    executable = scripts / ("uvicorn.exe" if sys.platform == "win32" else "uvicorn")
    executable.write_text("local executable", "utf-8")
    resolved = ProcessManager._resolve_project_executable(tmp_path, "uvicorn")
    assert resolved == str(executable.resolve())


def test_saved_process_record_requires_the_same_listener_pid(client, monkeypatch):
    manager = client.app.state.container.processes
    monkeypatch.setattr(manager, "_windows_listener_pid", lambda port: 222)
    assert manager._record_owns_listener({"port": 8000, "listener_pid": 222}) is True
    assert manager._record_owns_listener({"port": 8000, "listener_pid": 111}) is False
    assert manager._record_owns_listener({"port": 8000}) is False


def test_service_ports_can_be_configured_while_stopped(client):
    client.post("/api/projects", json={
        "name": "Ports", "description": "서비스별 포트를 직접 설정하는 테스트 서비스"
    })
    project = client.app.state.container.store.get("ports")
    project.runtime.environment.extend([
        EnvironmentVariableSpec(
            key="BACKEND_PORT",
            description="Docker backend port",
            format="integer",
        ),
        EnvironmentVariableSpec(
            key="FRONTEND_PORT",
            description="Docker frontend port",
            format="integer",
        ),
    ])
    client.app.state.container.store.save(project)
    response = client.put(
        "/api/projects/ports/runtime/ports",
        json={"backend_port": 18101, "frontend_port": 15174},
    )
    assert response.status_code == 200
    assert response.json()["runtime"]["backend_port"] == 18101
    assert response.json()["runtime"]["frontend_port"] == 15174
    assert client.app.state.container.store.read_env("ports") == {
        "BACKEND_PORT": "18101",
        "FRONTEND_PORT": "15174",
    }


def test_backend_and_frontend_ports_must_differ(client):
    client.post("/api/projects", json={
        "name": "Port conflict", "description": "동일 포트 설정을 거부하는 테스트 서비스"
    })
    response = client.put(
        "/api/projects/port-conflict/runtime/ports",
        json={"backend_port": 18111, "frontend_port": 18111},
    )
    assert response.status_code == 422


def test_create_does_not_generate_by_default(client):
    response = client.post("/api/projects", json={
        "name": "Planning First", "description": "기획과 기술 선택부터 진행하는 서비스"
    })
    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    assert client.get("/api/projects/planning-first/jobs").json() == []


def test_zip_project_can_be_imported_through_api(client):
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as payload:
        payload.writestr("back/main.go", "package main\nfunc main() {}\n")
        payload.writestr("back/go.mod", "module example.test/imported\n")
    archive.seek(0)

    response = client.post(
        "/api/projects/import",
        data={
            "name": "Imported API",
            "description": "API를 통해 기존 ZIP 프로젝트를 가져옵니다",
        },
        files={"file": ("service.zip", archive, "application/zip")},
    )

    assert response.status_code == 201
    project = response.json()
    assert project["status"] == "ready"
    assert project["runtime"]["backend_command"] == ["go", "run", "."]
    assert (client.app.state.container.store.project_dir(project["id"]) / "back" / "main.go").is_file()


def test_generate_requires_approved_plan(client):
    client.post("/api/projects", json={
        "name": "Needs Plan", "description": "승인된 명세가 필요한 서비스"
    })
    response = client.post("/api/projects/needs-plan/generate")
    assert response.status_code == 409


def test_project_workspace_returns_one_consistent_initial_snapshot(client):
    project = client.post(
        "/api/projects",
        json={"name": "Workspace", "description": "초기 화면 데이터를 한 요청으로 조회하는 서비스입니다"},
    ).json()

    response = client.get(f"/api/projects/{project['id']}/workspace")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "messages",
        "jobs",
        "processes",
        "improvement_messages",
        "plan",
        "improvement_plan",
        "usage",
        "versions",
        "repair_messages",
        "overview",
        "notifications",
    }
    assert [item["target"] for item in body["processes"]] == ["backend", "frontend"]
    assert body["overview"]["project_id"] == project["id"]


def test_version_diff_endpoint_compares_snapshot_with_current_files(client):
    project = client.post(
        "/api/projects",
        json={"name": "Diff API", "description": "버전 차이 API를 검증합니다"},
    ).json()
    store = client.app.state.container.store
    source = store.project_dir(project["id"]) / "back" / "main.py"
    source.write_text("before\n", "utf-8")
    version = VersioningService(store).save_version(project["id"], "before", None)
    source.write_text("after\n", "utf-8")

    response = client.get(f"/api/projects/{project['id']}/versions/{version.id}/diff")

    assert response.status_code == 200
    assert response.json()["modified"] == 1
    assert response.json()["files"][0]["path"] == "back/main.py"
