"""
Test script for RAG vector store with embedding provider.

Tests both low-level (embedding-based) and high-level (text-based) query methods.
"""

import asyncio
import os
import sys
from pathlib import Path

from starboard_server.infra.rag import (
    LLMClientEmbeddingProvider,
    SQLiteMultiCollectionStore,
)


async def test_low_level_methods(store: SQLiteMultiCollectionStore) -> None:
    """Test low-level query methods (require pre-computed embeddings)."""
    print("\n" + "=" * 80)
    print("TEST: Low-Level Methods (query_* with embeddings)")
    print("=" * 80)

    # Generate embedding using mock provider
    embedding_provider = LLMClientEmbeddingProvider()
    query_embedding = await embedding_provider.embed("jobs billing data")

    # Test query_tables
    print("\n1. Testing query_tables()...")
    results = await store.query_tables(
        query_embedding=query_embedding,
        n_results=5,
    )
    print(f"   Found {len(results)} results")
    for i, result in enumerate(results[:5], 1):
        content_preview = result.content[:80].replace("\n", " ")
        print(
            f"   {i}. {result.id[:50]}: {content_preview}... (score: {result.score:.3f})"
        )

    # Test query_facets
    print("\n2. Testing query_facets()...")
    facet_embedding = await embedding_provider.embed("average warehouse size")
    results = await store.query_facets(
        query_embedding=facet_embedding,
        n_results=5,
    )
    print(f"   Found {len(results)} results")
    for i, result in enumerate(results[:5], 1):
        content_preview = result.content[:80].replace("\n", " ")
        print(
            f"   {i}. {result.id[:50]}: {content_preview}... (score: {result.score:.3f})"
        )


async def test_high_level_methods(store: SQLiteMultiCollectionStore) -> None:
    """Test high-level search methods (accept text queries)."""
    print("\n" + "=" * 80)
    print("TEST: High-Level Methods (search_* with text)")
    print("=" * 80)

    # Test search_tables
    print("\n1. Testing search_tables()...")
    try:
        results = await store.search_tables(
            query="warehouse usage and costs",
            n_results=5,
        )
        print(f"   ✓ Found {len(results)} results")
        for i, result in enumerate(results[:5], 1):
            content_preview = result.content[:80].replace("\n", " ")
            print(
                f"   {i}. {result.id[:50]}: {content_preview}... (score: {result.score:.3f})"
            )
    except ValueError as e:
        print(f"   ✗ Error: {e}")

    # Test search_facets
    print("\n2. Testing search_facets()...")
    try:
        results = await store.search_facets(
            query="warehouse size options",
            n_results=5,
        )
        print(f"   ✓ Found {len(results)} results")
        for i, result in enumerate(results[:5], 1):
            content_preview = result.content[:80].replace("\n", " ")
            print(
                f"   {i}. {result.id[:50]}: {content_preview}... (score: {result.score:.3f})"
            )
    except ValueError as e:
        print(f"   ✗ Error: {e}")

    # Test query_multi_collection
    print("\n3. Testing query_multi_collection()...")
    try:
        results = await store.search_multi_collection(
            query="warehouse costs and performance",
            collections=["Tables", "Nuance", "Facets"],
            n_results_per_collection=3,
        )
        print(f"   ✓ Queried {len(results)} collections")
        for collection, collection_results in results.items():
            print(f"   - {collection}: {len(collection_results)} results")
    except ValueError as e:
        print(f"   ✗ Error: {e}")

    try:
        print("\n4. Testing domain filtering - unrestricted...")
        results_all = await store.search_tables(
            query="What did my warehouse usage cost last month?",
            domains=None,
            n_results=20,
            deduplicate=False,
        )

        print(f"   ✓ Found {len(results_all)} results")
        for i, result in enumerate(results_all[:10], 1):
            content_preview = result.content[:80].replace("\n", " ")
            print(
                f"   {i}. {result.id[:50]}: {content_preview}... (score: {result.score:.3f})"
            )

    except ValueError as e:
        print(f"   ✗ Error: {e}")

    try:
        print(
            "\n4. Testing domain filtering - restricted (finops_billing and compute_warehouses)..."
        )
        results_filtered = await store.search_tables(
            query="What did my warehouse usage cost last month?",
            domains=["finops_billing", "compute_warehouses"],
            n_results=20,
            deduplicate=False,
        )

        print(f"   ✓ Found {len(results_filtered)} results")
        for i, result in enumerate(results_filtered[:10], 1):
            content_preview = result.content[:80].replace("\n", " ")
            print(
                f"   {i}. {result.id[:50]}: {content_preview}... (score: {result.score:.3f})"
            )

    except ValueError as e:
        print(f"   ✗ Error: {e}")


async def main() -> int:
    """Run all tests."""
    print("\n" + "=" * 80)
    print("RAG Vector Store - Embedding Provider Test Suite")
    print("=" * 80)

    db_path = Path("/Users/c.price/Work/github/job-agent/dev_data/starboard_vector.db")
    if not db_path.exists():
        print(f"\n✗ Error: Database not found at {db_path}")
        print("   Run: python scripts/build_rag_vector_store.py")
        return 1

    print(f"\nDatabase: {db_path} ({db_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # Test 1: Store without embedding provider (low-level methods only)
    print("\n" + "=" * 80)
    print("TEST SUITE 1: Store WITHOUT Embedding Provider")
    print("=" * 80)

    store_no_provider = SQLiteMultiCollectionStore(
        db_path=str(db_path),
        embedding_dim=int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
    )
    await store_no_provider.initialize()
    await test_low_level_methods(store_no_provider)
    await store_no_provider.close()

    embedding_provider = LLMClientEmbeddingProvider()
    store_provider = SQLiteMultiCollectionStore(
        db_path=str(db_path),
        embedding_provider=embedding_provider,
        embedding_dim=int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
    )
    await store_provider.initialize()
    await test_high_level_methods(store_provider)
    await store_provider.close()

    print("\n" + "=" * 80)
    print("✓ All tests complete!")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
