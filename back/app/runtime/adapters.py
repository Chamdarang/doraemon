import asyncio
import hashlib
import shutil
import sys
from pathlib import Path
from typing import BinaryIO

from app.runtime.plugins import (
    GoRuntimeAdapter,
    JavaRuntimeAdapter,
    NodeRuntimeAdapter,
    PythonRuntimeAdapter,
    RuntimeAdapterRegistry,
)
from app.runtime.plugins.base import RuntimeAdapter


class RuntimeDependencyManager:
    """Backward-compatible facade over independently extensible runtime adapters."""

    def __init__(
        self,
        python_executable: str | None = None,
        adapters: list[RuntimeAdapter] | None = None,
    ):
        self.python_executable = python_executable or sys.executable
        self.registry = RuntimeAdapterRegistry(
            adapters
            or [
                PythonRuntimeAdapter(),
                NodeRuntimeAdapter(),
                GoRuntimeAdapter(),
                JavaRuntimeAdapter(),
            ]
        )

    async def prepare(self, cwd: Path, log_handle: BinaryIO, env: dict[str, str]) -> None:
        await self.registry.prepare(self, cwd, log_handle, env)

    # Compatibility methods kept for existing callers and focused adapter tests.
    async def _prepare_node(self, cwd: Path, log_handle: BinaryIO, env: dict[str, str]) -> None:
        await NodeRuntimeAdapter().prepare(self, cwd, log_handle, env)

    async def _prepare_python(self, cwd: Path, log_handle: BinaryIO, env: dict[str, str]) -> None:
        await PythonRuntimeAdapter().prepare(self, cwd, log_handle, env)

    async def _prepare_go(self, cwd: Path, log_handle: BinaryIO, env: dict[str, str]) -> None:
        await GoRuntimeAdapter().prepare(self, cwd, log_handle, env)

    @staticmethod
    def _node_installer(cwd: Path) -> tuple[str, list[str], str]:
        return NodeRuntimeAdapter.installer(cwd)

    @staticmethod
    def _package_manager(name: str, arguments: list[str]) -> tuple[str, list[str], str]:
        return NodeRuntimeAdapter.package_manager(name, arguments)

    @staticmethod
    async def _run(
        executable: str,
        arguments: list[str],
        cwd: Path,
        log_handle: BinaryIO,
        env: dict[str, str],
        error: str,
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            cwd=cwd,
            env=env,
            stdout=log_handle,
            stderr=asyncio.subprocess.STDOUT,
        )
        if await process.wait() != 0:
            raise ValueError(f"{error}. 로그를 확인해주세요")

    def _resolve_command(self, cwd: Path, command: list[str]) -> tuple[str, list[str]] | None:
        if not command:
            return None
        if resolved := self.registry.resolve_command(cwd, command):
            return resolved
        value, arguments = command[0], list(command[1:])
        local = cwd / value
        if local.is_file():
            return str(local.resolve()), arguments
        executable = shutil.which(value)
        return (executable, arguments) if executable else None

    @staticmethod
    def resolve_command(cwd: Path, command: list[str]) -> tuple[str, list[str]] | None:
        return RuntimeDependencyManager()._resolve_command(cwd, command)

    @staticmethod
    def dependency_signature(paths: list[Path]) -> str:
        digest = hashlib.sha256()
        for path in paths:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def read_stamp(path: Path) -> str:
        try:
            return path.read_text("utf-8").strip()
        except OSError:
            return ""

    @staticmethod
    def _log(handle: BinaryIO, message: str) -> None:
        handle.write(message.encode("utf-8"))
        handle.flush()
