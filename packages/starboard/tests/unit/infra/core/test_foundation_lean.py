# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the lean foundation init (Phase 2 C4, D-2.9).

Verifies that a default install (``vector_backend="none"``,
``enable_reflexion=False``) initialises foundation components with:
- NO vector store, NO reflexion store, NO embedding provider
- a TTL-only exact-key semantic cache (no sqlite-vec import)

and that the opt-in paths (reflexion / a real vector backend) stay reachable
and gated behind their extras.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starboard.infra.cache import SemanticCache, TTLSemanticCache
from starboard.infra.core.config import EnvConfig
from starboard.infra.core.container import Container


def _config(**overrides) -> EnvConfig:
    base = {
        "_env_file": None,
        "environment": "dev",
        "offline_mode": True,
        "mock_llm": True,
    }
    base.update(overrides)
    return EnvConfig(**base)


class TestLeanDefaultFoundation:
    @pytest.mark.asyncio
    async def test_default_builds_ttl_cache_only(self) -> None:
        cfg = _config(vector_backend="none", enable_reflexion=False)
        container = Container(cfg)
        await container._initialize_foundation_components()

        # TTL-only semantic cache, nothing vector-backed.
        assert isinstance(container.semantic_cache, TTLSemanticCache)
        assert container.vector_store is None
        assert container.reflexion_store is None
        assert container.embedding_provider is None

    @pytest.mark.asyncio
    async def test_semantic_cache_disabled_builds_nothing(self) -> None:
        cfg = _config(
            vector_backend="none",
            enable_reflexion=False,
            enable_semantic_cache=False,
        )
        container = Container(cfg)
        await container._initialize_foundation_components()
        assert container.semantic_cache is None
        assert container.vector_store is None
        assert container.reflexion_store is None

    def test_default_path_does_not_import_optional_store_drivers(self) -> None:
        # Run in a fresh subprocess so the sys.modules assertion is definitive.
        code = textwrap.dedent(
            """
            import asyncio, sys
            from starboard.infra.core.config import EnvConfig
            from starboard.infra.core.container import Container

            cfg = EnvConfig(
                _env_file=None,
                environment="dev",
                offline_mode=True,
                mock_llm=True,
                vector_backend="none",
                enable_reflexion=False,
            )
            container = Container(cfg)
            asyncio.run(container._initialize_foundation_components())
            optional_drivers = ("redis", "asyncpg", "pgvector", "aiosqlite", "sqlite_vec")
            imported = [name for name in optional_drivers if name in sys.modules]
            assert not imported, f"optional store drivers imported on default path: {imported}"
            print("OK")
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout


class TestSemanticCacheBackendDecision:
    def test_none_backend_is_not_vector(self) -> None:
        assert Container(_config(vector_backend="none"))._semantic_cache_uses_vector() is False

    @pytest.mark.parametrize("backend", ["inmemory", "sqlite", "vectorsearch"])
    def test_real_backend_uses_vector(self, backend: str) -> None:
        assert Container(_config(vector_backend=backend))._semantic_cache_uses_vector() is True

    @pytest.mark.asyncio
    async def test_vectorsearch_backend_keeps_ttl_cache_without_sqlite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Managed RAG stores cannot back the low-level semantic-cache protocol."""
        import starboard.infra.rag as rag
        from starboard.infra.rag.services import vector_store_factory

        managed_store = object()

        async def create_managed_store(**_kwargs):
            return managed_store

        def fail_if_sqlite_is_built(*_args, **_kwargs):
            pytest.fail(
                "vectorsearch semantic cache must not instantiate SQLiteVectorStore"
            )

        monkeypatch.setattr(
            vector_store_factory,
            "create_vector_store",
            create_managed_store,
        )
        monkeypatch.setattr(rag, "SQLiteVectorStore", fail_if_sqlite_is_built)

        container = Container(
            _config(vector_backend="vectorsearch", llm_api_key="test-key")
        )
        await container._initialize_foundation_components()

        assert container.vector_store is managed_store
        assert isinstance(container.semantic_cache, TTLSemanticCache)

    @pytest.mark.asyncio
    async def test_compatible_vector_store_is_reused_for_similarity_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A selected store with the low-level protocol backs the cache directly."""
        from starboard.infra.rag.services import vector_store_factory

        compatible_store = SimpleNamespace(
            search=AsyncMock(),
            upsert=AsyncMock(),
            delete=AsyncMock(),
            count=AsyncMock(),
        )

        async def create_compatible_store(**_kwargs):
            return compatible_store

        monkeypatch.setattr(
            vector_store_factory,
            "create_vector_store",
            create_compatible_store,
        )

        container = Container(
            _config(vector_backend="vectorsearch", llm_api_key="test-key")
        )
        await container._initialize_foundation_components()

        assert isinstance(container.semantic_cache, SemanticCache)
        assert container.semantic_cache.vector_store is compatible_store


class TestReflexionGatedBehindExtra:
    @pytest.mark.asyncio
    async def test_reflexion_without_driver_raises_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate a no-extras install: the vector-store driver is unimportable.
        monkeypatch.setitem(sys.modules, "sqlite_vec", None)
        cfg = _config(vector_backend="none", enable_reflexion=True)
        container = Container(cfg)
        with pytest.raises(RuntimeError) as exc:
            await container._initialize_foundation_components()
        msg = str(exc.value)
        assert "pip install" in msg
        assert "starboard[" in msg
        assert "reflexion" in msg.lower()


class TestRecallDegradesToRecency:
    @pytest.mark.asyncio
    async def test_default_memory_store_recall_is_recency(self) -> None:
        # The default (in-memory) memory store has no vector backend, so
        # recall_episodes must degrade to recency ordering (get_recent_episodes).
        from datetime import UTC, datetime, timedelta

        from starboard.adapters.state.inmemory.memory_store import InMemoryMemoryStore
        from starboard_core.models.memory import Episode

        store = InMemoryMemoryStore()
        base = datetime.now(UTC)
        older = Episode(
            id="e1",
            user_id="u1",
            conversation_id=None,
            summary="older",
            key_points=[],
            embedding=None,
            created_at=base - timedelta(hours=1),
        )
        newer = Episode(
            id="e2",
            user_id="u1",
            conversation_id=None,
            summary="newer",
            key_points=[],
            embedding=None,
            created_at=base,
        )
        await store.store_episode(older)
        await store.store_episode(newer)

        recalled = await store.recall_episodes("u1", query="anything", limit=10)
        recent = await store.get_recent_episodes("u1", limit=10)
        # recall == recency ordering (newest first), no semantic reranking.
        assert [e.id for e in recalled] == [e.id for e in recent]
        assert recalled[0].id == "e2"
