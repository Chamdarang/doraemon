import sqlite3


def _project(client, name: str) -> str:
    response = client.post(
        "/api/projects",
        json={"name": name, "description": "도구 호환성 확장을 검증하기 위한 테스트 서비스입니다."},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_sqlite_rows_support_quoted_table_names(client):
    project_id = _project(client, "Quoted SQLite")
    root = client.app.state.container.store.project_dir(project_id)
    database = root / "back" / "quoted.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE "daily""items" (id INTEGER PRIMARY KEY, value TEXT)')
        connection.execute('INSERT INTO "daily""items"(value) VALUES (?)', ("Pocket",))

    response = client.get(
        f"/api/projects/{project_id}/sqlite/rows",
        params={"path": "back/quoted.sqlite", "table": 'daily"items'},
    )

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "value": "Pocket"}]


def test_technology_stack_detects_docker_compose_services(client):
    project_id = _project(client, "Compose stack")
    root = client.app.state.container.store.project_dir(project_id)
    (root / "back" / "Dockerfile").write_text("FROM python:3.14-slim\n", "utf-8")
    (root / "back" / "compose.yaml").write_text(
        """services:
  db:
    image: postgres:18
  cache:
    image: redis:8
  queue:
    image: rabbitmq:4-management
  document:
    image: mongo:8
""",
        "utf-8",
    )

    body = client.get(f"/api/projects/{project_id}/technology-stack").json()

    assert {"Docker", "PostgreSQL", "Redis", "RabbitMQ", "MongoDB"} <= set(body["infrastructure"])
