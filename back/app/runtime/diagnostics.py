"""Fast advisory checks that never gate generated artifact application."""

from pathlib import Path

from app.repositories.store import ProjectStore


class RuntimeDiagnostics:
    def __init__(self, store: ProjectStore):
        self.store = store

    def inspect(self, project_id: str) -> list[str]:
        project = self.store.get(project_id)
        root = self.store.project_dir(project_id)
        findings: list[str] = []
        for target in ("backend", "frontend"):
            area = root / ("back" if target == "backend" else "front")
            command = getattr(project.runtime, f"{target}_command")
            label = "백엔드" if target == "backend" else "프론트엔드"
            if not command:
                findings.append(f"{label}: 실행 명령이 비어 있습니다")
                continue
            executable = Path(command[0]).name.lower()
            expected: tuple[str, ...] = ()
            if executable in {"python", "python.exe", "py", "uvicorn", "gunicorn"}:
                expected = ("pyproject.toml", "requirements.txt")
            elif executable in {"node", "node.exe", "npm", "npm.cmd", "pnpm", "yarn", "bun"}:
                expected = ("package.json",)
            elif executable in {"java", "java.exe", "mvn", "mvn.cmd", "gradle", "gradle.bat"}:
                expected = ("pom.xml", "build.gradle", "build.gradle.kts")
            elif executable in {"go", "go.exe"}:
                expected = ("go.mod",)
            if expected and not any((area / name).is_file() for name in expected):
                findings.append(f"{label}: {' 또는 '.join(expected)} 의존성 명세를 찾지 못했습니다")
            for argument in command[1:]:
                candidate = area / argument
                if argument.endswith((".py", ".js", ".mjs", ".cjs", ".jar")) and not candidate.exists():
                    findings.append(f"{label}: 실행 명령이 참조하는 파일이 없습니다 ({argument})")
        return findings
