from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel
from pydantic_core import to_jsonable_python


def canonical_json_bytes(value: Any) -> bytes:
    payload = to_jsonable_python(value)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_fingerprint(value: BaseModel | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
