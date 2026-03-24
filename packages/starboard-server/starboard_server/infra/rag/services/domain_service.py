"""Domain duplication service for RAG resource-model domains.

This service duplicates table chunks across one or more *RAG resource domains*
for improved retrieval. These domains are Databricks resource-model aligned and
are intentionally distinct from Starboard agent routing domains.

Output metadata key: `rag_resource_domain`
Source of truth for domain labels: `starboard_core.rag.resource_domains`
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from starboard_core.rag.resource_domains import map_system_table_to_rag_resource_domains

from starboard_server.infra.rag.services.chunking_service import TableChunk

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DomainChunk:
    """
    Domain-specific chunk for vector store ingestion.

    Represents a table chunk duplicated for a specific domain.

    Attributes:
        chunk_id: Unique ID (base_id + domain, e.g., "system.billing.usage::table_summary::finops_billing")
        base_id: Canonical ID from chunking (e.g., "system.billing.usage::table_summary")
        chunk_type: Type of chunk ("table_summary" | "use_cases" | "relationships" | "column")
        rag_resource_domain: RAG resource domain (Databricks resource-model aligned)
        content: Text content for embedding
        metadata: Additional metadata (includes domain)
        column_name: Column name (for column chunks only)
    """

    chunk_id: str
    base_id: str
    chunk_type: str
    rag_resource_domain: str
    content: str
    metadata: dict[str, str]
    column_name: str | None = None


class DomainService:
    """
    Service for duplicating chunks across domains.

    Handles mapping tables to domains and generating unique chunk IDs.
    """

    def __init__(self) -> None:
        """Initialize domain service."""

    def duplicate_for_domains(self, chunks: list[TableChunk]) -> list[DomainChunk]:
        """
        Duplicate chunks across all applicable domains.

        Args:
            chunks: Table chunks from ChunkingService

        Returns:
            List of domain chunks with unique chunk_ids

        Example:
            >>> service = DomainService()
            >>> table_chunks = chunking_service.chunk_table(table)
            >>> domain_chunks = service.duplicate_for_domains(table_chunks)
            >>> print(f"Generated {len(domain_chunks)} domain chunks from {len(table_chunks)}")
        """
        domain_chunks: list[DomainChunk] = []

        for chunk in chunks:
            # Get domains for this table
            domains = self._get_domains_for_table(chunk.metadata["table_name"])

            if not domains:
                logger.warning(
                    "no_domains_found",
                    table=chunk.metadata["table_name"],
                    base_id=chunk.base_id,
                )
                # Still create a chunk with "default" domain
                domains = ["workspace_admin"]

            # Duplicate chunk for each domain
            for rag_resource_domain in domains:
                domain_chunk = self._create_domain_chunk(chunk, rag_resource_domain)
                domain_chunks.append(domain_chunk)

        logger.debug(
            "chunks_duplicated",
            input_chunks=len(chunks),
            output_chunks=len(domain_chunks),
            unique_tables=len({c.metadata["table_name"] for c in chunks}),
        )

        return domain_chunks

    def _get_domains_for_table(self, table_name: str) -> list[str]:
        """Return resource-model domains for a system table."""
        mapped = map_system_table_to_rag_resource_domains(table_name)
        return [d.value for d in mapped]

    def _create_domain_chunk(
        self, chunk: TableChunk, rag_resource_domain: str
    ) -> DomainChunk:
        """
        Create domain-specific chunk from table chunk.

        Args:
            chunk: Table chunk from ChunkingService
            domain: Domain name

        Returns:
            Domain chunk with unique chunk_id
        """
        chunk_id = self._make_chunk_id(chunk.base_id, rag_resource_domain)

        # Copy metadata and add rag_resource_domain
        metadata = {**chunk.metadata, "rag_resource_domain": rag_resource_domain}

        return DomainChunk(
            chunk_id=chunk_id,
            base_id=chunk.base_id,
            chunk_type=chunk.chunk_type,
            rag_resource_domain=rag_resource_domain,
            content=chunk.content,
            metadata=metadata,
            column_name=chunk.column_name,
        )

    def _make_chunk_id(self, base_id: str, rag_resource_domain: str) -> str:
        """
        Generate unique chunk ID from base_id and domain.

        Format: "{base_id}::{rag_resource_domain}"

        Args:
            base_id: Canonical ID from chunking
            domain: Domain name

        Returns:
            Unique chunk ID

        Example:
            >>> _make_chunk_id("system.billing.usage::table_summary", "finops_billing")
            "system.billing.usage::table_summary::finops_billing"
        """
        return f"{base_id}::{rag_resource_domain}"
