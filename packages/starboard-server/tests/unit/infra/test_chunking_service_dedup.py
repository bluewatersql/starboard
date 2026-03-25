"""Tests for chunk deduplication in ChunkingService (item 9).

TDD: Written before implementation.
"""

from __future__ import annotations

from starboard_server.infra.rag.services.chunking_service import ChunkingService


def _make_table(full_name: str = "system.billing.usage") -> object:
    """Build a minimal TableMetadata-like object for testing."""
    from starboard_core.rag.models import TableMetadata

    return TableMetadata(
        table_catalog="system",
        table_schema="billing",
        table_name="usage",
        full_name=full_name,
        table_type="TABLE",
        columns=[],
        relationships=[],
        common_use_cases=[],
        common_join_columns=[],
    )


class TestChunkDeduplication:
    """Verify chunk_table produces no duplicate base_ids."""

    def test_no_duplicate_base_ids(self) -> None:
        """All chunks returned from chunk_table must have unique base_ids."""
        service = ChunkingService()
        table = _make_table()

        chunks = service.chunk_table(table)

        base_ids = [c.base_id for c in chunks]
        unique_ids = set(base_ids)

        assert len(base_ids) == len(unique_ids), (
            f"Duplicate base_ids found: "
            f"{[bid for bid in base_ids if base_ids.count(bid) > 1]}"
        )

    def test_no_duplicate_content(self) -> None:
        """Chunks with identical content should not be included twice."""
        service = ChunkingService()
        table = _make_table()

        chunks = service.chunk_table(table)
        contents = [c.content for c in chunks]

        # Allow minor differences but no exact duplicates
        unique_contents = set(contents)
        assert len(contents) == len(unique_contents), (
            f"Duplicate chunk contents found ({len(contents) - len(unique_contents)} duplicates)"
        )

    def test_summary_chunk_appears_once(self) -> None:
        """The table_summary chunk type should appear exactly once."""
        service = ChunkingService()
        table = _make_table()

        chunks = service.chunk_table(table)
        summary_chunks = [c for c in chunks if c.chunk_type == "table_summary"]

        assert len(summary_chunks) == 1, (
            f"Expected 1 table_summary chunk, got {len(summary_chunks)}"
        )

    def test_chunk_table_idempotent(self) -> None:
        """Calling chunk_table twice with same table produces same chunks."""
        service = ChunkingService()
        table = _make_table()

        chunks1 = service.chunk_table(table)
        chunks2 = service.chunk_table(table)

        ids1 = sorted(c.base_id for c in chunks1)
        ids2 = sorted(c.base_id for c in chunks2)
        assert ids1 == ids2
