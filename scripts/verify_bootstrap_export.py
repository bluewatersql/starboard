#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Verify bootstrap export and loading workflow.

This script tests the complete export -> load cycle to ensure
the in-memory vector store can successfully load from exported data.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


async def verify_export_load_cycle():
    """Verify the complete export and load workflow."""
    console.print("[bold cyan]Bootstrap Export/Load Verification[/bold cyan]\n")

    # Check if bootstrap data exists
    bootstrap_dir = Path(
        "packages/starboard-server/starboard/infra/rag/data/bootstrap"
    )

    console.print(f"[yellow]Checking bootstrap directory:[/yellow] {bootstrap_dir}")

    if not bootstrap_dir.exists():
        console.print("[bold red]✗ Bootstrap directory not found[/bold red]")
        return False

    # Check for required files
    required_files = [
        "manifest.json",
        "tables.json",
        "tables_embeddings.npz",
        "nuance.json",
        "nuance_embeddings.npz",
    ]

    missing_files = []
    file_table = Table(title="Bootstrap Files", show_header=True)
    file_table.add_column("File", style="cyan")
    file_table.add_column("Status", style="green")
    file_table.add_column("Size", justify="right")

    for filename in required_files:
        filepath = bootstrap_dir / filename
        if filepath.exists():
            size_kb = filepath.stat().st_size / 1024
            file_table.add_row(filename, "✓ Found", f"{size_kb:.1f} KB")
        else:
            missing_files.append(filename)
            file_table.add_row(filename, "[red]✗ Missing[/red]", "-")

    console.print(file_table)

    if missing_files:
        console.print(
            f"\n[bold yellow]⚠ Missing files:[/bold yellow] {', '.join(missing_files)}"
        )
        console.print(
            "\nRun export script to generate bootstrap data:\n"
            "  python scripts/export_vector_store_snapshot.py"
        )
        return False

    # Load and verify manifest
    console.print("\n[yellow]Loading manifest...[/yellow]")
    import json

    with open(bootstrap_dir / "manifest.json") as f:
        manifest = json.load(f)

    console.print(f"  Export timestamp: {manifest.get('export_timestamp', 'N/A')}")
    console.print(f"  Total records: {manifest.get('total_records', 'N/A')}")
    console.print(f"  Total size: {manifest.get('total_size_kb', 0):.1f} KB")

    # Test loading into in-memory store
    console.print("\n[yellow]Testing in-memory store loading...[/yellow]")

    try:
        from starboard.infra.rag.adapters.storage.bootstrap_loader import (
            BootstrapDataLoader,
        )

        loader = BootstrapDataLoader(data_dir=bootstrap_dir)

        # Load tables
        tables, tables_embeddings = loader.load_tables(with_embeddings=True)
        console.print(f"  ✓ Loaded {len(tables)} tables")
        if tables_embeddings:
            console.print(f"    • With {len(tables_embeddings)} precomputed embeddings")

        # Load nuance
        nuance, nuance_embeddings = loader.load_nuance(with_embeddings=True)
        console.print(f"  ✓ Loaded {len(nuance)} nuance entries")
        if nuance_embeddings:
            console.print(f"    • With {len(nuance_embeddings)} precomputed embeddings")

        # Load codebook
        codebook, codebook_embeddings = loader.load_codebook(with_embeddings=True)
        console.print(f"  ✓ Loaded {len(codebook)} codebook entries")
        if codebook_embeddings:
            console.print(
                f"    • With {len(codebook_embeddings)} precomputed embeddings"
            )

        # Summary
        console.print("\n[bold green]✓ Verification Complete[/bold green]")
        console.print(
            f"\nBootstrap data is ready for in-memory vector store "
            f"({len(tables) + len(nuance) + len(codebook)} total records)"
        )

        return True

    except Exception as e:
        console.print(f"\n[bold red]✗ Loading failed:[/bold red] {e}")
        import traceback

        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return False


async def main():
    """Main verification function."""
    success = await verify_export_load_cycle()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
