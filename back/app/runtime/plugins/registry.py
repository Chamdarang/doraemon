from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from .base import RuntimeAdapter, RuntimeHost


class RuntimeAdapterRegistry:
    def __init__(self, adapters: list[RuntimeAdapter]):
        self.adapters = adapters

    def detected(self, cwd: Path) -> list[RuntimeAdapter]:
        return [adapter for adapter in self.adapters if adapter.detect(cwd)]

    async def prepare(self, host: RuntimeHost, cwd: Path, log_handle: BinaryIO, env: dict[str, str]) -> None:
        for adapter in self.detected(cwd):
            await adapter.prepare(host, cwd, log_handle, env)

    def resolve_command(self, cwd: Path, command: list[str]) -> tuple[str, list[str]] | None:
        for adapter in self.adapters:
            if result := adapter.resolve_command(cwd, command):
                return result
        return None
