#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Build RAG vector store for Analytics Agent V2.

Orchestrates the complete pipeline:
1. Extract metadata from Databricks system tables
2. Enrich with LLM-generated context
3. Chunk tables into semantic pieces
4. Duplicate across domains
5. Ingest into multi-collection vector store
6. Load nuance and facets from JSON files

Features:
- Checkpoint-based resumability
- Parallel processing where possible
- Progress tracking
- Error handling and retry logic
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from databricks import sql as databricks_sql
from dotenv import load_dotenv
from pydantic import TypeAdapter
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from starboard_core.foundations.models import VectorRecord
from starboard_core.rag.models import TableMetadata
from starboard_server.adapters.llm import create_llm_client
from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.rag import (
    ChunkingService,
    CollectionType,
    DomainService,
    EnrichmentService,
    MetadataExtractor,
    QueryAnalyzer,
    SQLiteMultiCollectionStore,
)
from starboard_server.infra.rag.adapters.embedding import LLMClientEmbeddingProvider
from starboard_server.infra.rag.domain.protocols import EmbeddingProvider
from starboard_server.infra.rag.services.checkpoint_service import (
    read_checkpoint,
    write_checkpoint,
)

logger = structlog.get_logger(__name__)
console = Console()

# Configuration
CHECKPOINT_DIR = Path("checkpoints/rag")
CHECKPOINT_MAX_AGE_MINUTES = 24 * 60  # 24 hours in minutes

# Databricks system schemas to process
SYSTEM_SCHEMAS = [
    "system.access",
    "system.billing",
    "system.compute",
    # "system.information_schema",
    "system.lakeflow",
    "system.mlflow",
    "system.query",
    "system.serving",
    "system.storage",
]

EXCLUDED_TABLES = ["system.billing.cloud_infra_cost"]

# Nuance and facet data files
NUANCE_FILE = Path("packages/starboard-core/starboard_core/rag/data/nuance_pack.json")
CODEBOOK_FILE = Path(
    "packages/starboard-core/starboard_core/rag/data/codebook_pack.json"
)


class DatabricksClientWrapper:
    """Wrapper for Databricks SQL connection."""

    def __init__(self, connection: databricks_sql.Connection):
        self.connection = connection

    def execute_query(self, query: str) -> list[dict[str, Any]]:
        """Execute query and return results as list of dicts."""
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]


async def extract_metadata_step(
    databricks_client: DatabricksClientWrapper,
    query_analyzer: QueryAnalyzer,
    progress: Progress,
    task: TaskID,
) -> list[TableMetadata]:
    """
    Step 1: Extract metadata from Databricks.

    Discovery by example runs automatically inside MetadataExtractor on first call.

    Uses checkpoint if available and fresh.
    """
    # Check for fresh checkpoint
    checkpoint_data = await read_checkpoint("01_extracted_metadata")
    if checkpoint_data is not None:
        tables = TypeAdapter(list[TableMetadata]).validate_python(checkpoint_data)
        console.print(
            f"[green]✓[/green] Using cached extracted metadata ({len(tables)} tables)"
        )
        console.print(
            "[dim]Run 'python scripts/clean_checkpoints.py extracted' to force re-extraction[/dim]"
        )
        progress.update(task, completed=len(tables), total=len(tables))
        return tables

    console.print("[yellow]→[/yellow] Extracting metadata from Databricks...")
    console.print("[dim]Discovery by example will run automatically...[/dim]")

    # Create MetadataExtractor (discovery runs automatically on first extract_tables call)
    extractor = MetadataExtractor(
        databricks_client,
        query_analyzer,
        max_workers=5,
    )

    all_tables: list[TableMetadata] = []
    for schema in SYSTEM_SCHEMAS:
        catalog, schema_name = schema.split(".")
        tables = await extractor.extract_tables(
            schemas=[schema_name], catalog=catalog, excluded_tables=EXCLUDED_TABLES
        )
        all_tables.extend(tables)
        progress.update(task, advance=len(tables))

    # Save checkpoint
    checkpoint_data = [table.model_dump() for table in all_tables]
    await write_checkpoint("01_extracted_metadata", checkpoint_data)
    console.print(
        f"[green]✓[/green] Extracted {len(all_tables)} tables with enriched column metadata"
    )

    return all_tables


async def enrich_metadata_step(
    tables: list[TableMetadata],
    llm_client: BaseLLMClient,
    progress: Progress,
    task: TaskID,
) -> list[TableMetadata]:
    """
    Step 2: Enrich metadata with LLM.

    Uses checkpoint if available and fresh.
    """
    # Check for fresh checkpoint
    checkpoint_data = await read_checkpoint("02_enriched_metadata")
    if checkpoint_data is not None:
        enriched = TypeAdapter(list[TableMetadata]).validate_python(checkpoint_data)
        console.print(
            f"[green]✓[/green] Using cached enriched metadata ({len(enriched)} tables)"
        )
        console.print(
            "[dim]Run 'python scripts/clean_checkpoints.py enriched' to force re-enrichment[/dim]"
        )
        progress.update(task, completed=len(enriched), total=len(enriched))
        return enriched

    console.print("[yellow]→[/yellow] Enriching metadata with LLM...")

    enrichment = EnrichmentService(llm_client, max_concurrent=5)

    # Track progress manually since EnrichmentService doesn't have callbacks
    enriched_tables = []

    for completed, table in enumerate(tables, start=1):
        try:
            enriched = await enrichment.enrich_table(table)
            enriched_tables.append(enriched)
        except Exception as e:
            logger.error(
                "table_enrichment_failed", table=table.table_name, error=str(e)
            )
            enriched_tables.append(table)  # Keep original if enrichment fails

        progress.update(task, completed=completed)

    # Validate enrichment succeeded for at least some tables
    # Check if any tables have business_context (indicating successful enrichment)
    successfully_enriched = [
        t
        for t in enriched_tables
        if t.business_context is not None and t.business_context.strip()
    ]

    if not successfully_enriched:
        console.print(
            f"[red]✗[/red] Enrichment failed for all {len(enriched_tables)} tables"
        )
        console.print("[yellow]![/yellow] Cannot continue - enrichment is required")
        console.print("[dim]Fix LLM client configuration and try again[/dim]")
        raise RuntimeError(
            f"Enrichment failed for all {len(enriched_tables)} tables. "
            "Cannot continue with corrupted data."
        )

    # Save checkpoint only if at least some enrichment succeeded
    checkpoint_data = [table.model_dump() for table in enriched_tables]
    await write_checkpoint("02_enriched_metadata", checkpoint_data)
    console.print(
        f"[green]✓[/green] Enriched {len(successfully_enriched)}/{len(enriched_tables)} tables successfully"
    )

    return enriched_tables


async def chunk_and_duplicate_step(
    tables: list[TableMetadata],
    progress: Progress,
    task: TaskID,
) -> list[dict[str, Any]]:
    """
    Step 3: Chunk tables and duplicate across domains.

    Returns list of dicts ready for embedding.
    """

    console.print("[yellow]→[/yellow] Chunking and duplicating across domains...")

    chunking = ChunkingService()
    domain_service = DomainService()

    all_domain_chunks = []

    for table in tables:
        # Chunk table
        table_chunks = chunking.chunk_table(table)

        # Duplicate across domains
        domain_chunks = domain_service.duplicate_for_domains(table_chunks)

        # Convert to dict for JSON serialization
        for chunk in domain_chunks:
            all_domain_chunks.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "base_id": chunk.base_id,
                    "chunk_type": chunk.chunk_type,
                    "rag_resource_domain": chunk.rag_resource_domain,
                    "content": chunk.content,
                    "metadata": chunk.metadata,
                    "column_name": chunk.column_name,
                }
            )

        progress.update(task, advance=1)

    # Not saving checkpoint - function returns empty list
    return all_domain_chunks


async def embed_and_ingest_tables_step(
    chunks: list[dict[str, Any]],
    embedding_provider: EmbeddingProvider,
    vector_store: SQLiteMultiCollectionStore,
    progress: Progress,
    task: TaskID,
) -> None:
    """
    Step 4: Embed chunks and ingest into Tables collection.
    Args:
        chunks: List of chunks to embed
        embedding_provider: Embedding provider to use
        vector_store: Vector store to ingest into
        progress: Progress tracker
        task: Task ID for progress updates
    """
    console.print("[yellow]→[/yellow] Embedding and ingesting table chunks...")

    # Process in batches to avoid rate limits
    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]

        # Generate embeddings
        embeddings = await embedding_provider.embed_batch(
            [chunk["content"] for chunk in batch]
        )

        # Create vector records
        records = []
        for chunk, embedding in zip(batch, embeddings):
            records.append(
                VectorRecord(
                    id=chunk["chunk_id"],
                    content=chunk["content"],
                    embedding=embedding,
                    metadata={
                        **chunk["metadata"],
                        "base_id": chunk["base_id"],
                        "rag_resource_domain": chunk["rag_resource_domain"],
                        "chunk_type": chunk["chunk_type"],
                        **(
                            {"column_name": chunk["column_name"]}
                            if chunk["column_name"]
                            else {}
                        ),
                    },
                )
            )

        # Upsert to vector store
        await vector_store.upsert_tables(records)
        progress.update(task, advance=len(batch))

    console.print(
        f"[green]✓[/green] Ingested {len(chunks)} table chunks into vector store"
    )


def _utc_doc_set_version_int() -> int:
    return int(datetime.now(UTC).strftime("%Y%m%d"))


async def ingest_rag_packs_step(
    collection: CollectionType,
    embedding_provider: EmbeddingProvider,
    vector_store: SQLiteMultiCollectionStore,
    progress: Progress,
    task: TaskID,
    data: dict[str, Any] | None = None,
) -> None:
    """
    Loads RAG packs into defined collection.

    Args:
        collection: Collection type to ingest into
        embedding_provider: Embedding provider to use
        vector_store: Vector store to ingest into
        progress: Progress tracker
        task: Task ID for progress updates
        ndata: json pack data
    """

    if data:
        records = []
        console.print("[yellow]→[/yellow] Processing nuance pack...")

        for entry in data.get("records", []):
            content = entry.get("document", "")
            if not content:
                continue

            entry_metadata = entry.get("metadata", {})

            # Generate embedding
            embedding = await embedding_provider.embed(content)

            records.append(
                VectorRecord(
                    id=entry["id"],
                    content=content,
                    embedding=embedding,
                    metadata={
                        "rag_resource_domain": entry_metadata.get("domain"),
                        "doc_type": entry_metadata.get("doc_type", "general"),
                        "topic_id": entry_metadata.get("topic_id", ""),
                        "parent_id": entry_metadata.get("parent_id", ""),
                        "base_id": entry_metadata.get(
                            "base_id", entry["id"].split("@@domain=")[0]
                        ),
                        "warehouse_type": entry_metadata.get("warehouse_type", "both"),
                        "time_validity": entry_metadata.get("time_validity", "none"),
                        "involves_tags": entry_metadata.get("involves_tags", False),
                        "sku_family": entry_metadata.get("sku_family", "all"),
                        "is_active": entry_metadata.get("is_active", True),
                        "doc_set_version": entry_metadata.get(
                            "doc_set_version", _utc_doc_set_version_int()
                        ),
                        **(
                            {"code_key": entry_metadata.get("code_key", "")}
                            if "code_key" in entry_metadata
                            else {}
                        ),
                    },
                )
            )
            progress.update(task, advance=1)

        # Upsert all to defined collection
        collection_lower = collection.value.lower()

        if records:
            if collection_lower == "nuance":
                await vector_store.upsert_nuance(records)
            elif collection_lower == "codebook":
                await vector_store.upsert_codebook(records)
            else:
                raise ValueError(f"Unknown collection: {collection_lower}")

        console.print(
            f"[green]✓[/green] Embedding {len(records)} entries ({collection_lower})"
        )


async def ingest_facets_step(
    embedding_provider: EmbeddingProvider,
    vector_store: SQLiteMultiCollectionStore,
    progress: Progress,
    task: TaskID,
    codebook_data: dict[str, Any] | None = None,
) -> None:
    """
    Step 6: Load codebook, explode into facets, and ingest.

    Args:
        embedding_provider: Embedding provider to use
        vector_store: Vector store to ingest into
        progress: Progress tracker
        task: Task ID for progress updates
        codebook_data: Pre-loaded codebook data (optional, will load if not provided)
    """
    if codebook_data is None:
        if not CODEBOOK_FILE.exists():
            console.print(
                f"[yellow]![/yellow] Codebook file not found: {CODEBOOK_FILE}"
            )
            return

        console.print("[yellow]→[/yellow] Loading codebook...")
        with open(CODEBOOK_FILE) as f:
            codebook_data = json.load(f)

    console.print("[yellow]→[/yellow] Exploding codebook into facets...")

    # Explode codebook into individual facet entries
    records = []
    for entry in codebook_data["records"]:
        entry_metadata = entry.get("metadata", {})
        code_key = entry_metadata.get("code_key", "unknown")
        rag_resource_domain = entry_metadata.get("domain")
        values_csv = entry_metadata.get("values_csv", "")

        # Skip if no values
        if not values_csv:
            continue

        # Explode comma-separated values
        values = [v.strip() for v in values_csv.split(",")]

        for value in values:
            # Create facet content
            content = f"Code Key: {code_key}\nValue: {value}"
            if "document" in entry:
                # Include first 200 chars of document for context
                doc_excerpt = entry["document"][:200]
                content += f"\nContext: {doc_excerpt}"

            # Generate embedding
            embedding = await embedding_provider.embed(content)

            records.append(
                VectorRecord(
                    id=f"facet_{code_key}_{value}".replace(" ", "_")
                    .replace(".", "_")
                    .lower(),
                    content=content,
                    embedding=embedding,
                    metadata={
                        "rag_resource_domain": rag_resource_domain,
                        "code_key": code_key,
                        "field_value": value,
                        "doc_type": "facet",
                    },
                )
            )
            progress.update(task, advance=1)

    # Upsert to vector store
    await vector_store.upsert_facets(records)
    console.print(f"[green]✓[/green] Ingested {len(records)} facet entries")


async def main() -> int:
    """Main orchestration function."""
    console.print(
        "[bold cyan]Building RAG Vector Store for Analytics Agent V2[/bold cyan]\n"
    )

    load_dotenv()
    config = EnvConfig.from_env()

    # Create checkpoint directory
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize clients
    console.print("[yellow]→ Initializing clients...[/yellow]")

    databricks_conn = databricks_sql.connect(
        server_hostname=config.databricks_host_no_scheme,
        http_path=config.databricks_http_path,
        access_token=config.databricks_token,
    )
    databricks_client = DatabricksClientWrapper(databricks_conn)
    console.print("[yellow]\t→ Initalized Databricks client...[/yellow]")

    # LLM client
    llm_client = create_llm_client(cfg=config)

    # Embedding provider
    embedding_provider = LLMClientEmbeddingProvider()

    console.print("[yellow]\t→ Initalized LLM/Embedded client...[/yellow]")

    # Ensure data directory exists (resolve to absolute path)
    # The config path is relative, so resolve it from project root
    db_path = Path(config.sqlite_vector_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"[yellow]\t→ Vector store path: {str(db_path)}[/yellow]")

    # Vector store with eager initialization
    vector_store = SQLiteMultiCollectionStore(
        db_path=str(db_path),
        embedding_dim=config.embedding_dimension,
    )
    await vector_store.initialize()
    console.print("[yellow]\t→ Initalized Vector store...[/yellow]")

    console.print("[green]✓[/green] All clients initialized\n")

    # Create QueryAnalyzer (needed for MetadataExtractor)
    query_analyzer = QueryAnalyzer(dialect="databricks")

    # Progress tracking
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        try:
            # Step 1: Extract metadata (discovery runs automatically inside)
            task1 = progress.add_task(
                "Extracting metadata...", total=len(SYSTEM_SCHEMAS) * 10
            )
            tables = await extract_metadata_step(
                databricks_client, query_analyzer, progress, task1
            )

            t = progress.tasks[task1]
            progress.advance(task1, t.total - t.completed)

            # Step 2: Enrich with LLM
            task2 = progress.add_task("Enriching metadata...", total=len(tables))
            enriched_tables = await enrich_metadata_step(
                tables, llm_client, progress, task2
            )

            # Step 3: Chunk and duplicate
            task3 = progress.add_task(
                "Chunking and duplicating...", total=len(enriched_tables)
            )
            domain_chunks = await chunk_and_duplicate_step(
                enriched_tables, progress, task3
            )

            # Step 4: Embed and ingest tables
            task4 = progress.add_task(
                "Embedding and ingesting tables...", total=len(domain_chunks)
            )
            await embed_and_ingest_tables_step(
                domain_chunks, embedding_provider, vector_store, progress, task4
            )

            # Step 5: Ingest nuance AND codebook
            nuance_data = None
            nuance_count = 0

            if NUANCE_FILE.exists():
                with open(NUANCE_FILE) as f:
                    nuance_data = json.load(f)
                    nuance_count = len(nuance_data.get("records", []))

            if nuance_count > 0:
                task5 = progress.add_task("Ingesting nuance...", total=nuance_count)
                await ingest_rag_packs_step(
                    CollectionType.NUANCE,
                    embedding_provider,
                    vector_store,
                    progress,
                    task5,
                    data=nuance_data,
                )

            # Step 6: Ingest codebook
            codebook_data = None
            codebook_count = 0

            if CODEBOOK_FILE.exists():
                with open(CODEBOOK_FILE) as f:
                    codebook_data = json.load(f)
                    codebook_count = len(codebook_data.get("records", []))

            if codebook_count > 0:
                task6 = progress.add_task("Ingesting codebook...", total=codebook_count)
                await ingest_rag_packs_step(
                    CollectionType.CODEBOOK,
                    embedding_provider,
                    vector_store,
                    progress,
                    task6,
                    data=codebook_data,
                )

            # Step 7: Explode codebook into facets (separate Facets collection, per POC)
            facet_count = 0
            if codebook_data:
                # Count total facet values from values_csv
                for entry in codebook_data.get("records", []):
                    values_csv = entry.get("metadata", {}).get("values_csv", "")
                    if values_csv:
                        facet_count += len(
                            [v for v in values_csv.split(",") if v.strip()]
                        )

            if facet_count > 0:
                task7 = progress.add_task("Embedding facets...", total=facet_count)
                await ingest_facets_step(
                    embedding_provider,
                    vector_store,
                    progress,
                    task7,
                    codebook_data=codebook_data,
                )

        except Exception as e:
            console.print(f"\n[red]✗[/red] Error: {e}")
            logger.exception("build_failed", error=str(e))
            return 1
        finally:
            # Cleanup - close all pooled connections
            await vector_store.close()
            databricks_conn.close()

    # Summary
    console.print("\n[bold green]✓ Build Complete![/bold green]\n")
    console.print("Summary:")
    console.print(f"  Tables extracted: {len(tables)}")
    console.print(f"  Tables enriched: {len(enriched_tables)}")
    console.print(f"  Domain chunks: {len(domain_chunks)}")
    console.print(f"  Nuance entries: {nuance_count}")
    console.print(f"  Codebook entries: {codebook_count}")
    console.print(f"  Facet entries: {facet_count}")
    console.print(f"\nVector store: {db_path}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
