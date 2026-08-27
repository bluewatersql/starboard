"""Tests for the opt-in managed Databricks Vector Search adapter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starboard.infra.rag.adapters.storage.databricks_vector_store import (
    DatabricksVectorSearchStore,
)


class _FakeIndex:
    def __init__(self) -> None:
        self.search_kwargs: dict[str, Any] | None = None

    def similarity_search(self, **kwargs: Any) -> dict[str, Any]:
        self.search_kwargs = kwargs
        return {"manifest": {"columns": []}, "result": {"data_array": []}}


class _FakeClient:
    def __init__(self, index: _FakeIndex) -> None:
        self.index = index
        self.get_index_calls = 0

    def get_index(self, **_kwargs: Any) -> _FakeIndex:
        self.get_index_calls += 1
        return self.index


@pytest.mark.asyncio
async def test_search_uses_explicit_configured_columns() -> None:
    """Managed search must pass configured names, never the invalid wildcard."""
    columns = ["id", "content", "domain"]
    config = SimpleNamespace(
        embedding_dimension=3,
        vectorsearch_columns=columns,
    )
    index = _FakeIndex()
    store = DatabricksVectorSearchStore(config=config)  # type: ignore[arg-type]
    store._client = _FakeClient(index)

    await store.search_multi_collection("query", collections=["Tables"])

    assert index.search_kwargs is not None
    assert index.search_kwargs["columns"] == columns
    assert index.search_kwargs["columns"] != ["*"]


@pytest.mark.asyncio
async def test_search_without_columns_is_quarantined_before_client_call() -> None:
    """Unknown live index schemas must fail clearly instead of guessing columns."""
    config = SimpleNamespace(embedding_dimension=3)
    index = _FakeIndex()
    client = _FakeClient(index)
    store = DatabricksVectorSearchStore(config=config)  # type: ignore[arg-type]
    store._client = client

    with pytest.raises(ValueError, match="vectorsearch_columns"):
        await store.search_multi_collection("query", collections=["Tables"])

    assert client.get_index_calls == 0
