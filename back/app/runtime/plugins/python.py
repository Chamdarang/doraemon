from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from .base import RuntimeHost


class PythonRuntimeAdapter:
    name = "python"

    def detect(self, cwd: Path) -> bool:
        return (cwd / "requirements.txt").is_file() or (cwd / "pyproject.toml").is_file()

    async def prepare(self, host: RuntimeHost, cwd: Path, log_handle: BinaryIO, env: dict[str, str]) -> None:
        inputs = [
            path
            for path in (cwd / "requirements.txt", cwd / "pyproject.toml", cwd / "poetry.lock", cwd / "uv.lock")
            if path.exists()
        ]
        signature = host.dependency_signature(inputs)
        stamp = cwd / ".pocket-python-deps"
        python = cwd / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            host._log(log_handle, "[Doraemon] Creating Python virtual environment...\n")
            await host._run(
                host.python_executable,
                ["-m", "venv", ".venv"],
                cwd,
                log_handle,
                env,
                "Python 가상환경 생성에 실패했습니다",
            )
        if host.read_stamp(stamp) == signature:
            return
        arguments = (
            ["-m", "pip", "install", "-r", "requirements.txt"]
            if (cwd / "requirements.txt").is_file()
            else ["-m", "pip", "install", "-e", "."]
        )
        host._log(log_handle, "[Doraemon] Installing Python dependencies...\n")
        await host._run(str(python), arguments, cwd, log_handle, env, "Python 의존성 설치에 실패했습니다")
        stamp.write_text(signature, encoding="utf-8")

    def resolve_command(self, cwd: Path, command: list[str]) -> tuple[str, list[str]] | None:
        if not command:
            return None
        name = Path(command[0]).name
        arguments = list(command[1:])
        venv_bin = cwd / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        lowered = name.lower()
        if lowered in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
            python = venv_bin / ("python.exe" if os.name == "nt" else "python")
            if python.is_file():
                return str(python), arguments
        candidates = [
            venv_bin / name,
            venv_bin / (f"{name}.exe" if os.name == "nt" and not name.endswith(".exe") else name),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate.resolve()), arguments
        return None
