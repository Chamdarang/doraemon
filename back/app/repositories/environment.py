import json
import re
from urllib.parse import urlparse


class EnvironmentStoreMixin:
    """Generated-service environment discovery, validation and masking."""

    def runtime_env(self, project_id: str) -> dict[str, str]:
        values = self.read_env(project_id)
        return {
            key: re.sub(r"^mysql(?:\+pymysql)*://", "mysql+pymysql://", value) if isinstance(value, str) else value
            for key, value in values.items()
        }

    def read_env(self, project_id: str) -> dict[str, str]:
        path = self.project_dir(project_id) / ".env"
        if not path.exists():
            return {}
        result = {}
        for line in path.read_text("utf-8").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value
        return result

    def discover_env_keys(self, project_id: str) -> set[str]:
        root = self.project_dir(project_id)
        ignored = {"node_modules", ".venv", "dist", "build", "__pycache__"}
        patterns = (
            re.compile(r"(?:os\.getenv|os\.environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
            re.compile(r"os\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]"),
            re.compile(r"(?:process\.env|import\.meta\.env)\.([A-Z][A-Z0-9_]*)"),
        )
        keys: set[str] = set()
        for area in ("back", "front"):
            for path in (root / area).rglob("*"):
                if not path.is_file() or any(part in ignored for part in path.parts) or path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
                    continue
                try:
                    content = path.read_text("utf-8")
                except (OSError, UnicodeError):
                    continue
                for pattern in patterns:
                    keys.update(pattern.findall(content))
            for env_example in (root / area).glob(".env*"):
                if not env_example.is_file() or env_example.name == ".env":
                    continue
                try:
                    for line in env_example.read_text("utf-8").splitlines():
                        candidate = line.split("=", 1)[0].strip()
                        if re.fullmatch(r"[A-Z_][A-Z0-9_]*", candidate):
                            keys.add(candidate)
                except (OSError, UnicodeError):
                    continue
        return keys

    def write_env(self, project_id: str, values: dict[str, str]) -> None:
        manifest = self.get(project_id)
        specs = {item.key: item for item in manifest.runtime.environment}
        for key, value in values.items():
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
                raise ValueError(f"잘못된 환경변수 이름: {key}")
            if "\n" in value or "\r" in value:
                raise ValueError("환경변수 값에는 줄바꿈을 사용할 수 없습니다")
            spec = specs.get(key)
            looks_secret = any(marker in key for marker in ("SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY", "API_KEY"))
            if key.startswith(("VITE_", "NEXT_PUBLIC_")) and looks_secret:
                raise ValueError(f"비밀값으로 보이는 환경변수는 프론트 공개 접두사를 사용할 수 없습니다: {key}")
            if spec:
                if spec.secret and (spec.client_exposed or key.startswith(("VITE_", "NEXT_PUBLIC_"))):
                    raise ValueError(f"비밀 환경변수는 프론트에 노출할 수 없습니다: {key}")
                self._validate_env_format(key, value, spec.format)
        path = self.project_dir(project_id) / ".env"
        self._write_text_atomic(path, "".join(f"{key}={value}\n" for key, value in sorted(values.items())))

    @staticmethod
    def _validate_env_format(key: str, value: str, format_name: str) -> None:
        if not value:
            return
        try:
            if format_name == "integer":
                int(value)
            elif format_name == "boolean" and value.lower() not in {"true", "false", "1", "0"}:
                raise ValueError
            elif format_name == "json":
                json.loads(value)
            elif format_name == "url":
                parsed = urlparse(value)
                if not parsed.scheme or not parsed.netloc:
                    raise ValueError
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"환경변수 형식이 올바르지 않습니다 ({format_name}): {key}") from exc

    @staticmethod
    def masked_env(values: dict[str, str]) -> dict[str, str]:
        return {key: ("********" if value else "") for key, value in values.items()}
