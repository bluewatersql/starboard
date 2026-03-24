# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Golden tests for diagnostic pattern matching system.

These tests use syrupy snapshots to detect pattern output regressions.
When patterns change intentionally, run `pytest --snapshot-update` to update.

Test cases cover:
- Tier 1 patterns (memory, network, sql)
- Tier 1b patterns (execution, storage)
- Exit code triage
- Negative signal confidence reduction
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from starboard_server.tools.domain.diagnostic.exit_code_triager import (
    ExitCodeTriager,
)
from starboard_server.tools.domain.diagnostic.pattern_matcher import (
    PatternMatcher,
)
from starboard_server.tools.domain.diagnostic.patterns.registry import (
    PatternRegistry,
)
from syrupy.assertion import SnapshotAssertion

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(scope="module")
def registry() -> PatternRegistry:
    """Load the production pattern catalog."""
    reg = PatternRegistry()
    catalog_dir = (
        Path(__file__).parent.parent.parent.parent
        / "packages"
        / "starboard-server"
        / "starboard_server"
        / "tools"
        / "domain"
        / "diagnostic"
        / "patterns"
        / "catalog"
    )
    if catalog_dir.exists():
        reg.load_from_directory(catalog_dir)
    return reg


@pytest.fixture
def matcher(registry: PatternRegistry) -> PatternMatcher:
    """Create pattern matcher with production patterns."""
    return PatternMatcher(registry)


@pytest.fixture
def triager() -> ExitCodeTriager:
    """Create exit code triager."""
    return ExitCodeTriager()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _match_result_to_dict(result) -> dict:
    """Convert match result to a serializable dict for snapshots."""
    return {
        "has_matches": result.has_matches,
        "match_count": result.match_count,
        "top_match": {
            "pattern_id": result.top_match.pattern_id,
            "confidence": round(result.top_match.confidence, 2),
            "evidence_refs": list(result.top_match.evidence_refs)[:2],
        }
        if result.top_match
        else None,
        # Use sorted list for deterministic ordering in snapshots
        "all_patterns": sorted([m.pattern_id for m in result.matches]),
    }


def _triage_result_to_dict(result) -> dict:
    """Convert triage result to a serializable dict for snapshots."""
    return {
        "exit_code": result.exit_code,
        "is_signal": result.is_signal,
        "signal_number": result.signal_number,
        "raw_interpretation": result.raw_interpretation,
        "primary_hypothesis": {
            "type": result.primary_hypothesis.hypothesis_type.value,
            "confidence": round(result.primary_hypothesis.confidence, 2),
            "supporting_evidence": list(result.primary_hypothesis.supporting_evidence),
            "next_steps": list(result.primary_hypothesis.next_steps)[:2],
        },
        "alternative_count": len(result.alternative_hypotheses),
    }


# =============================================================================
# TIER 1 MEMORY PATTERN GOLDEN TESTS
# =============================================================================


class TestMemoryPatternGolden:
    """Golden tests for memory-related patterns."""

    def test_java_heap_space_oom(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Java heap space OutOfMemoryError."""
        text = dedent("""
            2025-01-15 10:23:45 ERROR Executor 3 terminated with exception
            Caused by: java.lang.OutOfMemoryError: Java heap space
                at java.base/java.util.Arrays.copyOf(Arrays.java:3512)
                at org.apache.spark.sql.execution.aggregate.HashAggregateExec.doExecute
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)

    def test_gc_overhead_limit(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: GC overhead limit exceeded."""
        text = dedent("""
            java.lang.OutOfMemoryError: GC overhead limit exceeded
            at scala.collection.mutable.ListBuffer.$plus$eq(ListBuffer.scala:178)
            Full GC events detected before failure
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)

    def test_exit_code_137_oom_killed(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Exit code 137 with OOMKilled evidence."""
        text = dedent("""
            Container exited with code 137
            OOMKilled annotation present in pod status
            Memory usage exceeded limit: 15.8G / 16G
            """)
        result = matcher.match(text, exit_code=137)
        assert snapshot == _match_result_to_dict(result)

    def test_metaspace_oom(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Metaspace OutOfMemoryError."""
        text = "java.lang.OutOfMemoryError: Metaspace"
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)


# =============================================================================
# TIER 1 NETWORK PATTERN GOLDEN TESTS
# =============================================================================


class TestNetworkPatternGolden:
    """Golden tests for network-related patterns."""

    def test_shuffle_fetch_failed(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Shuffle fetch failed exception."""
        text = dedent("""
            org.apache.spark.shuffle.FetchFailedException:
            Failed to fetch shuffle block from executor 5
            Caused by: java.io.IOException: Failed to connect
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)

    def test_connection_timeout(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Connection timeout."""
        text = dedent("""
            java.net.SocketTimeoutException: Connection timed out
            Failed to connect to executor-5.example.com:7337
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)


# =============================================================================
# TIER 1 SQL PATTERN GOLDEN TESTS
# =============================================================================


class TestSqlPatternGolden:
    """Golden tests for SQL-related patterns."""

    def test_column_not_found(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Column not found AnalysisException."""
        text = dedent("""
            org.apache.spark.sql.AnalysisException: cannot resolve 'customer_id'
            given input columns: [id, name, email, created_at]
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)

    def test_permission_denied(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Permission denied error."""
        text = dedent("""
            PERMISSION_DENIED: User 'user@example.com' does not have
            SELECT permission on TABLE `catalog`.`schema`.`table`
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)

    def test_table_not_found(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Table or view not found."""
        text = "TABLE_OR_VIEW_NOT_FOUND: Table or view 'missing_table' not found"
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)


# =============================================================================
# TIER 1B EXECUTION PATTERN GOLDEN TESTS
# =============================================================================


class TestExecutionPatternGolden:
    """Golden tests for execution-related patterns."""

    def test_executor_lost(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Executor lost failure."""
        text = dedent("""
            ExecutorLostFailure: Executor 3 exited due to SIGKILL
            Lost executor 3 on worker-node-5
            Reason: Container killed by YARN for exceeding memory limits
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)

    def test_stage_failed_retries(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Stage failed after max retries."""
        text = dedent("""
            Job aborted due to stage failure: Stage 5 failed 4 times
            Most recent failure reason: Task 23 in stage 5.3 failed 4 times
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)

    def test_task_not_serializable(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Task not serializable exception."""
        text = dedent("""
            org.apache.spark.SparkException: Task not serializable
            Caused by: java.io.NotSerializableException: com.example.DatabaseClient
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)


# =============================================================================
# TIER 1B STORAGE PATTERN GOLDEN TESTS
# =============================================================================


class TestStoragePatternGolden:
    """Golden tests for storage-related patterns."""

    def test_disk_space_exhausted(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Disk space exhausted."""
        text = dedent("""
            java.io.IOException: No space left on device
            Failed to write shuffle data to /tmp/spark-shuffle
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)

    def test_s3_access_denied(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: S3 access denied."""
        text = dedent("""
            com.amazonaws.services.s3.model.AmazonS3Exception: Access Denied
            Status Code: 403, AWS Service: Amazon S3
            s3://my-bucket/data/file.parquet
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)


# =============================================================================
# EXIT CODE TRIAGE GOLDEN TESTS
# =============================================================================


class TestExitCodeTriageGolden:
    """Golden tests for exit code triage."""

    def test_exit_137_no_context(
        self, triager: ExitCodeTriager, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Exit 137 without additional context."""
        result = triager.triage(137)
        assert snapshot == _triage_result_to_dict(result)

    def test_exit_137_with_oom_evidence(
        self, triager: ExitCodeTriager, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Exit 137 with OOMKilled evidence."""
        result = triager.triage(137, "Container was OOMKilled by oom-killer")
        assert snapshot == _triage_result_to_dict(result)

    def test_exit_143_cancellation(
        self, triager: ExitCodeTriager, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Exit 143 with cancellation evidence."""
        result = triager.triage(143, "Job was cancelled by user")
        assert snapshot == _triage_result_to_dict(result)

    def test_exit_139_crash(
        self, triager: ExitCodeTriager, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Exit 139 (SIGSEGV) crash."""
        result = triager.triage(139, "Segmentation fault in native code")
        assert snapshot == _triage_result_to_dict(result)

    def test_exit_1_general_error(
        self, triager: ExitCodeTriager, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Exit 1 general error."""
        result = triager.triage(1)
        assert snapshot == _triage_result_to_dict(result)


# =============================================================================
# NEGATIVE SIGNAL GOLDEN TESTS
# =============================================================================


class TestNegativeSignalGolden:
    """Golden tests for negative signal confidence reduction."""

    def test_exit_137_reduced_by_cancellation(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Exit 137 confidence reduced by cancellation evidence.

        This test verifies that negative signals (like 'job cancellation')
        reduce confidence for patterns where that evidence is contradictory.
        """
        # Text with negative signal for OOM hypothesis
        text = dedent("""
            Process exited with code 137
            Job cancellation requested by admin
            No memory pressure detected
            """)
        result = matcher.match(text, exit_code=137)
        assert snapshot == _match_result_to_dict(result)

    def test_java_heap_reduced_by_manual_stop(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Java heap OOM confidence reduced by manual stop evidence."""
        text = dedent("""
            java.lang.OutOfMemoryError: Java heap space
            Note: Application was manually stopped by operator
            """)
        result = matcher.match(text)
        assert snapshot == _match_result_to_dict(result)


# =============================================================================
# MULTI-PATTERN GOLDEN TESTS
# =============================================================================


class TestMultiPatternGolden:
    """Golden tests for multi-pattern matching."""

    def test_multiple_patterns_same_log(self, registry: PatternRegistry) -> None:
        """Golden: Multiple patterns match in same log.

        Note: This test uses assertions instead of snapshots because
        pattern ordering can vary for equal-confidence matches.
        Uses higher max_matches to capture all patterns.
        """
        # Use higher max_matches to capture all patterns
        matcher = PatternMatcher(registry, max_matches=10)
        text = dedent("""
            java.lang.OutOfMemoryError: Java heap space
            org.apache.spark.shuffle.FetchFailedException: Failed to fetch
            ExecutorLostFailure: Executor 3 exited
            """)
        result = matcher.match(text)

        # Verify multiple patterns matched
        assert result.has_matches
        assert result.match_count >= 3

        # Verify core expected patterns are present
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "java_heap_space" in pattern_ids
        assert "executor_lost" in pattern_ids
        # shuffle_fetch_failed may or may not match based on keyword hits

        # Top match should be one of the high-confidence patterns
        assert result.top_match is not None
        assert result.top_match.pattern_id in pattern_ids


# =============================================================================
# TIER 2 PATTERN GOLDEN TESTS
# =============================================================================


class TestTier2DataPatterns:
    """Golden tests for Tier 2 data patterns."""

    def test_data_skew_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Data skew detection."""
        text = dedent("""
            WARNING: Data skew detected in stage 5
            Task 42 took 10x longer than median
            Skewed partition processing 95% of data
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "data_skew" in pattern_ids
        assert snapshot == _match_result_to_dict(result)

    def test_shuffle_spill_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Shuffle spill detection."""
        text = dedent("""
            Shuffle spill to disk: 4.5 GB
            Spill (Memory) 8.2 GB  Spill (Disk) 4.5 GB
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "shuffle_spill" in pattern_ids
        assert snapshot == _match_result_to_dict(result)

    def test_disk_full_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Disk full detection."""
        text = dedent("""
            java.io.IOException: No space left on device
            ENOSPC: Cannot write shuffle data
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "disk_full" in pattern_ids
        assert snapshot == _match_result_to_dict(result)


class TestTier2DeltaPatterns:
    """Golden tests for Tier 2 Delta Lake patterns."""

    def test_delta_concurrent_write_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Delta concurrent write conflict."""
        text = dedent("""
            ConcurrentModificationException: Conflicting write detected
            Transaction conflict on table delta.`/data/my_table`
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "delta_concurrent_write" in pattern_ids
        assert snapshot == _match_result_to_dict(result)

    def test_delta_corruption_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Delta table corruption."""
        text = dedent("""
            DeltaIllegalStateException: Table state is corrupted
            Invalid checkpoint at version 42
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "delta_corruption" in pattern_ids
        assert snapshot == _match_result_to_dict(result)


class TestTier2UCPatterns:
    """Golden tests for Tier 2 Unity Catalog patterns."""

    def test_uc_permission_denied_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Unity Catalog permission denied."""
        text = dedent("""
            PERMISSION_DENIED: User 'user@example.com' does not have
            SELECT permission on TABLE `catalog`.`schema`.`table`
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "uc_permission_denied" in pattern_ids
        assert snapshot == _match_result_to_dict(result)

    def test_uc_not_found_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Unity Catalog resource not found."""
        text = dedent("""
            TABLE_OR_VIEW_NOT_FOUND: Table 'my_catalog.my_schema.my_table'
            does not exist
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "uc_not_found" in pattern_ids
        assert snapshot == _match_result_to_dict(result)


class TestTier2MiscPatterns:
    """Golden tests for Tier 2 miscellaneous patterns."""

    def test_network_throttling_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Network throttling detection."""
        text = dedent("""
            SlowDown: Rate limit exceeded
            HTTP 429: Too many requests to S3
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "network_throttling" in pattern_ids
        assert snapshot == _match_result_to_dict(result)

    def test_python_worker_crash_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Python worker crash."""
        text = dedent("""
            PythonException: Python worker crashed
            Python process exited unexpectedly
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "python_worker_crash" in pattern_ids
        assert snapshot == _match_result_to_dict(result)

    def test_arrow_conversion_error_pattern(
        self, matcher: PatternMatcher, snapshot: SnapshotAssertion
    ) -> None:
        """Golden: Arrow conversion error."""
        text = dedent("""
            ArrowInvalid: cannot convert value
            Error in toPandas(): Arrow conversion failed
            """)
        result = matcher.match(text)
        pattern_ids = {m.pattern_id for m in result.matches}
        assert "arrow_conversion_error" in pattern_ids
        assert snapshot == _match_result_to_dict(result)
