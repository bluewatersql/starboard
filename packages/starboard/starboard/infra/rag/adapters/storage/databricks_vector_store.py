# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Managed Databricks Vector Search store (opt-in escape hatch).

This adapter is the **opt-in** ANN path for the analytics agent, gated behind
``starboard[vectorsearch]`` (which pins ``databricks-vectorsearch``). It is NOT
on the default path — the default (``vector_backend="none"``) reads curated
reference files from disk with no embeddings (Phase 2 C1, D-2.3).

It queries a managed delta-sync Vector Search index (one index per collection)
over UC Delta tables using the same ``WorkspaceClient``/credentials the auth
resolver provides — no self-managed vector store.

``databricks-vectorsearch`` is imported lazily inside ``initialize()`` so a
default (no-extras) install never imports it. Only ``search_multi_collection``
(the sole method ``build_analytics_context`` calls) performs retrieval; the
low-level per-collection ``query_*``/``upsert_*`` primitives are intentionally
deferred (managed index ingestion is delta-sync, not client-side upsert) and
raise ``NotImplementedError`` with an actionable message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_core.rag.models import (
    RAGCodebookContext,
    RAGContext,
    RAGFacetContext,
    RAGNuanceContext,
    RAGTableContext,
)

from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.infra.core.config import EnvConfig
    from starboard.infra.rag.domain.protocols import EmbeddingProvider

logger = get_logger(__name__)

# Collection name -> RAGContext field / model.
_COLLECTION_MODELS: dict[str, tuple[str, type]] = {
    "Tables": ("tables", RAGTableContext),
    "Nuance": ("nuance", RAGNuanceContext),
    "Facets": ("facets", RAGFacetContext),
    "Codebook": ("codebook", RAGCodebookContext),
}


class DatabricksVectorSearchStore:
    """Managed Databricks Vector Search adapter (opt-in, behind [vectorsearch])."""

    def __init__(
        self,
        config: EnvConfig,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_dim: int = 1024,
    ) -> None:
        self._config = config
        self.embedding_provider = embedding_provider
        self.embedding_dim = getattr(config, "embedding_dimension", embedding_dim)
        self._client: Any | None = None
        # Endpoint + per-collection index names are read from config; a hosted
        # deployment provisions the managed delta-sync indexes out of band.
        self._endpoint_name = getattr(
            config, "vectorsearch_endpoint", "starboard-rag"
        )
        self._index_prefix = getattr(
            config, "vectorsearch_index_prefix", "starboard.rag"
        )

    async def initialize(self) -> None:
        """Lazily construct the managed Vector Search client.

        Raises:
            ImportError: if ``databricks-vectorsearch`` is not installed (the
                caller in ``vector_store_factory`` degrades to ``None``).
        """
        from databricks.vector_search.client import (  # type: ignore[import-not-found,import-untyped]
            VectorSearchClient,
        )

        self._client = VectorSearchClient(disable_notice=True)
        logger.info(
            "databricks_vector_search_client_ready",
            endpoint=self._endpoint_name,
            index_prefix=self._index_prefix,
        )

    def _index_name(self, collection: str) -> str:
        return f"{self._index_prefix}.{collection.lower()}"

    async def generate_embedding(self, text: str) -> list[float]:
        if not self.embedding_provider:
            raise ValueError("No embedding provider configured")
        return await self.embedding_provider.embed(text)

    async def search_multi_collection(
        self,
        query: str,
        *,
        collections: list[str],
        n_results_per_collection: int = 10,
        domains: list[str] | None = None,
    ) -> RAGContext:
        """Query the managed indexes for the requested collections."""
        if self._client is None:
            await self.initialize()

        context = RAGContext()
        for collection in collections:
            mapping = _COLLECTION_MODELS.get(collection)
            if mapping is None:
                continue
            field, model = mapping
            try:
                index = self._client.get_index(  # type: ignore[union-attr]
                    endpoint_name=self._endpoint_name,
                    index_name=self._index_name(collection),
                )
                filters = {"domain": domains} if domains else None
                resp = index.similarity_search(
                    query_text=query,
                    columns=["*"],
                    num_results=n_results_per_collection,
                    filters=filters,
                )
                items = _rows_to_models(resp, model)
                getattr(context, field).extend(items)
            except Exception as e:  # noqa: BLE001 - per-collection degrade
                logger.warning(
                    "vector_search_collection_query_failed",
                    collection=collection,
                    error=str(e),
                    error_type=type(e).__name__,
                )
        return context

    async def close(self) -> None:
        self._client = None

    async def connect(self) -> None:  # pragma: no cover - lifecycle parity
        if self._client is None:
            await self.initialize()

    # --- Deferred primitives (managed index ingestion is delta-sync) --------
    def _not_supported(self, op: str) -> NotImplementedError:
        return NotImplementedError(
            f"{op} is not supported on the managed Vector Search adapter; "
            "the delta-sync index ingests from its UC Delta source table."
        )

    async def query_multi_collection(
        self, *_args: Any, **_kwargs: Any
    ) -> RAGContext:
        raise self._not_supported("query_multi_collection")

    async def query_tables(self, *_args: Any, **_kwargs: Any) -> list[RAGTableContext]:
        raise self._not_supported("query_tables")

    async def query_nuance(self, *_args: Any, **_kwargs: Any) -> list[RAGNuanceContext]:
        raise self._not_supported("query_nuance")

    async def query_codebook(
        self, *_args: Any, **_kwargs: Any
    ) -> list[RAGCodebookContext]:
        raise self._not_supported("query_codebook")

    async def query_facets(self, *_args: Any, **_kwargs: Any) -> list[RAGFacetContext]:
        raise self._not_supported("query_facets")

    async def upsert_tables(self, *_args: Any, **_kwargs: Any) -> None:
        raise self._not_supported("upsert_tables")

    async def upsert_nuance(self, *_args: Any, **_kwargs: Any) -> None:
        raise self._not_supported("upsert_nuance")

    async def upsert_facets(self, *_args: Any, **_kwargs: Any) -> None:
        raise self._not_supported("upsert_facets")

    async def delete(self, _key: str) -> bool:
        raise self._not_supported("delete")

    async def get(self, _key: str) -> object | None:
        raise self._not_supported("get")

    async def set(self, _key: str, _value: object) -> None:
        raise self._not_supported("set")


def _rows_to_models(resp: Any, model: type) -> list[Any]:
    """Map a Vector Search similarity_search response into RAG model instances."""
    try:
        data = resp.get("result", {}).get("data_array", []) or []
        columns = [c["name"] for c in resp.get("manifest", {}).get("columns", [])]
    except AttributeError:
        return []

    items: list[Any] = []
    for row in data:
        record = dict(zip(columns, row, strict=False))
        record.pop("score", None)
        fields = set(getattr(model, "model_fields", {}).keys())
        filtered = {k: v for k, v in record.items() if k in fields}
        try:
            items.append(model(**filtered))
        except Exception:  # noqa: BLE001 - skip malformed rows
            continue
    return items
