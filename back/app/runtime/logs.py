from pathlib import Path


class ProcessLogStore:
    """Owns bounded process log files and cursor-based reads."""

    @classmethod
    def append_chunk(cls, path: Path, chunk: bytes, max_bytes: int) -> None:
        if len(chunk) >= max_bytes:
            chunk = chunk[-max_bytes:]
        current_size = path.stat().st_size if path.exists() else 0
        if current_size and current_size + len(chunk) > max_bytes:
            cls.rotate(path)
        with path.open("ab") as handle:
            handle.write(chunk)

    @classmethod
    def rotate_if_needed(cls, path: Path, max_bytes: int) -> None:
        if path.exists() and path.stat().st_size >= max_bytes:
            cls.rotate(path)

    @classmethod
    def reset_for_start(cls, path: Path) -> None:
        """Archive the previous run and give the new run an empty current log."""
        if not path.exists():
            return
        if path.stat().st_size:
            cls.rotate(path)
        else:
            path.unlink()

    @staticmethod
    def rotate(path: Path) -> None:
        rotated = path.with_suffix(f"{path.suffix}.1")
        rotated.unlink(missing_ok=True)
        path.replace(rotated)

    @staticmethod
    def startup_detail(path: Path) -> str:
        try:
            lines = path.read_text("utf-8", errors="replace").splitlines()[-20:]
        except OSError:
            return ""
        detail = "\n".join(lines).strip()
        return f"\n\n최근 로그:\n{detail[-3000:]}" if detail else ""

    @staticmethod
    def tail(path: Path, lines: int = 300) -> str:
        if not path.exists():
            return ""
        return "\n".join(path.read_text("utf-8", errors="replace").splitlines()[-lines:])

    @staticmethod
    def chunk(
        path: Path,
        cursor: int = 0,
        log_id: str = "",
        max_bytes: int = 131_072,
    ) -> dict[str, str | int | bool]:
        if not path.exists():
            return {"logs": "", "cursor": 0, "log_id": "", "reset": bool(cursor or log_id)}
        stat = path.stat()
        file_identity = stat.st_ino or stat.st_ctime_ns
        current_id = f"{stat.st_dev:x}:{file_identity:x}"
        reset = bool(log_id and log_id != current_id) or cursor < 0 or cursor > stat.st_size
        start = cursor
        if reset or not log_id:
            start = max(0, stat.st_size - max_bytes)
            reset = True
        with path.open("rb") as handle:
            handle.seek(start)
            content = handle.read(max_bytes)
        return {
            "logs": content.decode("utf-8", errors="replace"),
            "cursor": start + len(content),
            "log_id": current_id,
            "reset": reset,
        }
