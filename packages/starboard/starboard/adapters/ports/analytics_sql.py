# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Public ``NLQueryPort`` adapter over native analytics-SQL generation (C5).

Wraps the existing ``LLMSQLGenerator``. No new capability — just the port
surface. The adapter builds a minimal intent/RAG context when the caller does
not supply one (via ``WorkspaceCtx``).
"""

from __future__ import annotations

from typing import Any, Protocol

from starboard_core.ports.nl_query import NLAnswer, NLQueryPort, WorkspaceCtx
from starboard_core.rag.models import RAGContext

from starboard.tools.domain.analytics_sql.models import (
    QueryDomain,
    QueryIntent,
    QueryIntentContext,
)


class _SqlGenerator(Protocol):
    """Structural type for the wrapped generator (see ``LLMSQLGenerator``)."""

    async def generate(
        self,
        user_query: str,
        intent_context: Any,
        rag_context: Any,
        previous_errors: list[str] | None = None,
    ) -> dict[str, Any]: ...


class AnalyticsSqlAdapter(NLQueryPort):
    """Answer NL questions with SQL via the native ``LLMSQLGenerator``.

    Args:
        generator: The SQL generator to delegate to.
        intent_builder: Optional callable ``(question, ctx) -> QueryIntentContext``
            used when ``ctx.intent_context`` is not supplied.
        rag_builder: Optional callable ``(question, ctx) -> RAGContext`` used when
            ``ctx.rag_context`` is not supplied.
    """

    def __init__(
        self,
        generator: _SqlGenerator,
        *,
        intent_builder: Any = None,
        rag_builder: Any = None,
    ) -> None:
        self._generator = generator
        self._intent_builder = intent_builder
        self._rag_builder = rag_builder

    async def ask(self, question: str, ctx: WorkspaceCtx) -> NLAnswer:
        intent_context = ctx.intent_context
        if intent_context is None:
            intent_context = (
                self._intent_builder(question, ctx)
                if self._intent_builder is not None
                else QueryIntentContext(
                    intent=QueryIntent.UNKNOWN,
                    domain=QueryDomain.UNKNOWN,
                    confidence=0.0,
                    reasoning="default minimal intent (no classifier supplied)",
                )
            )

        rag_context = ctx.rag_context
        if rag_context is None:
            rag_context = (
                self._rag_builder(question, ctx)
                if self._rag_builder is not None
                else RAGContext()
            )

        result = await self._generator.generate(question, intent_context, rag_context)
        return NLAnswer(
            success=bool(result.get("success", False)),
            sql=str(result.get("sql", "")),
            explanation=str(result.get("explanation", "")),
            metadata={
                k: v
                for k, v in result.items()
                if k not in ("success", "sql", "explanation")
            },
        )
