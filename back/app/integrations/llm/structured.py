from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def decode_structured_payload(text: str) -> Any:
    """Decode one JSON value, accepting only an optional outer Markdown fence."""
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    return json.loads(fenced.group(1) if fenced else cleaned)


def normalize_structured_payload(payload: Any) -> Any:
    """Normalize known cross-provider schema deviations without guessing broken JSON."""
    if not isinstance(payload, dict):
        return payload
    files = payload.get("files")
    if isinstance(files, dict):
        payload["files"] = [
            {
                "path": path,
                "content": value.get("content", "") if isinstance(value, dict) else value,
            }
            for path, value in files.items()
        ]
    deleted = payload.get("deleted_files")
    if isinstance(deleted, str):
        payload["deleted_files"] = [deleted] if deleted.startswith(("back/", "front/")) else []
    if isinstance(payload.get("runtime"), str):
        payload["runtime"] = None
    return payload


def parse_structured_output(text: str, model: type[T]) -> T:
    return model.model_validate(normalize_structured_payload(decode_structured_payload(text)))
