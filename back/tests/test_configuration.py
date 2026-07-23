import pytest

from app.core.config import Settings
from app.schemas import EnvironmentVariableSpec
from app.repositories.store import ProjectStore


def test_secret_client_environment_variable_is_rejected(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Secrets", "프론트 비밀값 노출을 차단하는 테스트 서비스")
    project.runtime.environment = [EnvironmentVariableSpec(
        key="VITE_SECRET_KEY",
        description="노출되면 안 되는 값",
        secret=True,
        client_exposed=True,
    )]
    store.save(project)
    with pytest.raises(ValueError, match="프론트"):
        store.write_env(project.id, {"VITE_SECRET_KEY": "secret"})


def test_environment_variable_format_is_validated(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Formats", "환경변수 값 형식을 검증하는 테스트 서비스")
    project.runtime.environment = [EnvironmentVariableSpec(
        key="SERVICE_PORT",
        description="서비스 포트",
        format="integer",
    )]
    store.save(project)
    with pytest.raises(ValueError, match="integer"):
        store.write_env(project.id, {"SERVICE_PORT": "not-a-number"})
