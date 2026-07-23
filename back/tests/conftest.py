import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path):
    original = settings.root
    original_env_file = settings.llm_env_file
    key_fields = {field: getattr(settings, field) for field, _ in settings._provider_key_fields.values()}
    settings.root = tmp_path
    settings.llm_env_file = tmp_path / ".env"
    with TestClient(app) as test_client:
        yield test_client
    settings.root = original
    settings.llm_env_file = original_env_file
    for field, value in key_fields.items():
        setattr(settings, field, value)
