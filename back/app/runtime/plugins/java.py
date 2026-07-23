from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from .base import RuntimeHost


class JavaRuntimeAdapter:
    name = "java"

    def detect(self, cwd: Path) -> bool:
        return any((cwd / name).is_file() for name in ("pom.xml", "build.gradle", "build.gradle.kts", "mvnw", "mvnw.cmd", "gradlew", "gradlew.bat"))

    async def prepare(self, host: RuntimeHost, cwd: Path, log_handle: BinaryIO, env: dict[str, str]) -> None:
        return None

    def resolve_command(self, cwd: Path, command: list[str]) -> tuple[str, list[str]] | None:
        if not command:
            return None
        name = Path(command[0]).name.lower()
        arguments = list(command[1:])
        wrappers = {
            "mvn": "mvnw.cmd" if os.name == "nt" else "mvnw",
            "mvn.cmd": "mvnw.cmd" if os.name == "nt" else "mvnw",
            "mvnw": "mvnw.cmd" if os.name == "nt" else "mvnw",
            "mvnw.cmd": "mvnw.cmd" if os.name == "nt" else "mvnw",
            "gradle": "gradlew.bat" if os.name == "nt" else "gradlew",
            "gradle.bat": "gradlew.bat" if os.name == "nt" else "gradlew",
            "gradlew": "gradlew.bat" if os.name == "nt" else "gradlew",
            "gradlew.bat": "gradlew.bat" if os.name == "nt" else "gradlew",
        }
        wrapper = cwd / wrappers.get(name, "")
        return (str(wrapper.resolve()), arguments) if wrapper.is_file() else None
