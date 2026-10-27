# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Engagement run IDs and idempotency keys (engagement-drive spec §2).

A run ID is ``YYYYMMDD_<full lowercase UUIDv4>``. The date is UTC and purely
informational; uniqueness comes from the UUID. Run IDs carry no sensitive
content, so they are safe in folder names.

The idempotency key is generated once per run from the run ID (plus optional
scoping parts) and persisted before acquisition, so a retry that reuses the run
ID reproduces the identical key and can find, rather than duplicate, the
objects it already created.

Standard library only.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime

_RUN_ID_RE = re.compile(
    r"(\d{8})_([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})"
)
_KEY_PREFIX = "sbk1_"


def new_run_id(
    now: datetime | None = None,
    uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
) -> str:
    """Create a fresh run ID.

    Args:
        now: Timestamp for the date part (default: the current time). Naive
            values are taken as UTC; aware values are converted to UTC.
        uuid_factory: Source of the UUIDv4 (injectable for tests).

    Raises:
        ValueError: if the factory does not produce a valid UUIDv4.
    """
    moment = datetime.now(UTC) if now is None else now
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    run_id = f"{moment:%Y%m%d}_{uuid_factory()}"
    if not is_run_id(run_id):
        raise ValueError(f"uuid_factory did not produce a lowercase UUIDv4: {run_id!r}")
    return run_id


def parse_run_id(value: str) -> tuple[date, uuid.UUID]:
    """Split a run ID into its UTC date and UUID.

    Raises:
        ValueError: on any malformed ID (uppercase, non-v4, impossible date).
    """
    match = _RUN_ID_RE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(f"not a valid run ID: {value!r}")
    stamp, raw = match.groups()
    try:
        day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
    except ValueError as exc:
        raise ValueError(f"not a valid run ID (bad date): {value!r}") from exc
    return day, uuid.UUID(raw)


def is_run_id(value: str) -> bool:
    """Whether ``value`` is a well-formed run ID."""
    try:
        parse_run_id(value)
    except ValueError:
        return False
    return True


def idempotency_key(run_id: str, *parts: str) -> str:
    """Derive a deterministic idempotency key for a run.

    Each input is length-prefixed before hashing, so the join is unambiguous:
    ``("ab", "c")`` and ``("a", "bc")`` produce different keys.

    Raises:
        ValueError: if ``run_id`` is malformed.
    """
    parse_run_id(run_id)
    digest = hashlib.sha256()
    for item in (run_id, *parts):
        raw = item.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return _KEY_PREFIX + digest.hexdigest()
