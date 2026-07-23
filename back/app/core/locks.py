"""In-process serialization for mutations of one generated service."""

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager


class ProjectBusyError(RuntimeError):
    pass


class ProjectLockRegistry:
    def __init__(self):
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @asynccontextmanager
    async def hold(self, project_id: str, *, wait: bool = True):
        lock = self._locks[project_id]
        if not wait and lock.locked():
            raise ProjectBusyError(project_id)
        async with lock:
            yield

    def is_locked(self, project_id: str) -> bool:
        return self._locks[project_id].locked()
