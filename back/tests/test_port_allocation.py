import json
import zipfile

from app.core.config import Settings
from app.services.importer import ProjectImportService
from app.runtime.command import replace_command_port
from app.repositories.store import ProjectStore


def test_new_and_cloned_projects_receive_distinct_configured_ports(tmp_path):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))

    first = store.create("First", "첫 번째 포트 할당을 검증하는 테스트 서비스입니다.")
    second = store.create("Second", "두 번째 포트 할당을 검증하는 테스트 서비스입니다.")
    first.runtime.backend_command = ["python", "manage.py", "runserver", f"0.0.0.0:{first.runtime.backend_port}"]
    first.runtime.frontend_command = ["java", "-jar", "app.jar", f"--server.port={first.runtime.frontend_port}"]
    store.save(first)
    clone = store.clone(first.id, "First clone")

    pairs = {
        (first.runtime.backend_port, first.runtime.frontend_port),
        (second.runtime.backend_port, second.runtime.frontend_port),
        (clone.runtime.backend_port, clone.runtime.frontend_port),
    }
    all_ports = {
        first.runtime.backend_port, first.runtime.frontend_port,
        second.runtime.backend_port, second.runtime.frontend_port,
        clone.runtime.backend_port, clone.runtime.frontend_port,
    }
    assert len(pairs) == 3
    assert len(all_ports) == 6
    assert clone.runtime.backend_command[-1] == f"0.0.0.0:{clone.runtime.backend_port}"
    assert clone.runtime.frontend_command[-1] == f"--server.port={clone.runtime.frontend_port}"


def test_imported_projects_use_their_allocated_ports(tmp_path):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))
    service = ProjectImportService(store)
    archive = tmp_path / "service.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as payload:
        payload.writestr("back/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
        payload.writestr("front/package.json", json.dumps({"scripts": {"dev": "vite"}, "dependencies": {"vite": "latest"}}))

    first = service.import_archive("Imported one", "첫 번째 가져오기 포트 할당 테스트입니다.", archive)
    second = service.import_archive("Imported two", "두 번째 가져오기 포트 할당 테스트입니다.", archive)

    assert first.runtime.backend_port != second.runtime.backend_port
    assert first.runtime.frontend_port != second.runtime.frontend_port
    assert second.runtime.backend_command[-1] == str(second.runtime.backend_port)
    assert second.runtime.frontend_command[-1] == str(second.runtime.frontend_port)


def test_runtime_port_update_rejects_another_project_reserved_port(client, monkeypatch):
    first = client.post("/api/projects", json={"name": "Port owner", "description": "포트를 먼저 예약하는 테스트 서비스입니다."}).json()
    second = client.post("/api/projects", json={"name": "Port requester", "description": "동일 포트를 요청하는 테스트 서비스입니다."}).json()
    monkeypatch.setattr(client.app.state.container.processes, "_available_port", lambda port: port)

    response = client.put(
        f"/api/projects/{second['id']}/runtime/ports",
        json={"backend_port": first["runtime"]["backend_port"], "frontend_port": second["runtime"]["frontend_port"]},
    )

    assert response.status_code == 409
    assert "Doraemon" in response.json()["detail"]


def test_runtime_port_update_rewrites_framework_specific_commands(client, monkeypatch):
    created = client.post("/api/projects", json={"name": "Port rewrite", "description": "프레임워크별 실행 명령의 포트 변경 테스트입니다."}).json()
    store = client.app.state.container.store
    project = store.get(created["id"])
    project.runtime.backend_command = ["python", "manage.py", "runserver", f"0.0.0.0:{project.runtime.backend_port}"]
    project.runtime.frontend_command = ["java", "-jar", "app.jar", f"--server.port={project.runtime.frontend_port}"]
    store.save(project)
    monkeypatch.setattr(client.app.state.container.processes, "_available_port", lambda port: port)

    response = client.put(
        f"/api/projects/{project.id}/runtime/ports",
        json={"backend_port": 18_001, "frontend_port": 15_174},
    )

    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert runtime["backend_command"][-1] == "0.0.0.0:18001"
    assert runtime["frontend_command"][-1] == "--server.port=15174"


def test_command_port_rewriter_supports_common_argument_forms():
    assert replace_command_port(["uvicorn", "app:app", "--port", "8001"], 9001, 8001)[-1] == "9001"
    assert replace_command_port(["vite", "--port=5174"], 6174, 5174)[-1] == "--port=6174"
    assert replace_command_port(["java", "-Dserver.port=8001", "-jar", "app.jar"], 9001, 8001)[1] == "-Dserver.port=9001"
    assert replace_command_port(["python", "manage.py", "runserver", "127.0.0.1:8001"], 9001, 8001)[-1] == "127.0.0.1:9001"


def test_unarchive_reassigns_ports_reused_while_project_was_archived(tmp_path):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))
    archived = store.create("Archived", "보관 서비스 포트 복구를 검증하는 테스트입니다.")
    store.set_archived(archived.id, True)
    replacement = store.create("Replacement", "해제된 포트를 사용하는 테스트 서비스입니다.")

    restored = store.set_archived(archived.id, False)

    assert {restored.runtime.backend_port, restored.runtime.frontend_port}.isdisjoint(
        {replacement.runtime.backend_port, replacement.runtime.frontend_port}
    )
    assert str(restored.runtime.backend_port) in restored.runtime.backend_command
    assert str(restored.runtime.frontend_port) in restored.runtime.frontend_command


def test_trash_restore_reassigns_ports_reused_after_deletion(tmp_path):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))
    deleted = store.create("Deleted", "휴지통 서비스 포트 복구를 검증하는 테스트입니다.")
    store.move_to_trash(deleted.id)
    replacement = store.create("Replacement", "휴지통에서 해제된 포트를 사용하는 서비스입니다.")
    trash_id = store.list_trash()[0].id

    restored = store.restore_trash(trash_id)

    assert {restored.runtime.backend_port, restored.runtime.frontend_port}.isdisjoint(
        {replacement.runtime.backend_port, replacement.runtime.frontend_port}
    )
