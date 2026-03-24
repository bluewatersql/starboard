"""Fast JSON serialization using orjson.

Drop-in replacement for stdlib json in hot paths (SSE, API, tools, state).
orjson is 3-10x faster and natively handles datetime, UUID, dataclasses.

Usage:
    from starboard_server.infra.serialization import json_dumps, json_loads

    data = json_loads(raw_bytes)
    text = json_dumps(data)
"""

from __future__ import annotations

from typing import Any

import orjson


def json_dumps(obj: Any) -> str:
    """Serialize to JSON string (UTF-8 decoded)."""
    return orjson.dumps(obj).decode("utf-8")


def json_dumps_sorted(obj: Any) -> str:
    """Serialize to JSON string with sorted keys (for deterministic hashing)."""
    return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS).decode("utf-8")


def json_dumps_bytes(obj: Any) -> bytes:
    """Serialize to JSON bytes (zero-copy, ideal for SSE/HTTP)."""
    return orjson.dumps(obj)


def json_loads(data: str | bytes) -> Any:
    """Deserialize JSON from str or bytes."""
    return orjson.loads(data)
