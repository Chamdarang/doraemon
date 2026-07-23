import asyncio

import pytest

from app.core.locks import ProjectBusyError, ProjectLockRegistry


@pytest.mark.asyncio
async def test_mutations_for_one_project_are_serialized():
    locks = ProjectLockRegistry()
    entered = asyncio.Event()
    release = asyncio.Event()
    order: list[str] = []

    async def first():
        async with locks.hold("demo"):
            order.append("first")
            entered.set()
            await release.wait()

    async def second():
        await entered.wait()
        async with locks.hold("demo"):
            order.append("second")

    one = asyncio.create_task(first())
    two = asyncio.create_task(second())
    await entered.wait()
    await asyncio.sleep(0)
    assert order == ["first"]
    release.set()
    await asyncio.gather(one, two)
    assert order == ["first", "second"]


@pytest.mark.asyncio
async def test_paid_chat_can_fail_fast_instead_of_waiting_for_same_project():
    locks = ProjectLockRegistry()

    async with locks.hold("demo"):
        assert locks.is_locked("demo") is True
        with pytest.raises(ProjectBusyError):
            async with locks.hold("demo", wait=False):
                raise AssertionError("busy lock must not be entered")

    assert locks.is_locked("demo") is False


def test_paid_chat_api_rejects_a_second_request_instead_of_queueing(client):
    project = client.post(
        "/api/projects",
        json={"name": "Busy planning", "description": "중복 LLM 요청 차단을 검증하는 테스트 서비스입니다."},
    ).json()
    lock = client.app.state.container.project_locks._locks[project["id"]]
    client.portal.call(lock.acquire)
    try:
        response = client.post(
            f"/api/projects/{project['id']}/messages",
            json={"content": "같은 요청을 다시 보내지 마"},
        )
    finally:
        lock.release()

    assert response.status_code == 409
    assert "중복 LLM 과금" in response.json()["detail"]
