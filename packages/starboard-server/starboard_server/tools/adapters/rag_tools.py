"""Analytics Agent V3: build_analytics_context tool (Agentic RAG).

This module intentionally exposes a SINGLE agent-callable tool:
`build_analytics_context`.

Key design points:
- Always retrieve Tables + Nuance collections
- Optionally retrieve Codebook / Facets / Learnings collections
- Uses `rag_resource_domain` as the RAG resource-model domain field
  (distinct from agent routing domains like job/query/warehouse/etc.)
- Gracefully degrades when embedding endpoint is unavailable
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from starboard_core.rag.models import RAGContext

from starboard_server.exceptions import AdapterError
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.adapters.base import BaseToolAdapter

if TYPE_CHECKING:
    from starboard_server.infra.rag.domain import (
        EmbeddingProvider,
        MultiCollectionStore,
    )

logger = get_logger(__name__)


class AnalyticsContextTools(BaseToolAdapter):
    """Agent-callable tool to build RAG context for analytics SQL generation."""

    def __init__(
        self,
        vector_store: MultiCollectionStore,
        embedding_provider: EmbeddingProvider,
        analytics_sql_tools: Any | None = None,
    ):
        """Initialize analytics context tools.

        Args:
            vector_store: Multi-collection vector store
            embedding_provider: Provider for generating embeddings
            analytics_sql_tools: Optional SQL tools instance for context handle storage
        """
        super().__init__()
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.analytics_sql_tools = analytics_sql_tools

    async def build_analytics_context(
        self,
        user_query: str,
        rag_resource_domains: list[str] | None = None,
        *,
        include_tables: bool = True,
        include_nuance: bool = True,
        include_codebook: bool = False,
        include_facets: bool = False,
        include_learnings: bool = False,
        agent_domain: str = "analytics",
        n_tables: int = 5,
        n_nuances: int = 15,
        n_codebook: int = 5,
        n_facets: int = 10,
        n_learnings: int = 3,
    ) -> dict[str, Any]:
        """
        Build a complete context bundle for analytics SQL generation.

        Always retrieves Tables + Nuance collections. Optionally retrieves
        Codebook, Facets, and Learnings.
        """
        if not user_query or not user_query.strip():
            raise ValueError("user_query cannot be empty")

        query = user_query.strip()

        # Normalize domains: accept list or JSON/string inputs from LLM
        domains: list[str] | None
        if rag_resource_domains is None:
            domains = None
        elif isinstance(rag_resource_domains, str):
            try:
                parsed = json.loads(rag_resource_domains)
                if isinstance(parsed, list):
                    domains = [str(d).strip() for d in parsed if str(d).strip()]
                else:
                    domains = (
                        [rag_resource_domains.strip()]
                        if rag_resource_domains.strip()
                        else None
                    )
            except json.JSONDecodeError:
                # Fallback: comma/space separated string
                parts = [
                    p.strip() for p in rag_resource_domains.split(",") if p.strip()
                ]
                domains = parts or None
        else:
            domains = [d.strip() for d in rag_resource_domains if d and str(d).strip()]
            if not domains:
                domains = None

        enabled = {
            "Tables": include_tables,
            "Nuance": include_nuance,
            "Facets": include_facets,
            "Codebook": include_codebook,
        }

        collections = [name for name, flag in enabled.items() if flag]
        n_results_per_collection = max(n_tables, n_nuances, n_facets, n_codebook)

        logger.debug(
            "build_analytics_context_called",
            extra={
                "query": query,
                "rag_resource_domains": domains,
                "collections": collections,
                "n_results_per_collection": n_results_per_collection,
                "agent_domain": agent_domain,
            },
        )

        try:
            rag_context = await self.vector_store.search_multi_collection(
                query=query,
                collections=collections,
                n_results_per_collection=n_results_per_collection,
                domains=domains,
            )
        except (AdapterError, ValueError):
            logger.warning(
                "embedding_search_failed_using_empty_context",
                extra={
                    "query": query,
                    "collections": collections,
                    "domains": domains,
                },
                exc_info=True,
            )
            rag_context = RAGContext()

        if include_learnings:
            rag_context.learnings = []

        rag_context.tables = rag_context.tables[:n_tables]
        rag_context.nuance = rag_context.nuance[:n_nuances]
        rag_context.codebook = rag_context.codebook[:n_codebook]
        rag_context.facets = rag_context.facets[:n_facets]
        rag_context.learnings = rag_context.learnings[:n_learnings]

        # Store context and return handle (token-efficient approach)
        if self.analytics_sql_tools:
            context_handle = self.analytics_sql_tools.store_rag_context(rag_context)

            return {
                "context_handle": context_handle,
                "summary": {
                    "tables_found": len(rag_context.tables),
                    "nuance_found": len(rag_context.nuance),
                    "codebook_found": len(rag_context.codebook),
                    "facets_found": len(rag_context.facets),
                    "learnings_found": len(rag_context.learnings),
                    "domains_searched": domains,
                },
            }
        else:
            # Fallback: return full context (for backward compatibility)
            logger.warning(
                "analytics_sql_tools_not_injected",
                extra={"message": "Returning full context instead of handle"},
            )
            return rag_context.model_dump()
