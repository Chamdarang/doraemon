from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from .base import RuntimeHost


class GoRuntimeAdapter:
    name = "go"

    def detect(self, cwd: Path) -> bool:
        return (cwd / "go.mod").is_file()

    async def prepare(self, host: RuntimeHost, cwd: Path, log_handle: BinaryIO, env: dict[str, str]) -> None:
        inputs = [path for path in (cwd / "go.mod", cwd / "go.sum") if path.exists()]
        signature = host.dependency_signature(inputs)
        stamp = cwd / ".pocket-go-deps"
        if host.read_stamp(stamp) == signature:
            return
        go = shutil.which("go")
        if not go:
            raise ValueError("Go 프로젝트이지만 go 실행 파일을 찾을 수 없습니다")
        host._log(log_handle, "[Doraemon] Downloading Go modules...\n")
        await host._run(go, ["mod", "download"], cwd, log_handle, env, "Go 모듈 다운로드에 실패했습니다")
        stamp.write_text(signature, encoding="utf-8")

    def resolve_command(self, cwd: Path, command: list[str]) -> tuple[str, list[str]] | None:
        return None
