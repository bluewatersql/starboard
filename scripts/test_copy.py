"""
Test script for RAG vector store with embedding provider.

Tests both low-level (embedding-based) and high-level (text-based) query methods.
"""

import asyncio
import os
import sys
from pathlib import Path

from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.rag import (
    LLMClientEmbeddingProvider,
    SQLiteMultiCollectionStore,
)


async def main() -> int:
    """Run all tests."""
    print("\n" + "=" * 80)
    print("RAG Vector Store - Embedding Provider Test Suite")
    print("=" * 80)

    # query = "Show me warehouse costs for the last 30 days"
    query = "What are the top 10 most expensive jobs over the last month?"

    domains = ["finops_billing", "compute_warehouses"]

    db_path = Path("/Users/c.price/Work/github/job-agent/dev_data/starboard_vector.db")
    if not db_path.exists():
        print(f"\n✗ Error: Database not found at {db_path}")
        print("   Run: python scripts/build_rag_vector_store.py")
        return 1

    print(f"\nDatabase: {db_path} ({db_path.stat().st_size / 1024 / 1024:.1f} MB)")

    print("\n" + "=" * 80)
    print("RAG Test")
    print("=" * 80)

    config = EnvConfig.from_env()
    config.validate_config()

    embedding_provider = LLMClientEmbeddingProvider(cfg=config)

    store_provider = SQLiteMultiCollectionStore(
        db_path=str(db_path),
        embedding_provider=embedding_provider,
        embedding_dim=int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
    )
    await store_provider.initialize()

    try:
        rag_results = await store_provider.search_multi_collection(
            query=query,
            # collections=["Tables", "Nuance", "Facets", "Codebook"],
            collections=["Codebook"],
            n_results_per_collection=25,
            domains=domains,
        )

        # for collection, results in rag_results.items():
        #     print(f"{collection}:")
        #     # Convert dataclass instances to dictionaries for JSON serialization
        #     # serializable_results = [asdict(result) for result in results]
        #     # print(json.dumps(serializable_results, indent=2))
        #     [
        #         print(result.model_dump_json(exclude_none=True, indent=2))
        #         for result in results
        #     ]
        #     print()

        print(rag_results.model_dump_json(exclude_none=True, indent=2))
        print()

    finally:
        await store_provider.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
