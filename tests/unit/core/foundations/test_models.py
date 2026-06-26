# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for foundation models."""

from datetime import UTC, datetime, timedelta

import pytest
from starboard_core.foundations.models import (
    CacheEntry,
    ReflexionLearning,
    VectorRecord,
    VectorSearchResult,
)


class TestVectorSearchResult:
    """Tests for VectorSearchResult dataclass."""

    def test_create_vector_search_result(self):
        """Test creating a valid VectorSearchResult."""
        result = VectorSearchResult(
            id="vec_123",
            score=0.95,
            metadata={"source": "documentation"},
            content="How to optimize Databricks clusters",
        )

        assert result.id == "vec_123"
        assert result.score == 0.95
        assert result.metadata == {"source": "documentation"}
        assert result.content == "How to optimize Databricks clusters"

    def test_vector_search_result_immutable(self):
        """Test that VectorSearchResult is immutable."""
        result = VectorSearchResult(
            id="vec_123", score=0.95, metadata={}, content="test"
        )

        with pytest.raises(AttributeError):
            result.score = 0.5  # type: ignore


class TestVectorRecord:
    """Tests for VectorRecord dataclass."""

    def test_create_vector_record(self):
        """Test creating a valid VectorRecord."""
        embedding = [0.1, 0.2, 0.3]
        record = VectorRecord(
            id="vec_456",
            embedding=embedding,
            metadata={"source": "docs", "type": "guide"},
            content="Cluster optimization guide",
        )

        assert record.id == "vec_456"
        assert record.embedding == embedding
        assert record.metadata == {"source": "docs", "type": "guide"}
        assert record.content == "Cluster optimization guide"

    def test_vector_record_with_large_embedding(self):
        """Test VectorRecord with realistic embedding size."""
        # OpenAI embeddings are 1536 dimensions
        embedding = [0.01] * 1536
        record = VectorRecord(
            id="vec_789", embedding=embedding, metadata={}, content="test content"
        )

        assert len(record.embedding) == 1536

    def test_vector_record_immutable(self):
        """Test that VectorRecord is immutable."""
        record = VectorRecord(
            id="vec_789", embedding=[0.1], metadata={}, content="test"
        )

        with pytest.raises(AttributeError):
            record.content = "modified"  # type: ignore


class TestReflexionLearning:
    """Tests for ReflexionLearning dataclass."""

    def test_create_reflexion_learning(self):
        """Test creating a valid ReflexionLearning."""
        now = datetime.now(UTC)
        learning = ReflexionLearning(
            id="learn_123",
            problem="Query optimization for large tables",
            solution="Use partitioning and limit scans",
            feedback="Initial approach caused timeout",
            success_score=0.85,
            created_at=now,
            tags=["query", "optimization", "performance"],
            agent_domain="query",
            metadata={"table_size_gb": 1000},
        )

        assert learning.id == "learn_123"
        assert learning.problem == "Query optimization for large tables"
        assert learning.solution == "Use partitioning and limit scans"
        assert learning.feedback == "Initial approach caused timeout"
        assert learning.success_score == 0.85
        assert learning.created_at == now
        assert learning.tags == ["query", "optimization", "performance"]
        assert learning.agent_domain == "query"
        assert learning.metadata == {"table_size_gb": 1000}

    def test_reflexion_learning_with_defaults(self):
        """Test ReflexionLearning with default values."""
        learning = ReflexionLearning(
            id="learn_456",
            problem="Problem description",
            solution="Solution description",
            feedback="Feedback description",
            success_score=0.7,
            created_at=datetime.now(UTC),
        )

        assert learning.tags == []
        assert learning.agent_domain == ""
        assert learning.metadata == {}

    def test_reflexion_learning_invalid_score_too_high(self):
        """Test that success_score > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="success_score must be between 0 and 1"):
            ReflexionLearning(
                id="learn_invalid",
                problem="Test",
                solution="Test",
                feedback="Test",
                success_score=1.5,
                created_at=datetime.now(UTC),
            )

    def test_reflexion_learning_invalid_score_negative(self):
        """Test that negative success_score raises ValueError."""
        with pytest.raises(ValueError, match="success_score must be between 0 and 1"):
            ReflexionLearning(
                id="learn_invalid",
                problem="Test",
                solution="Test",
                feedback="Test",
                success_score=-0.1,
                created_at=datetime.now(UTC),
            )

    def test_reflexion_learning_empty_problem(self):
        """Test that empty problem raises ValueError."""
        with pytest.raises(ValueError, match="problem cannot be empty"):
            ReflexionLearning(
                id="learn_invalid",
                problem="",
                solution="Test solution",
                feedback="Test feedback",
                success_score=0.5,
                created_at=datetime.now(UTC),
            )

    def test_reflexion_learning_empty_solution(self):
        """Test that empty solution raises ValueError."""
        with pytest.raises(ValueError, match="solution cannot be empty"):
            ReflexionLearning(
                id="learn_invalid",
                problem="Test problem",
                solution="",
                feedback="Test feedback",
                success_score=0.5,
                created_at=datetime.now(UTC),
            )

    def test_reflexion_learning_immutable(self):
        """Test that ReflexionLearning is immutable."""
        learning = ReflexionLearning(
            id="learn_789",
            problem="Test",
            solution="Test",
            feedback="Test",
            success_score=0.5,
            created_at=datetime.now(UTC),
        )

        with pytest.raises(AttributeError):
            learning.success_score = 0.9  # type: ignore


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_create_cache_entry(self):
        """Test creating a valid CacheEntry."""
        now = datetime.now(UTC)
        embedding = [0.1, 0.2, 0.3]
        response = {"jobs": [{"id": "job_1", "cost": 100}]}

        entry = CacheEntry(
            id="cache_123",
            query="Show me top 10 expensive jobs",
            query_embedding=embedding,
            response=response,
            created_at=now,
            ttl=300,
            metadata={"model": "gpt-4", "temperature": 0.4},
        )

        assert entry.id == "cache_123"
        assert entry.query == "Show me top 10 expensive jobs"
        assert entry.query_embedding == embedding
        assert entry.response == response
        assert entry.created_at == now
        assert entry.ttl == 300
        assert entry.metadata == {"model": "gpt-4", "temperature": 0.4}

    def test_cache_entry_with_default_metadata(self):
        """Test CacheEntry with default metadata."""
        entry = CacheEntry(
            id="cache_456",
            query="Test query",
            query_embedding=[0.1],
            response={"result": "test"},
            created_at=datetime.now(UTC),
            ttl=60,
        )

        assert entry.metadata == {}

    def test_cache_entry_not_expired(self):
        """Test that fresh cache entry is not expired."""
        entry = CacheEntry(
            id="cache_789",
            query="Test query",
            query_embedding=[0.1],
            response={"result": "test"},
            created_at=datetime.now(UTC),
            ttl=300,
        )

        assert not entry.is_expired

    def test_cache_entry_expired(self):
        """Test that old cache entry is expired."""
        old_time = datetime.now(UTC) - timedelta(seconds=400)
        entry = CacheEntry(
            id="cache_expired",
            query="Test query",
            query_embedding=[0.1],
            response={"result": "test"},
            created_at=old_time,
            ttl=300,  # 5 minutes TTL, but entry is 400 seconds old
        )

        assert entry.is_expired

    def test_cache_entry_exactly_at_ttl(self):
        """Test cache entry exactly at TTL boundary."""
        exact_time = datetime.now(UTC) - timedelta(seconds=300)
        entry = CacheEntry(
            id="cache_boundary",
            query="Test query",
            query_embedding=[0.1],
            response={"result": "test"},
            created_at=exact_time,
            ttl=300,
        )

        # At exactly TTL, should be expired (> not >=)
        assert entry.is_expired

    def test_cache_entry_immutable(self):
        """Test that CacheEntry is immutable."""
        entry = CacheEntry(
            id="cache_123",
            query="Test",
            query_embedding=[0.1],
            response={},
            created_at=datetime.now(UTC),
            ttl=300,
        )

        with pytest.raises(AttributeError):
            entry.ttl = 600  # type: ignore
