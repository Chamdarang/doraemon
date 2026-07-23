import json
import sqlite3
import zipfile

from app.schemas import GlobalSettings


def _project(client, name="Toolbox"):
    response = client.post("/api/projects", json={"name": name, "description": "Doraemon 도구 기능을 검증하는 테스트 서비스"})
    assert response.status_code == 201
    return response.json()["id"]


def test_notifications_and_global_settings(client):
    project_id = _project(client)
    store = client.app.state.container.store
    store.add_notification(project_id, "success", "완료", "작업이 끝났습니다")
    notifications = client.get(f"/api/projects/{project_id}/notifications").json()
    assert notifications[0]["read"] is False
    assert client.post(f"/api/projects/{project_id}/notifications/read").status_code == 204
    assert client.get(f"/api/projects/{project_id}/notifications").json()[0]["read"] is True

    settings = {"default_cost_mode": "economy", "keep_versions": 3, "log_tail_lines": 200}
    updated = client.put("/api/settings", json=settings).json()
    assert {key: updated[key] for key in settings} == settings
    assert updated["llm_provider"] == "openai"
    assert updated["llm_model"] == "gpt-5.4-mini"
    created = client.post("/api/projects", json={"name": "Economy", "description": "전역 기본 비용 설정이 반영되는 테스트 서비스"}).json()
    assert created["llm_policy"]["mode"] == "economy"


def test_notification_retention_prunes_old_and_excess_items(client):
    project_id = _project(client, "Notification retention")
    store = client.app.state.container.store
    store.save_global_settings(GlobalSettings(
        notification_retention_days=1,
        notification_max_items=10,
    ))
    old = store.add_notification(project_id, "info", "old", "expired")
    old.created_at = "2020-01-01T00:00:00+00:00"
    old_path = store.project_dir(project_id) / ".pocket" / "notifications" / f"{old.id}.json"
    store._write_text_atomic(old_path, old.model_dump_json(indent=2))
    for index in range(12):
        store.add_notification(project_id, "success", f"item-{index}", "recent")

    notifications = store.list_notifications(project_id)
    assert len(notifications) == 10
    assert all(item.title != "old" for item in notifications)


def test_maintenance_clears_current_and_rotated_logs(client):
    project_id = _project(client, "Rotated log cleanup")
    logs = client.app.state.container.store.project_dir(project_id) / ".pocket" / "logs"
    logs.mkdir(parents=True)
    current = logs / "backend.log"
    rotated = logs / "backend.log.1"
    current.write_text("current", "utf-8")
    rotated.write_text("rotated", "utf-8")

    response = client.post(
        f"/api/projects/{project_id}/maintenance",
        json={"clear_logs": True, "clear_cache": False},
    )

    assert response.status_code == 200
    assert current.read_text("utf-8") == ""
    assert not rotated.exists()


def test_llm_settings_update_runtime_without_exposing_key(client):
    response = client.put(
        "/api/settings",
        json={
            "llm_provider": "custom",
            "llm_model": "local-model",
            "llm_base_url": "http://localhost:11434/v1",
            "llm_api_key": "secret-test-key",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["llm_api_key_configured"] is True
    assert "llm_api_key" not in body
    assert client.app.state.container.generator.config.openai_model == "local-model"
    assert client.app.state.container.generator.config.openai_base_url == "http://localhost:11434/v1"


def test_llm_provider_profiles_survive_switches(client):
    base = {"default_cost_mode": "balanced", "keep_versions": 5, "log_tail_lines": 300, "llm_max_output_tokens": 64000}
    profiles = {
        "openai": {"model": "gpt-5.4-mini", "base_url": ""},
        "anthropic": {"model": "claude-sonnet-4-6", "base_url": "https://api.anthropic.com/v1/messages"},
    }
    response = client.put("/api/settings", json={
        **base,
        "llm_provider": "anthropic",
        "llm_model": profiles["anthropic"]["model"],
        "llm_base_url": profiles["anthropic"]["base_url"],
        "llm_profiles": profiles,
    })

    assert response.status_code == 200
    assert response.json()["llm_profiles"] == profiles


def test_invalid_multiline_api_key_is_not_written(client):
    response = client.put("/api/settings", json={
        "llm_provider": "openai",
        "llm_model": "gpt-5.4-mini",
        "llm_base_url": "",
        "llm_api_key": "first\nsecond",
    })
    assert response.status_code == 422
    assert not client.app.state.container.generator.config.llm_env_file.exists()


def test_corrupted_global_settings_recovers_backup(client):
    store = client.app.state.container.store
    store.save_global_settings(GlobalSettings(keep_versions=3))
    store.save_global_settings(GlobalSettings(keep_versions=7))
    (store.root / ".pocket-settings.json").write_text("{broken", "utf-8")

    assert store.get_global_settings().keep_versions == 3


def test_sqlite_read_only_and_export_excludes_secrets(client):
    project_id = _project(client, "Data Tool")
    root = client.app.state.container.store.project_dir(project_id)
    database = root / "back" / "sample.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO items(name) VALUES ('Pocket')")
    (root / "back" / "main.py").write_text("print('ok')", "utf-8")
    (root / "back" / ".env").write_text("SECRET=hidden", "utf-8")

    databases = client.get(f"/api/projects/{project_id}/sqlite").json()
    assert databases == [{"path": "back/sample.sqlite", "tables": ["items"]}]
    rows = client.get(
        f"/api/projects/{project_id}/sqlite/rows",
        params={"path": "back/sample.sqlite", "table": "items"},
    ).json()
    assert rows == [{"id": 1, "name": "Pocket"}]

    response = client.post(f"/api/projects/{project_id}/export")
    assert response.status_code == 200
    assert list((client.app.state.container.store.root / ".exports").glob("*.zip")) == []
    archive_path = client.app.state.container.store.root / "export-test.zip"
    archive_path.write_bytes(response.content)
    with zipfile.ZipFile(archive_path) as archive:
        assert "back/main.py" in archive.namelist()
        assert "back/.env" not in archive.namelist()


def test_export_and_diagnostics_do_not_follow_project_symlinks(client, monkeypatch):
    project_id = _project(client, "Symlink boundary")
    store = client.app.state.container.store
    root = store.project_dir(project_id)
    outside = store.root / "outside-secret.py"
    outside.write_text('TOKEN = "sk-abcdefghijklmnopqrstuvwxyz"', "utf-8")
    linked = root / "back" / "linked-secret.py"
    try:
        linked.symlink_to(outside)
    except OSError:
        linked.write_text(outside.read_text("utf-8"), "utf-8")
        path_type = type(linked)
        original_is_symlink = path_type.is_symlink
        monkeypatch.setattr(path_type, "is_symlink", lambda self: self == linked or original_is_symlink(self))

    report = client.get(f"/api/projects/{project_id}/diagnostics").json()
    assert not any("linked-secret.py" in item["message"] for item in report["security"])

    response = client.post(f"/api/projects/{project_id}/export")
    assert response.status_code == 200
    archive_path = store.root / "symlink-export-test.zip"
    archive_path.write_bytes(response.content)
    with zipfile.ZipFile(archive_path) as archive:
        assert "back/linked-secret.py" not in archive.namelist()


def test_diagnostics_find_secret_and_undeclared_environment(client):
    project_id = _project(client, "Diagnostics")
    root = client.app.state.container.store.project_dir(project_id)
    (root / "back" / "main.py").write_text(
        'TOKEN = "sk-abcdefghijklmnopqrstuvwxyz"\nVALUE = os.getenv("MISSING_VALUE")',
        "utf-8",
    )
    report = client.get(f"/api/projects/{project_id}/diagnostics").json()
    assert any(item["category"] == "secret" for item in report["security"])
    assert any("MISSING_VALUE" in item["message"] for item in report["consistency"])


def test_technology_stack_is_derived_from_project_manifests(client):
    project_id = _project(client, "Stack summary")
    root = client.app.state.container.store.project_dir(project_id)
    (root / "back" / "requirements.txt").write_text("fastapi\nSQLAlchemy\nPyMySQL\n", "utf-8")
    (root / "front" / "package.json").write_text(
        '{"dependencies":{"react":"19.0.0"},"devDependencies":{"vite":"7.0.0","typescript":"5.8.0"}}',
        "utf-8",
    )
    response = client.get(f"/api/projects/{project_id}/technology-stack")
    assert response.status_code == 200
    body = response.json()
    assert "FastAPI" in body["backend"]
    assert "React" in body["frontend"]
    assert "MySQL" in body["infrastructure"]


def test_technology_stack_detects_python_service_dependencies(client):
    project_id = _project(client, "Python infrastructure stack")
    root = client.app.state.container.store.project_dir(project_id)
    (root / "back" / "requirements.txt").write_text(
        "fastapi\nasyncpg\nredis\naio-pika\nmotor\naiosqlite\n",
        "utf-8",
    )

    body = client.get(f"/api/projects/{project_id}/technology-stack").json()

    assert {"PostgreSQL", "Redis", "RabbitMQ", "MongoDB", "SQLite"} <= set(body["infrastructure"])


def test_technology_stack_detects_node_backend_framework_and_orm(client):
    project_id = _project(client, "Node backend stack")
    root = client.app.state.container.store.project_dir(project_id)
    (root / "back" / "package.json").write_text(
        json.dumps({
            "dependencies": {
                "express": "^4.0.0",
                "@prisma/client": "^5.0.0",
                "mysql2": "^3.0.0",
                "pg": "^8.0.0",
                "mongoose": "^8.0.0",
                "better-sqlite3": "^11.0.0",
            },
            "devDependencies": {"typescript": "^5.0.0", "tsx": "^4.0.0"},
        }),
        "utf-8",
    )

    body = client.get(f"/api/projects/{project_id}/technology-stack").json()

    assert body["backend"] == ["Express", "Node.js", "Prisma", "TypeScript"]
    assert {"MySQL", "PostgreSQL", "MongoDB", "SQLite"} <= set(body["infrastructure"])


def test_technology_stack_detects_java_and_go_infrastructure(client):
    java_id = _project(client, "Java stack")
    java_root = client.app.state.container.store.project_dir(java_id)
    (java_root / "back" / "pom.xml").write_text(
        "<dependencies><artifactId>postgresql</artifactId><artifactId>spring-rabbit</artifactId><artifactId>spring-boot-starter-data-redis</artifactId></dependencies>",
        "utf-8",
    )
    java = client.get(f"/api/projects/{java_id}/technology-stack").json()
    assert "Java / Spring" in java["backend"]
    assert {"PostgreSQL", "RabbitMQ", "Redis"} <= set(java["infrastructure"])

    go_id = _project(client, "Go stack")
    go_root = client.app.state.container.store.project_dir(go_id)
    (go_root / "back" / "go.mod").write_text(
        "module example.local/service\nrequire ( github.com/jackc/pgx/v5 v5.0.0 github.com/redis/go-redis/v9 v9.0.0 github.com/rabbitmq/amqp091-go v1.0.0 )",
        "utf-8",
    )
    go = client.get(f"/api/projects/{go_id}/technology-stack").json()
    assert "Go" in go["backend"]
    assert {"PostgreSQL", "RabbitMQ", "Redis"} <= set(go["infrastructure"])
