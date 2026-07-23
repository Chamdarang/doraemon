from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import BinaryIO

from .base import RuntimeHost


class NodeRuntimeAdapter:
    name = "node"

    def detect(self, cwd: Path) -> bool:
        return (cwd / "package.json").is_file()

    async def prepare(self, host: RuntimeHost, cwd: Path, log_handle: BinaryIO, env: dict[str, str]) -> None:
        inputs = [
            path
            for path in (
                cwd / "package.json",
                cwd / "package-lock.json",
                cwd / "npm-shrinkwrap.json",
                cwd / "pnpm-lock.yaml",
                cwd / "yarn.lock",
                cwd / "bun.lock",
                cwd / "bun.lockb",
            )
            if path.exists()
        ]
        signature = host.dependency_signature(inputs)
        stamp = cwd / ".pocket-node-deps"
        if (cwd / "node_modules").is_dir() and host.read_stamp(stamp) == signature:
            return
        executable, arguments, label = self.installer(cwd)
        host._log(log_handle, f"[Doraemon] Installing {label} dependencies...\n")
        await host._run(executable, arguments, cwd, log_handle, env, f"{label} 의존성 설치에 실패했습니다")
        stamp.write_text(signature, encoding="utf-8")

    @staticmethod
    def installer(cwd: Path) -> tuple[str, list[str], str]:
        if (cwd / "pnpm-lock.yaml").is_file():
            return NodeRuntimeAdapter.package_manager("pnpm", ["install", "--frozen-lockfile"])
        if (cwd / "yarn.lock").is_file():
            return NodeRuntimeAdapter.package_manager("yarn", ["install"])
        if (cwd / "bun.lock").is_file() or (cwd / "bun.lockb").is_file():
            bun = shutil.which("bun")
            if not bun:
                raise ValueError("bun.lock이 있지만 bun 실행 파일을 찾을 수 없습니다")
            return bun, ["install", "--frozen-lockfile"], "bun"
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            raise ValueError("Node.js 프로젝트이지만 npm 실행 파일을 찾을 수 없습니다")
        return npm, ["install", "--no-audit", "--no-fund"], "npm"

    @staticmethod
    def package_manager(name: str, arguments: list[str]) -> tuple[str, list[str], str]:
        executable = shutil.which(f"{name}.cmd") or shutil.which(name)
        if executable:
            return executable, arguments, name
        corepack = shutil.which("corepack.cmd") or shutil.which("corepack")
        if corepack:
            return corepack, [name, *arguments], name
        raise ValueError(f"{name} 잠금 파일이 있지만 {name} 또는 corepack을 찾을 수 없습니다")

    def resolve_command(self, cwd: Path, command: list[str]) -> tuple[str, list[str]] | None:
        if not command:
            return None
        name = Path(command[0]).name
        arguments = list(command[1:])
        node_bin = cwd / "node_modules" / ".bin"
        candidates = [
            node_bin / name,
            node_bin / (f"{name}.cmd" if os.name == "nt" and not name.endswith(".cmd") else name),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate.resolve()), arguments
        lowered = name.lower()
        if lowered in {"pnpm", "pnpm.cmd", "yarn", "yarn.cmd"}:
            corepack = shutil.which("corepack.cmd") or shutil.which("corepack")
            if corepack:
                return corepack, [lowered.split(".")[0], *arguments]
        return None
