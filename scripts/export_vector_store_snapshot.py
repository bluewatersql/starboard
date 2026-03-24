#!/usr/bin/env python3
"""Export production vector store for in-memory bootstrap.

This script exports a curated subset of the production vector store
(starboard_vector.db) to JSON + compressed NumPy format for bundling
with the starboard-server package.

The exported data is used to bootstrap the in-memory vector store in
CLI and development environments where SQLite vector extensions are unavailable.

Usage:
    python scripts/export_vector_store_snapshot.py

Output:
    packages/starboard-server/starboard_server/infra/rag/data/bootstrap/
    ├── tables.json              # Table metadata (readable)
    ├── tables_embeddings.npz    # Precomputed embeddings (binary)
    ├── nuance.json              # Best practices (readable)
    ├── nuance_embeddings.npz    # Precomputed embeddings (binary)
    ├── codebook.json            # Field definitions (readable)
    ├── codebook_embeddings.npz  # Precomputed embeddings (binary)
    └── manifest.json            # Export metadata
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

logger = structlog.get_logger(__name__)
console = Console()


class VectorStoreExporter:
    """Export vector store contents to bootstrap format."""

    def __init__(
        self,
        db_path: str | Path,
        output_dir: str | Path,
    ):
        """Initialize exporter.

        Args:
            db_path: Path to starboard_vector.db
            output_dir: Directory to save exports
        """
        self.db_path = Path(db_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if not self.db_path.exists():
            raise FileNotFoundError(f"Vector store not found: {self.db_path}")

        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

    def get_table_stats(self) -> dict[str, int]:
        """Get row counts for each collection."""
        collections = ["tables", "nuance", "codebook", "facets"]
        stats = {}

        for collection in collections:
            cursor = self.conn.execute(
                f"SELECT COUNT(*) as count FROM vectors_{collection}"
            )
            row = cursor.fetchone()
            stats[collection] = row["count"] if row else 0

        return stats

    def export_collection(
        self,
        collection: str,
        strategy: str = "essential",
        max_items: int = 20,
        progress: Progress | None = None,
        task_id: Any = None,
    ) -> dict[str, Any]:
        """Export a single collection.

        Args:
            collection: Collection name (tables, nuance, codebook, facets)
            strategy: Export strategy (essential, random, top_used)
            max_items: Maximum items to export
            progress: Optional progress tracker
            task_id: Optional progress task ID

        Returns:
            Export statistics
        """
        # Build query based on strategy
        if collection == "tables" and strategy == "essential":
            # Prioritize essential system tables but include others if needed
            query = f"""
                SELECT *
                FROM vectors_{collection}
                ORDER BY
                    CASE
                        WHEN json_extract(metadata, '$.table_name') LIKE 'system.billing%' THEN 1
                        WHEN json_extract(metadata, '$.table_name') LIKE 'system.compute%' THEN 2
                        WHEN json_extract(metadata, '$.table_name') LIKE 'system.query%' THEN 3
                        WHEN json_extract(metadata, '$.doc_type') = 'table_summary' THEN 4
                        ELSE 5
                    END,
                    json_extract(metadata, '$.table_name')
                LIMIT ?
            """
        elif collection == "nuance" and strategy == "essential":
            # Prioritize high-value domains but include others if needed
            query = f"""
                SELECT *
                FROM vectors_{collection}
                ORDER BY
                    CASE
                        WHEN json_extract(metadata, '$.rag_resource_domain') = 'finops_billing' THEN 1
                        WHEN json_extract(metadata, '$.rag_resource_domain') = 'compute_warehouses' THEN 2
                        WHEN json_extract(metadata, '$.rag_resource_domain') = 'compute_jobs' THEN 3
                        WHEN json_extract(metadata, '$.doc_type') = 'performance' THEN 4
                        WHEN json_extract(metadata, '$.doc_type') = 'join_pattern' THEN 5
                        WHEN json_extract(metadata, '$.doc_type') = 'aggregation' THEN 6
                        ELSE 7
                    END,
                    id
                LIMIT ?
            """
        elif collection == "codebook" and strategy == "essential":
            # Prioritize common domains but include others if needed
            query = f"""
                SELECT *
                FROM vectors_{collection}
                ORDER BY
                    CASE
                        WHEN json_extract(metadata, '$.rag_resource_domain') = 'finops_billing' THEN 1
                        WHEN json_extract(metadata, '$.rag_resource_domain') = 'compute_warehouses' THEN 2
                        ELSE 3
                    END,
                    id
                LIMIT ?
            """
        else:
            # Random sample
            query = f"""
                SELECT *
                FROM vectors_{collection}
                ORDER BY RANDOM()
                LIMIT ?
            """

        cursor = self.conn.execute(query, (max_items,))

        # Process records
        records = []
        embeddings = {}

        for row in cursor.fetchall():
            embedding_id = f"{collection}_{row['id']}"

            # Extract metadata
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}

            # Build record
            record = {
                "id": row["id"],
                "content": row["content"],
                "metadata": metadata,
                "embedding_ref": embedding_id,
            }
            records.append(record)

            # Store embedding separately (unpack from binary format)
            if row["embedding"]:
                # Embeddings are stored as binary using struct.pack(f"{len}f", *floats)
                # Unpack to list of floats
                embedding_bytes = row["embedding"]
                num_floats = len(embedding_bytes) // 4  # 4 bytes per float
                embedding_floats = struct.unpack(f"{num_floats}f", embedding_bytes)
                embeddings[embedding_id] = np.array(embedding_floats, dtype=np.float32)

            if progress and task_id:
                progress.update(task_id, advance=1)

        # Save JSON metadata
        json_file = self.output_dir / f"{collection}.json"
        with open(json_file, "w") as f:
            json.dump(records, f, indent=2)

        # Save embeddings as compressed NumPy
        npz_file = self.output_dir / f"{collection}_embeddings.npz"
        np.savez_compressed(npz_file, **embeddings)

        # Get relative paths if possible, otherwise use absolute
        try:
            json_rel = json_file.relative_to(Path.cwd())
            npz_rel = npz_file.relative_to(Path.cwd())
        except ValueError:
            json_rel = json_file
            npz_rel = npz_file

        stats = {
            "collection": collection,
            "records_exported": len(records),
            "json_size_kb": json_file.stat().st_size / 1024,
            "embeddings_size_kb": npz_file.stat().st_size / 1024,
            "json_file": str(json_rel),
            "embeddings_file": str(npz_rel),
        }

        return stats

    def export_all(
        self,
        strategy: str = "essential",
        config: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Export all collections.

        Args:
            strategy: Export strategy (essential, random, top_used)
            config: Per-collection max items (defaults to essential config)

        Returns:
            Export manifest with statistics
        """
        if config is None:
            # Default: curated essential subset
            config = {
                "tables": 15,  # Core system tables
                "nuance": 30,  # Key best practices
                "codebook": 10,  # Important field definitions
                "facets": 0,  # Skip facets (can be large, less critical)
            }

        console.print("\n[bold blue]Vector Store Export[/bold blue]")
        console.print(f"Source: [cyan]{self.db_path}[/cyan]")
        console.print(f"Output: [cyan]{self.output_dir}[/cyan]")
        console.print(f"Strategy: [cyan]{strategy}[/cyan]\n")

        # Get current stats
        db_stats = self.get_table_stats()
        console.print("[yellow]Source Database Stats:[/yellow]")
        for collection, count in db_stats.items():
            console.print(f"  • {collection}: {count:,} records")
        console.print()

        # Export each collection
        export_stats = []
        _total_items = sum(v for v in config.values() if v > 0)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            for collection, max_items in config.items():
                if max_items == 0:
                    continue

                task = progress.add_task(
                    f"Exporting {collection}...", total=max_items
                )

                stats = self.export_collection(
                    collection=collection,
                    strategy=strategy,
                    max_items=max_items,
                    progress=progress,
                    task_id=task,
                )
                export_stats.append(stats)

                progress.update(task, completed=True)

        # Create manifest
        manifest = {
            "export_timestamp": datetime.now(UTC).isoformat(),
            "source_database": str(self.db_path),
            "strategy": strategy,
            "source_stats": db_stats,
            "collections": export_stats,
            "total_records": sum(s["records_exported"] for s in export_stats),
            "total_size_kb": sum(
                s["json_size_kb"] + s["embeddings_size_kb"] for s in export_stats
            ),
        }

        manifest_file = self.output_dir / "manifest.json"
        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)

        # Print summary
        console.print("\n[bold green]✓ Export Complete[/bold green]\n")
        console.print("[yellow]Export Summary:[/yellow]")
        for stats in export_stats:
            console.print(
                f"  • {stats['collection']}: {stats['records_exported']} records "
                f"({stats['json_size_kb'] + stats['embeddings_size_kb']:.1f} KB)"
            )

        console.print(
            f"\n[bold]Total:[/bold] {manifest['total_records']} records, "
            f"{manifest['total_size_kb']:.1f} KB"
        )

        # Get relative path if possible
        try:
            manifest_rel = manifest_file.relative_to(Path.cwd())
        except ValueError:
            manifest_rel = manifest_file
        console.print(f"[bold]Manifest:[/bold] {manifest_rel}")

        return manifest

    def close(self):
        """Close database connection."""
        self.conn.close()


async def main():
    """Main export function."""
    console.print("[bold cyan]Starboard Vector Store Exporter[/bold cyan]\n")

    # Configuration - check multiple possible locations
    possible_paths = [
        Path("starboard_vector.db"),  # Project root
        Path("dev_data/starboard_vector.db"),  # Dev data directory
    ]

    db_path = None
    for path in possible_paths:
        if path.exists():
            db_path = path
            break

    output_dir = Path(
        "packages/starboard-server/starboard_server/infra/rag/data/bootstrap"
    )

    # Check if database exists
    if db_path is None:
        console.print(
            "[bold red]Error:[/bold red] Vector store not found in any location:"
        )
        for path in possible_paths:
            console.print(f"  • {path}")
        console.print(
            "\nPlease run the RAG build script first:\n"
            "  python scripts/build_rag_vector_store.py"
        )
        return 1

    # Export
    exporter = VectorStoreExporter(db_path=db_path, output_dir=output_dir)

    try:
        _manifest = exporter.export_all(
            strategy="essential",
            config={
                "tables": 1000,  # Essential system tables (prioritizes billing, compute, query)
                "nuance": 1000,  # Key SQL patterns and best practices
                "codebook": 1000,  # Important field definitions
                "facets": 1000,  # Skip (not critical for basic queries, saves space)
            },
        )

        console.print(
            "\n[bold green]✓ Bootstrap data ready for in-memory vector store[/bold green]"
        )

        return 0

    except Exception as e:
        console.print(f"\n[bold red]Error during export:[/bold red] {e}")
        logger.exception("export_failed")
        return 1

    finally:
        exporter.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
