# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Bounded host exposure: the stdout envelope budget.

Pure, no I/O. :func:`bound` returns a JSON-safe copy of a helper envelope that
fits ``max_bytes`` when encoded the way :func:`encoded_size` measures it
(``json.dumps(x, default=str)``, compact, UTF-8). Callers must print it the same
way (no ``indent``) for the budget to hold.

Shrinking order, stopping as soon as it fits:

1. Always: drop raw row arrays (``rows``/``sample_rows``/``raw_rows``) and cap
   every list at :data:`MAX_LIST_ITEMS`.
2. Re-cap non-protected lists at 25, 10, 5, 1, 0 items. A list of at most
   :data:`SHORT_LIST_ITEMS` scalars is kept whole: cutting a definition list
   (``failed_states``) changes what it says and saves almost nothing.
3. Shorten long strings (512, 128, 32 characters), except ID values.
4. Drop non-protected keys (top level, then under ``data``), largest first.
5. Fall back to the ID keys only.

Every reduction sets ``truncated: true``; dropped or cut items are counted in
``omitted`` (``{path: count}``, list items aggregated as ``a.b[].c``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

__all__ = ["DEFAULT_MAX_BYTES", "MAX_LIST_ITEMS", "bound", "encoded_size"]

DEFAULT_MAX_BYTES = 24_000
MAX_LIST_ITEMS = 50
SHORT_LIST_ITEMS = 8
_ROW_KEYS = frozenset({"rows", "sample_rows", "raw_rows"})
_KEEP = frozenset(
    {
        "ok",
        "domain",
        "command",
        "run_id",
        "run_folder_id",
        "refs",
        "counts",
        "summary",
        "errors",
        "warnings",
    }
)
_ID_KEYS = ("ok", "domain", "command", "run_id", "run_folder_id")
_RECAPS = (25, 10, 5, 1, 0)
_STRING_LIMITS = (512, 128, 32)
_ELLIPSIS = "...[truncated]"


def encoded_size(payload: Any) -> int:
    """Byte size of ``json.dumps(payload, default=str)`` in UTF-8."""
    return len(json.dumps(payload, default=str).encode("utf-8"))


def _short_scalars(value: list[Any]) -> bool:
    return len(value) <= SHORT_LIST_ITEMS and not any(
        isinstance(v, (dict, list)) for v in value
    )


def _count(value: Any) -> int:
    return len(value) if isinstance(value, (list, dict)) else 1


class _Bounder:
    def __init__(self) -> None:
        self.omitted: dict[str, int] = {}
        self.truncated = False

    def omit(self, path: str, n: int) -> None:
        self.omitted[path] = self.omitted.get(path, 0) + n
        self.truncated = True

    def walk(
        self, value: Any, path: str, cap: int, drop_rows: bool, key: str | None
    ) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                p = f"{path}.{k}" if path else k
                if drop_rows and k in _ROW_KEYS and isinstance(v, list):
                    self.omit(p, len(v))
                    continue
                out[k] = self.walk(v, p, cap, drop_rows, k)
            return out
        if isinstance(value, list):
            limit = MAX_LIST_ITEMS if key in _KEEP else min(cap, MAX_LIST_ITEMS)
            if len(value) > limit and not _short_scalars(value):
                self.omit(path, len(value) - limit)
                value = value[:limit]
            return [self.walk(v, f"{path}[]", cap, drop_rows, None) for v in value]
        return value

    def shorten(self, value: Any, limit: int, key: str | None) -> Any:
        if isinstance(value, dict):
            return {k: self.shorten(v, limit, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.shorten(v, limit, None) for v in value]
        if isinstance(value, str) and key not in _ID_KEYS and len(value) > limit:
            self.truncated = True
            return value[:limit] + _ELLIPSIS
        return value

    def finish(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self.truncated:
            return data
        return {**data, "truncated": True, "omitted": dict(self.omitted)}


def bound(
    payload: Mapping[str, Any], *, max_bytes: int = DEFAULT_MAX_BYTES
) -> dict[str, Any]:
    """Return a JSON-safe copy of ``payload`` that fits ``max_bytes``.

    Keeps ``ok/domain/command/run_id/run_folder_id/refs/counts/summary`` (and
    the envelope's ``errors``/``warnings``) at the top level and under
    ``data``. ``payload`` is not modified.
    """
    data = json.loads(json.dumps(payload, default=str))
    if not isinstance(data, dict):
        raise TypeError("bound() needs a mapping payload")
    b = _Bounder()

    def fits(candidate: dict[str, Any]) -> bool:
        return encoded_size(b.finish(candidate)) <= max_bytes

    data = b.walk(data, "", MAX_LIST_ITEMS, True, None)
    if fits(data):
        return b.finish(data)
    for cap in _RECAPS:
        data = b.walk(data, "", cap, False, None)
        if fits(data):
            return b.finish(data)
    for limit in _STRING_LIMITS:
        data = b.shorten(data, limit, None)
        if fits(data):
            return b.finish(data)

    droppable: list[tuple[int, tuple[str, ...]]] = [
        (encoded_size(v), (k,)) for k, v in data.items() if k not in _KEEP
    ]
    inner = data.get("data")
    if isinstance(inner, dict):
        droppable += [
            (encoded_size(v), ("data", k)) for k, v in inner.items() if k not in _KEEP
        ]
    for _, path in sorted(droppable, key=lambda item: item[0], reverse=True):
        holder = data if len(path) == 1 else data.get("data")
        if not isinstance(holder, dict) or path[-1] not in holder:
            continue
        b.omit(".".join(path), _count(holder.pop(path[-1])))
        if fits(data):
            return b.finish(data)

    minimal: dict[str, Any] = {}
    for scope in (data, data.get("data") if isinstance(data.get("data"), dict) else {}):
        for k in _ID_KEYS:
            if k in scope and k not in minimal:
                minimal[k] = scope[k]
    b.truncated = True
    out = b.finish(minimal)
    if encoded_size(out) > max_bytes:
        out = {
            **minimal,
            "truncated": True,
            "omitted": {"*": sum(b.omitted.values()) or 1},
        }
    return out
