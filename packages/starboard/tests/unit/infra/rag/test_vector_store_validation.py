# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for SQLiteVectorStore collection name and ORDER BY validation."""

from __future__ import annotations

import pytest
from starboard.infra.rag.adapters.storage.sqlite_vector_store import (
    SQLiteVectorStore,
)


class TestCollectionNameValidation:
    """Test collection name allowlist and pattern validation."""

    def test_allowed_names_accepted(self) -> None:
        """All CollectionType enum values and 'default' should be accepted."""
        for name in ("default", "tables", "nuance", "codebook", "facets", "learnings"):
            store = SQLiteVectorStore(db_path=":memory:", collection_name=name)
            assert store.collection_name == name

    def test_safe_pattern_accepted(self) -> None:
        """Names matching the safe alphanumeric pattern should be accepted."""
        store = SQLiteVectorStore(
            db_path=":memory:", collection_name="custom_collection"
        )
        assert store.collection_name == "custom_collection"

    def test_sql_injection_in_name_rejected(self) -> None:
        """SQL injection attempts in collection name should be rejected."""
        with pytest.raises(ValueError, match="Invalid collection name"):
            SQLiteVectorStore(
                db_path=":memory:", collection_name="tables; DROP TABLE --"
            )

    def test_special_chars_rejected(self) -> None:
        """Names with special characters should be rejected."""
        for bad_name in ("my-table", "table name", "table'name", "123start", "UPPER"):
            with pytest.raises(ValueError, match="Invalid collection name"):
                SQLiteVectorStore(db_path=":memory:", collection_name=bad_name)

    def test_empty_name_rejected(self) -> None:
        """Empty collection name should be rejected."""
        with pytest.raises(ValueError, match="Invalid collection name"):
            SQLiteVectorStore(db_path=":memory:", collection_name="")

    def test_overly_long_name_rejected(self) -> None:
        """Names exceeding 64 characters should be rejected."""
        long_name = "a" * 65
        with pytest.raises(ValueError, match="Invalid collection name"):
            SQLiteVectorStore(db_path=":memory:", collection_name=long_name)


class TestOrderByValidation:
    """Test ORDER BY clause allowlist validation."""

    def test_allowed_order_by_accepted(self) -> None:
        """Allowlisted ORDER BY clauses should pass."""
        for clause in ("created_at ASC", "created_at DESC", "id ASC", "id DESC"):
            result = SQLiteVectorStore._validate_order_by(clause)
            assert result == clause

    def test_injection_in_order_by_rejected(self) -> None:
        """SQL injection in ORDER BY should be rejected."""
        with pytest.raises(ValueError, match="Invalid ORDER BY"):
            SQLiteVectorStore._validate_order_by("created_at; DROP TABLE users --")

    def test_arbitrary_column_rejected(self) -> None:
        """Non-allowlisted columns should be rejected."""
        with pytest.raises(ValueError, match="Invalid ORDER BY"):
            SQLiteVectorStore._validate_order_by("metadata DESC")

    def test_subquery_in_order_by_rejected(self) -> None:
        """Subqueries in ORDER BY should be rejected."""
        with pytest.raises(ValueError, match="Invalid ORDER BY"):
            SQLiteVectorStore._validate_order_by("(SELECT 1) DESC")
