#!/usr/bin/env python3
"""Test in-memory vector store with full bootstrap data."""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.table import Table

console = Console()


async def test_inmemory_store():
    """Test in-memory store initialization and search."""
    console.print("[bold cyan]Testing In-Memory Vector Store Bootstrap[/bold cyan]\n")

    # Import after path setup
    from starboard_server.infra.rag.adapters.storage.bootstrap_loader import (
        load_bootstrap_data,
    )
    from starboard_server.infra.rag.adapters.storage.inmemory_vector_store import (
        InMemoryMultiCollectionStore,
    )

    # Mock embedding provider for testing
    class MockEmbeddingProvider:
        async def embed(self, text: str) -> list[float]:
            # Return a simple deterministic embedding for testing
            import hashlib

            # Use hash to generate deterministic floats
            hash_val = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
            return [float((hash_val >> i) & 0xFF) / 255.0 for i in range(1024)]

    # Create in-memory store
    console.print("[yellow]1. Initializing in-memory vector store...[/yellow]")
    embedding_provider = MockEmbeddingProvider()
    store = InMemoryMultiCollectionStore(
        embedding_provider=embedding_provider,
        embedding_dim=1024,
        max_vectors=50000,
    )
    await store.initialize()
    console.print("  ✓ Store initialized\n")

    # Load bootstrap data
    console.print("[yellow]2. Loading bootstrap data...[/yellow]")
    counts = await load_bootstrap_data(
        store=store,
        use_exported=True,
        use_hardcoded=True,
    )

    # Display loaded counts
    load_table = Table(title="Bootstrap Data Loaded", show_header=True)
    load_table.add_column("Collection", style="cyan")
    load_table.add_column("Records", justify="right", style="green")

    for collection, count in counts.items():
        load_table.add_row(collection, str(count))

    console.print(load_table)
    console.print()

    total_loaded = sum(counts.values())
    if total_loaded == 0:
        console.print("[bold red]✗ No data loaded![/bold red]")
        return False

    console.print(f"[green]✓ Total records loaded: {total_loaded}[/green]\n")

    # Get store stats
    console.print("[yellow]3. Checking store statistics...[/yellow]")
    stats = store.get_stats()

    stats_table = Table(title="Vector Store Stats", show_header=True)
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", justify="right", style="yellow")

    stats_table.add_row("Total Vectors", str(stats["total_vectors"]))
    stats_table.add_row("Tables Collection", str(stats["collections"]["tables"]))
    stats_table.add_row("Nuance Collection", str(stats["collections"]["nuance"]))
    stats_table.add_row("Codebook Collection", str(stats["collections"]["codebook"]))
    stats_table.add_row("Facets Collection", str(stats["collections"]["facets"]))

    # Calculate approximate memory usage
    approx_mem_mb = stats["total_vectors"] * 1024 * 4 / (1024 * 1024)  # 1024 floats * 4 bytes
    stats_table.add_row("Approx Memory (MB)", f"{approx_mem_mb:.2f}")

    console.print(stats_table)
    console.print()

    # Test search functionality
    console.print("[yellow]4. Testing search functionality...[/yellow]")

    # Search tables
    try:
        table_context = await store.search_multi_collection(
            query="billing costs usage",
            collections=["tables"],
            n_results_per_collection=5,
        )
        console.print(f"  ✓ Tables search returned {len(table_context.tables)} results")

        if table_context.tables:
            console.print(f"    • Top result: {table_context.tables[0].table_name}")
            console.print(f"    • Score: {table_context.tables[0].relevance_score:.4f}")
    except Exception as e:
        console.print(f"  [red]✗ Tables search failed: {e}[/red]")
        return False

    # Search nuance
    try:
        nuance_context = await store.search_multi_collection(
            query="optimize query performance",
            collections=["nuance"],
            n_results_per_collection=3,
        )
        console.print(f"  ✓ Nuance search returned {len(nuance_context.nuance)} results")

        if nuance_context.nuance:
            console.print(f"    • Top result: {nuance_context.nuance[0].topic}")
            console.print(f"    • Score: {nuance_context.nuance[0].relevance_score:.4f}")
    except Exception as e:
        console.print(f"  [red]✗ Nuance search failed: {e}[/red]")
        return False

    # Search codebook
    try:
        codebook_context = await store.search_multi_collection(
            query="sku pricing",
            collections=["codebook"],
            n_results_per_collection=3,
        )
        console.print(f"  ✓ Codebook search returned {len(codebook_context.codebook)} results")

        if codebook_context.codebook:
            console.print(f"    • Top result: {codebook_context.codebook[0].code}")
            console.print(f"    • Score: {codebook_context.codebook[0].relevance_score:.4f}")
    except Exception as e:
        console.print(f"  [red]✗ Codebook search failed: {e}[/red]")
        return False

    console.print()

    # Multi-collection search
    console.print("[yellow]5. Testing multi-collection search...[/yellow]")
    try:
        multi_context = await store.search_multi_collection(
            query="warehouse compute costs",
            collections=["tables", "nuance", "codebook"],
            n_results_per_collection=10,
        )

        total_results = (
            len(multi_context.tables) +
            len(multi_context.nuance) +
            len(multi_context.codebook)
        )
        console.print(f"  ✓ Multi-collection search returned {total_results} total results")

        # Show distribution
        console.print("    • Results by collection:")
        console.print(f"      - tables: {len(multi_context.tables)}")
        console.print(f"      - nuance: {len(multi_context.nuance)}")
        console.print(f"      - codebook: {len(multi_context.codebook)}")

    except Exception as e:
        console.print(f"  [red]✗ Multi-collection search failed: {e}[/red]")
        return False

    console.print()
    console.print("[bold green]✓ All tests passed![/bold green]")
    console.print(
        f"\n[bold]Summary:[/bold] In-memory vector store successfully loaded "
        f"{total_loaded} records and performed {4} successful searches."
    )

    return True


async def main():
    """Main test function."""
    try:
        success = await test_inmemory_store()
        return 0 if success else 1
    except Exception as e:
        console.print(f"\n[bold red]✗ Test failed with error:[/bold red] {e}")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
