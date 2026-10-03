# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Log-retrieval port (Phase-2 C5, D-2.10).

A kernel-tier, SDK-free Protocol for fetching a bundle of log content for a
diagnostic entity (cluster / driver / service). The output feeds the diagnostic
substrate (``evidence_extractor`` -> ``root_cause_synthesizer``) unchanged.

The PUBLIC adapter parses delivered log4j/event logs from DBFS/Volumes (reusing
the log parser). A gated internal adapter (indexed log triage) is Phase 3 and
does not ship here — so nothing in this module names an internal backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LogQuery:
    """A request for logs for a single diagnostic entity.

    Attributes:
        entity: The entity kind — e.g. ``"cluster"``, ``"driver"``, ``"service"``.
        entity_id: Identifier of the entity (cluster id, run id, ...).
        paths: Explicit log paths/prefixes to read (DBFS/Volumes/cloud URIs).
        time_window_hours: Bound on the look-back window (public default 2h).
        filters: Optional free-form filters (level, container, ...).
    """

    entity: str
    entity_id: str
    paths: tuple[str, ...] = ()
    time_window_hours: float = 2.0
    filters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LogBundle:
    """Concatenated log content plus provenance.

    Attributes:
        text: The concatenated log text (consumable by the evidence extractor).
        source: A short descriptor of the adapter/source that produced it.
        line_count: Number of lines in ``text`` (0 when empty).
        paths: The paths that were actually read.
        metadata: Optional adapter metadata (byte counts, truncation, ...).
    """

    text: str
    source: str
    line_count: int = 0
    paths: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class LogRetrievalPort(Protocol):
    """Fetch a :class:`LogBundle` for a :class:`LogQuery`."""

    async def fetch(self, ref: LogQuery) -> LogBundle:
        """Retrieve logs described by ``ref`` and return them as a bundle."""
        ...
