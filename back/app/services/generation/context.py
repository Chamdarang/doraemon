"""Bounded, relevance-aware source context for paid LLM requests."""

from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
import json
import os
import re
from uuid import uuid4

IGNORED_DIRS = {"node_modules", ".venv", "dist", "build", "__pycache__", ".git", ".pocket", ".next", "coverage"}
IGNORED_FILES = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"}
ALLOWED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".html", ".md", ".toml", ".yaml", ".yml", ".txt"}
ESSENTIAL_NAMES = {
    "package.json", "requirements.txt", "pyproject.toml", "pom.xml", "build.gradle", "build.gradle.kts", "go.mod",
    "vite.config.ts", "vite.config.js", "tsconfig.json", "main.py", "main.ts", "main.tsx", "main.js", "main.jsx",
    "app.tsx", "app.jsx", "index.ts", "index.tsx",
}


def _source_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for area in ("back", "front"):
        base = root / area
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel_path = path.relative_to(root)
            if any(part in IGNORED_DIRS for part in rel_path.parts) or path.name in IGNORED_FILES:
                continue
            if path.name.endswith((".min.js", ".min.css")) or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            result[rel_path.as_posix()] = path
    return result


def _content_hashes(files: dict[str, Path]) -> dict[str, str]:
    result = {}
    for rel, path in files.items():
        try:
            result[rel] = sha256(path.read_bytes()).hexdigest()[:12]
        except OSError:
            continue
    return result


def load_context_manifest(root: Path, operation: str) -> dict[str, object]:
    path = root / ".pocket" / "llm-context" / f"{operation}.json"
    try:
        raw = json.loads(path.read_text("utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def changed_context_paths(root: Path, manifest: dict[str, object]) -> list[str]:
    previous = manifest.get("hashes")
    if not isinstance(previous, dict):
        return []
    current = _content_hashes(_source_files(root))
    return sorted(path for path, digest in current.items() if previous.get(path) != digest)


def save_context_manifest(root: Path, operation: str, selected_paths: Iterable[str]) -> None:
    files = _source_files(root)
    payload = {
        "hashes": _content_hashes(files),
        "selected_paths": sorted(set(selected_paths)),
    }
    path = root / ".pocket" / "llm-context" / f"{operation}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _resolve_import_graph(files: dict[str, Path]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    graph: dict[str, set[str]] = {path: set() for path in files}
    by_path = {Path(path): path for path in files}
    for rel, path in files.items():
        try:
            content = path.read_text("utf-8")
        except (OSError, UnicodeError):
            continue
        specs: list[tuple[str, bool]] = [
            (match, False)
            for match in re.findall(r"(?:from\s+|import\s*\(?\s*)[\"']([^\"']+)[\"']", content)
        ]
        if path.suffix == ".py":
            specs.extend(
                (match, True)
                for match in re.findall(r"^\s*(?:from|import)\s+([.\w]+)", content, re.MULTILINE)
            )
        for spec, is_python in specs:
            if is_python:
                leading = len(spec) - len(spec.lstrip("."))
                module = spec.lstrip(".").replace(".", "/")
                if leading:
                    base = Path(rel).parent
                    for _ in range(max(0, leading - 1)):
                        base = base.parent
                    bases = [base / module]
                else:
                    module_path = Path(module)
                    bases = [module_path, Path(rel).parents[1] / module_path]
            else:
                if not spec.startswith((".", "back/", "front/")):
                    continue
                bases = [Path(rel).parent / spec if spec.startswith(".") else Path(spec)]
            candidates = []
            for base in bases:
                candidates.extend([base, *(base.with_suffix(suffix) for suffix in sorted(ALLOWED_SUFFIXES))])
                candidates.extend(base / f"index{suffix}" for suffix in sorted(ALLOWED_SUFFIXES))
            normalized_candidates = [Path(os.path.normpath(candidate.as_posix())) for candidate in candidates]
            target = next((by_path[candidate] for candidate in normalized_candidates if candidate in by_path), None)
            if target:
                graph[rel].add(target)
    reverse: dict[str, set[str]] = {path: set() for path in files}
    for source, targets in graph.items():
        for target in targets:
            reverse[target].add(source)
    return graph, reverse


def select_context_paths(
    root: Path,
    query: str,
    previous_paths: Iterable[str] = (),
    changed_paths: Iterable[str] = (),
    max_paths: int = 35,
) -> list[str]:
    """Select entrypoints, explicitly relevant files, and one-hop import neighbors."""
    files = _source_files(root)
    previous = {Path(item).as_posix() for item in previous_paths if Path(item).as_posix() in files}
    changed = {Path(item).as_posix() for item in changed_paths if Path(item).as_posix() in files}
    selected = set(previous)
    lowered = query.lower()
    tokens = {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_.\-/]{2,}", query)}
    wants_front = any(word in lowered for word in ("front", "react", "화면", "ui", "ux", "디자인", "css", "버튼", "모바일"))
    wants_back = any(word in lowered for word in ("back", "api", "서버", "fastapi", "spring", "데이터", "db", "로그인", "인증"))
    for rel, path in files.items():
        rel_lower = rel.lower()
        if path.name.lower() in ESSENTIAL_NAMES:
            selected.add(rel)
        if any(token in rel_lower for token in tokens if len(token) >= 3):
            selected.add(rel)
        if wants_front and rel.startswith("front/") and path.suffix.lower() in {".tsx", ".jsx", ".css", ".html"}:
            selected.add(rel)
        if wants_back and rel.startswith("back/") and any(part in path.stem.lower() for part in ("main", "api", "router", "service", "model")):
            selected.add(rel)
    selected.update(path for path in changed if path in previous)
    if not wants_front and not wants_back and not previous_paths:
        selected.update(rel for rel, path in files.items() if path.name.lower() in ESSENTIAL_NAMES)
    graph, reverse = _resolve_import_graph(files)
    seeds = set(selected)
    for rel_path in seeds:
        selected.update(graph.get(rel_path, ()))
        selected.update(reverse.get(rel_path, ()))
    ranked = sorted(selected, key=lambda path: (
        0 if path in previous else 1 if path in changed else 2 if files[path].name.lower() in ESSENTIAL_NAMES else 3,
        path,
    ))
    return ranked[:max_paths]


def project_snapshot(
    root: Path,
    *,
    limit: int = 100_000,
    per_file_limit: int = 15_000,
    focus_paths: Iterable[str] = (),
    focused_only: bool = False,
) -> str:
    """Return a bounded snapshot with a complete hashed map and selected contents."""
    files = _source_files(root)
    focus = {Path(path).as_posix() for path in focus_paths}
    ordered = sorted(files.items(), key=lambda item: (0 if item[0] in focus else 1 if item[1].name.lower() in ESSENTIAL_NAMES else 2, item[0]))
    index_lines = []
    for rel, path in ordered:
        try:
            payload = path.read_bytes()
            index_lines.append(f"{rel}\t{len(payload)} bytes\tsha256:{sha256(payload).hexdigest()[:12]}")
        except OSError:
            index_lines.append(f"{rel}\tunreadable")
    parts = ["SOURCE MAP (path, size, content hash):\n" + "\n".join(index_lines), "\n\nSOURCE CONTENTS:\n"]
    used = sum(map(len, parts))
    omitted: list[str] = []
    for rel, path in ordered:
        if focused_only and rel not in focus and path.name.lower() not in ESSENTIAL_NAMES:
            omitted.append(rel)
            continue
        try:
            content = path.read_text("utf-8")
        except (OSError, UnicodeError):
            omitted.append(rel)
            continue
        if len(content) > per_file_limit:
            content = content[:per_file_limit] + f"\n\n[truncated: original length={len(content)} characters]"
        block = f"\n--- {rel} ---\n{content}\n"
        if used + len(block) > limit:
            omitted.append(rel)
            continue
        parts.append(block)
        used += len(block)
    if omitted:
        parts.append("\nCONTENT OMITTED (use the source map when planning paths):\n" + "\n".join(omitted))
    return "".join(parts)


def estimate_tokens(value: str) -> int:
    """Conservative provider-independent estimate for UI and activity reporting."""
    return max(1, (len(value) + 2) // 3)
