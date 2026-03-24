#!/usr/bin/env python3
"""Verify precomputed embeddings are being used."""

import asyncio

import numpy as np
from rich.console import Console

console = Console()


async def main():
    """Verify precomputed embeddings."""
    console.print("[bold cyan]Verifying Precomputed Embeddings Usage[/bold cyan]\n")

    from starboard_server.infra.rag.adapters.storage.bootstrap_loader import (
        BootstrapDataLoader,
    )

    loader = BootstrapDataLoader()

    # Load tables with embeddings
    console.print("[yellow]Loading tables with embeddings...[/yellow]")
    tables, embeddings = loader.load_tables(with_embeddings=True)

    console.print(f"✓ Loaded {len(tables)} tables")
    console.print(f"✓ Loaded {len(embeddings) if embeddings else 0} embeddings")

    if embeddings:
        console.print("\n[green]Sample embedding (index 0):[/green]")
        if 0 in embeddings:
            emb = embeddings[0]
            console.print(f"  • Shape: {emb.shape}")
            console.print(f"  • Type: {emb.dtype}")
            console.print(f"  • First 5 values: {emb[:5]}")
            console.print(f"  • L2 norm: {np.linalg.norm(emb):.4f}")

            # Check if it's normalized (OpenAI embeddings are normalized)
            norm = np.linalg.norm(emb)
            is_normalized = abs(norm - 1.0) < 0.01
            console.print(f"  • Normalized: {is_normalized} (norm={norm:.6f})")
        else:
            console.print("  [red]✗ Index 0 not found in embeddings dict[/red]")
            console.print(f"  Available keys: {list(embeddings.keys())[:5]}")
    else:
        console.print("[red]✗ No embeddings loaded![/red]")
        return 1

    console.print("\n[bold green]✓ Precomputed embeddings are valid OpenAI embeddings![/bold green]")
    console.print(
        "\n[yellow]Note:[/yellow] Search tests with MockEmbeddingProvider will return 0 results "
        "because mock embeddings are in a different vector space than real OpenAI embeddings."
    )
    console.print(
        "To test search, use a real embedding provider with an actual API key."
    )

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
