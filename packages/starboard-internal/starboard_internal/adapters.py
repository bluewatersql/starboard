# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""No-op sample internal adapter (Phase-3 D-3.1).

Proves the ``starboard.port_adapters`` entry-point seam end-to-end without
shipping any real internal capability. The adapter is a pure no-op: it names no
internal namespace, backend, host, or internal shortlink, and it returns an empty
result. It is registered as an ``internal``-tier provider, so it is selected
**only** when the internal-data enablement gate is open (§3.5): with the gate
closed the public ``LogRetrievalPort`` adapter remains the universal path.

The real internal adapters (D6 logs/diagnostics, D7 fleet, D8 Genie) replace
this sample in later Phase-3 tasks.
"""

from __future__ import annotations

from starboard.ports.discovery import INTERNAL_TIER, SimplePortAdapterProvider
from starboard.ports.registry import Port
from starboard_core.ports.log_retrieval import LogBundle, LogQuery, LogRetrievalPort

#: Stable source tag for the sample bundle — deliberately generic (no backend id).
_NOOP_SOURCE = "starboard-internal-noop"


class NoOpLogRetrievalAdapter(LogRetrievalPort):
    """A gated internal ``LogRetrievalPort`` that returns an empty bundle.

    Sample only: it demonstrates that an internal-tier adapter registered via
    the entry-point contract supersedes the public adapter when the gate is
    open. It performs no retrieval and references nothing internal.
    """

    async def fetch(self, ref: LogQuery) -> LogBundle:
        return LogBundle(
            text="",
            source=_NOOP_SOURCE,
            line_count=0,
            paths=(),
            metadata={"noop": "true", "entity": ref.entity},
        )


#: Module-level provider the entry point resolves to (see pyproject.toml).
noop_sample_provider = SimplePortAdapterProvider(
    port=Port.LOG_RETRIEVAL,
    factory=NoOpLogRetrievalAdapter,
    tier=INTERNAL_TIER,
)
