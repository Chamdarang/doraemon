from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Protocol


class RuntimeHost(Protocol):
    python_executable: str

    async def _run(
        self,
        executable: str,
        arguments: list[str],
        cwd: Path,
        log_handle: BinaryIO,
        env: dict[str, str],
        error: str,
    ) -> None: ...

    def dependency_signature(self, paths: list[Path]) -> str: ...

    def read_stamp(self, path: Path) -> str: ...

    def _log(self, handle: BinaryIO, message: str) -> None: ...


class RuntimeAdapter(Protocol):
    name: str

    def detect(self, cwd: Path) -> bool: ...

    async def prepare(
        self,
        host: RuntimeHost,
        cwd: Path,
        log_handle: BinaryIO,
        env: dict[str, str],
    ) -> None: ...

    def resolve_command(self, cwd: Path, command: list[str]) -> tuple[str, list[str]] | None: ...
