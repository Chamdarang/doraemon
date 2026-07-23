import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, SecretStr

from app.integrations.llm import client as llm
from app.integrations.llm.providers import common, probe
from app.services.generation.service import GenerationService
from app.schemas import ImprovementBundle, Job, JobStatus
from app.services.versioning import VersioningService


class Result(BaseModel):
    name: str
    values: list[int]


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code
        self.reason_phrase = "OK" if status_code < 400 else "Bad Request"

    @property
    def is_success(self):
        return self.status_code < 400

    def json(self):
        return self.body


class FakeClient:
    response = FakeResponse({})
    last_request = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        type(self).last_request = (url, kwargs)
        return type(self).response

    async def get(self, url, **kwargs):
        type(self).last_request = (url, kwargs)
        return type(self).response


FIXTURES = Path(__file__).parent / "fixtures" / "llm"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text("utf-8"))


def config(provider, *, url="", model="model"):
    return SimpleNamespace(
        llm_provider=provider,
        openai_api_key=SecretStr("test-key"),
        openai_base_url=url or None,
        openai_model=model,
        llm_max_output_tokens=64000,
    )


@pytest.mark.asyncio
async def test_anthropic_uses_native_structured_output(monkeypatch):
    FakeClient.response = FakeResponse(fixture("anthropic.json"))
    monkeypatch.setattr(common.httpx, "AsyncClient", FakeClient)

    response = await llm.parse_structured(config("anthropic"), instructions="system", input="user", text_format=Result)

    assert response.output_parsed.name == "Pocket"
    _, request = FakeClient.last_request
    assert request["json"]["output_config"]["format"]["type"] == "json_schema"
    assert "Return only" not in request["json"]["system"]


@pytest.mark.asyncio
async def test_gemini_uses_interactions_structured_output(monkeypatch):
    FakeClient.response = FakeResponse(fixture("gemini.json"))
    monkeypatch.setattr(common.httpx, "AsyncClient", FakeClient)

    response = await llm.parse_structured(config("gemini", url="https://generativelanguage.googleapis.com/v1beta"), instructions="system", input="user", text_format=Result)

    assert response.output_parsed.values == [3]
    url, request = FakeClient.last_request
    assert url.endswith("/interactions")
    assert request["json"]["response_format"]["mime_type"] == "application/json"


@pytest.mark.asyncio
async def test_compatible_provider_accepts_text_content_blocks(monkeypatch):
    FakeClient.response = FakeResponse(fixture("compatible.json"))
    monkeypatch.setattr(common.httpx, "AsyncClient", FakeClient)

    response = await llm.parse_structured(
        config("custom", url="http://localhost:11434/v1"),
        instructions="system",
        input="user",
        text_format=Result,
    )

    assert response.output_parsed.values == [4]


def test_known_improvement_response_deviations_are_normalized():
    raw = f"```json\n{json.dumps(fixture('improvement-deviations.json'))}\n```"

    bundle = common.parse_json(raw, ImprovementBundle, "fixture")

    assert [item.path for item in bundle.files] == ["back/app/main.py", "front/src/App.tsx"]
    assert bundle.runtime is None


@pytest.mark.asyncio
async def test_openrouter_requires_structured_output_capable_route(monkeypatch):
    FakeClient.response = FakeResponse({
        "choices": [{"message": {"content": '{"name":"Pocket","values":[]}'}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 3},
    })
    monkeypatch.setattr(common.httpx, "AsyncClient", FakeClient)

    await llm.parse_structured(config("openrouter", url="https://openrouter.ai/api/v1"), instructions="system", input="user", text_format=Result)

    _, request = FakeClient.last_request
    assert request["json"]["provider"]["require_parameters"] is True
    assert request["json"]["response_format"]["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_connection_check_only_reads_model(monkeypatch):
    FakeClient.response = FakeResponse({"id": "gpt-5.4-mini"})
    monkeypatch.setattr(probe.httpx, "AsyncClient", FakeClient)

    result = await llm.test_connection(config("openai", model="gpt-5.4-mini"))

    url, _ = FakeClient.last_request
    assert url.endswith("/models/gpt-5.4-mini")
    assert result["reachable"] is True


def test_provider_keys_are_kept_separately(client):
    base = {"default_cost_mode": "balanced", "keep_versions": 5, "log_tail_lines": 300, "llm_max_output_tokens": 64000}
    first = client.put("/api/settings", json={**base, "llm_provider": "openai", "llm_model": "gpt-5.4-mini", "llm_base_url": "", "llm_api_key": "openai-key"})
    second = client.put("/api/settings", json={**base, "llm_provider": "anthropic", "llm_model": "claude-sonnet-4-6", "llm_base_url": "https://api.anthropic.com/v1/messages", "llm_api_key": "anthropic-key"})
    switched = client.put("/api/settings", json={**base, "llm_provider": "openai", "llm_model": "gpt-5.4-mini", "llm_base_url": ""})

    assert first.status_code == second.status_code == switched.status_code == 200
    assert switched.json()["llm_api_key_configured"] is True
    assert switched.json()["llm_api_key_providers"] == ["anthropic", "openai"]
    assert client.app.state.container.generator.config.provider_api_key("anthropic").get_secret_value() == "anthropic-key"
    assert "ANTHROPIC_API_KEY=anthropic-key" in client.app.state.container.generator.config.llm_env_file.read_text("utf-8")


@pytest.mark.asyncio
async def test_second_paid_call_is_rejected_while_one_is_running(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_call(*args, **kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(output_parsed=Result(name="first", values=[]), usage=None)

    monkeypatch.setattr(llm, "_parse_structured_unlocked", slow_call)
    first = asyncio.create_task(
        llm.parse_structured(config("openai"), instructions="one", input="one", text_format=Result, project_id="demo", operation="generation")
    )
    await started.wait()
    activity = llm.get_llm_activity()
    assert activity.busy is True
    assert activity.project_id == "demo"
    assert activity.operation == "generation"
    assert activity.estimated_input_tokens > 0
    with pytest.raises(llm.LlmProviderError, match="중복 과금 방지"):
        await llm.parse_structured(config("openai"), instructions="two", input="two", text_format=Result)
    release.set()
    await first
    assert llm.get_llm_activity().busy is False


def test_corrupted_manifest_recovers_from_last_backup(client):
    project = client.post("/api/projects", json={"name": "Recovery", "description": "손상된 상태 파일 복구를 확인하는 충분한 설명입니다."}).json()
    store = client.app.state.container.store
    manifest = store.get(project["id"])
    original_name = manifest.name
    manifest.name = "Changed"
    store.save(manifest)
    (store.project_dir(project["id"]) / "pocket.json").write_text("{broken", "utf-8")

    recovered = store.get(project["id"])

    assert recovered.name == original_name
    assert (store.project_dir(project["id"]) / "pocket.json").read_text("utf-8").startswith("{")


def test_interrupted_write_restores_checkpoint(client):
    project = client.post("/api/projects", json={"name": "Interrupted", "description": "파일 적용 중 서버 재시작 복구를 확인하는 충분한 설명입니다."}).json()
    store = client.app.state.container.store
    root = store.project_dir(project["id"])
    source = root / "back" / "main.py"
    source.write_text("before", "utf-8")
    job = Job(id="interrupted-job", project_id=project["id"], status=JobStatus.writing)
    store.save_job(job)
    VersioningService(store).create_checkpoint(project["id"], job.id)
    source.write_text("after", "utf-8")

    GenerationService(client.app.state.container.generator.config, store)

    recovered = store.get_job(project["id"], job.id)
    assert source.read_text("utf-8") == "before"
    assert recovered.status == JobStatus.failed
    assert recovered.interrupted is True
    assert recovered.retry_available is True
