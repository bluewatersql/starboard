# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Natural-language query port (Phase-2 C5, D-2.10).

A kernel-tier, SDK-free Protocol for answering a natural-language question about
a workspace with generated SQL.

The PUBLIC adapter is backed by native analytics-SQL generation. A gated
internal adapter (curated NL rooms) is Phase 3 and does not ship here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class WorkspaceCtx:
    """Context for an NL query.

    ``intent_context`` / ``rag_context`` are intentionally opaque (``Any``) so
    the kernel port stays SDK- and model-free; the concrete adapter interprets
    them (e.g. an analytics ``QueryIntentContext`` / ``RAGContext``).

    Attributes:
        host: Optional workspace host (informational only).
        warehouse_id: Optional SQL warehouse id.
        intent_context: Optional pre-built, adapter-specific intent context.
        rag_context: Optional pre-built, adapter-specific retrieval context.
        extra: Free-form additional context.
    """

    host: str | None = None
    warehouse_id: str | None = None
    intent_context: Any = None
    rag_context: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NLAnswer:
    """The answer to an NL query.

    Attributes:
        success: Whether generation succeeded.
        sql: The generated SQL (empty on failure).
        explanation: Brief explanation of the query logic.
        metadata: Optional adapter metadata.
    """

    success: bool
    sql: str = ""
    explanation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class NLQueryPort(Protocol):
    """Answer a natural-language question with generated SQL."""

    async def ask(self, question: str, ctx: WorkspaceCtx) -> NLAnswer:
        """Answer ``question`` within ``ctx`` and return an :class:`NLAnswer`."""
        ...
