from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def validate_bounded_json[T](
    value: T,
    *,
    max_depth: int = 4,
    max_items: int = 50,
    max_string_length: int = 2_000,
) -> T:
    """Reject JSON-like metadata capable of hiding excessive nested content."""

    def walk(item: Any, depth: int) -> None:
        if depth > max_depth:
            raise ValueError("metadata nesting is too deep")
        if isinstance(item, str):
            if len(item) > max_string_length:
                raise ValueError("metadata string is too long")
            return
        if item is None or isinstance(item, (bool, int, float)):
            return
        if isinstance(item, Mapping):
            if len(item) > max_items:
                raise ValueError("metadata contains too many keys")
            for key, nested in item.items():
                if not isinstance(key, str) or len(key) > 128:
                    raise ValueError("metadata keys must be short strings")
                walk(nested, depth + 1)
            return
        if isinstance(item, Sequence) and not isinstance(item, (bytes, bytearray)):
            if len(item) > max_items:
                raise ValueError("metadata contains too many list items")
            for nested in item:
                walk(nested, depth + 1)
            return
        raise ValueError("metadata must contain JSON-compatible values only")

    walk(value, 0)
    return value
