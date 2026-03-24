# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Unit tests for diagnostic agent artifact-based routing.

Tests verify that:
- Stack traces are routed to diagnostic agent
- Exit codes are detected and routed
- OOM patterns are caught
- Spark failure patterns are caught
- Exclusivity patterns work correctly
"""

from starboard_server.agents.routing.domain_intents import (
    DOMAIN_INTENTS,
    route_by_scoring,
    score_domain,
)

# =============================================================================
# ARTIFACT ROUTING TESTS
# =============================================================================


class TestStackTraceRouting:
    """Tests for stack trace artifact routing."""

    def test_java_exception_routes_to_diagnostic(self) -> None:
        """Java exception should route to diagnostic."""
        user_input = """java.lang.OutOfMemoryError: Java heap space
            at java.base/java.util.Arrays.copyOf
            at org.apache.spark.sql.execution.aggregate.HashAggregateExec"""

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"
        assert confidence >= 0.9

    def test_python_traceback_routes_to_diagnostic(self) -> None:
        """Python traceback should route to diagnostic."""
        user_input = """Traceback (most recent call last):
            File "notebook.py", line 45, in process_data
            raise ValueError("Invalid data format")"""

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"
        assert "Exclusive pattern" in reason

    def test_caused_by_chain_routes_to_diagnostic(self) -> None:
        """Caused by chain should route to diagnostic."""
        user_input = """Exception in thread "main"
            java.lang.RuntimeException: Failed
            Caused by: java.io.IOException: Connection refused"""

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"


class TestExitCodeRouting:
    """Tests for exit code routing."""

    def test_exit_137_routes_to_diagnostic(self) -> None:
        """Exit 137 should route to diagnostic with high confidence."""
        user_input = "my job exited with code 137"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"

    def test_exit_143_routes_to_diagnostic(self) -> None:
        """Exit 143 should route to diagnostic."""
        user_input = "Container exit code 143"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"

    def test_sigkill_routes_to_diagnostic(self) -> None:
        """SIGKILL mention should route to diagnostic."""
        user_input = "Process terminated with SIGKILL"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"


class TestOOMRouting:
    """Tests for OOM pattern routing."""

    def test_out_of_memory_routes_to_diagnostic(self) -> None:
        """Out of memory error should route to diagnostic."""
        user_input = "Got java.lang.OutOfMemoryError: Java heap space"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"

    def test_gc_overhead_routes_to_diagnostic(self) -> None:
        """GC overhead limit should route to diagnostic."""
        user_input = "OutOfMemoryError: GC overhead limit exceeded"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"

    def test_oom_killed_routes_to_diagnostic(self) -> None:
        """OOMKilled status should route to diagnostic."""
        user_input = "Container was OOMKilled by oom-killer"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"


class TestSparkFailureRouting:
    """Tests for Spark failure pattern routing."""

    def test_executor_lost_routes_to_diagnostic(self) -> None:
        """Executor lost failure should route to diagnostic."""
        user_input = "ExecutorLostFailure: Executor 3 exited"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"

    def test_fetch_failed_routes_to_diagnostic(self) -> None:
        """FetchFailedException should route to diagnostic."""
        user_input = "FetchFailedException: Failed to fetch shuffle block"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"

    def test_shuffle_failed_routes_to_diagnostic(self) -> None:
        """Shuffle failed should route to diagnostic."""
        user_input = "Stage failed because shuffle fetch failed"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"

    def test_analysis_exception_routes_to_diagnostic(self) -> None:
        """AnalysisException should route to diagnostic."""
        user_input = "AnalysisException: cannot resolve 'column'"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"


class TestRootCauseRouting:
    """Tests for root cause analysis queries."""

    def test_why_fail_routes_to_diagnostic(self) -> None:
        """Why fail question should route to diagnostic."""
        user_input = "why did my job fail?"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"

    def test_root_cause_routes_to_diagnostic(self) -> None:
        """Root cause query should route to diagnostic."""
        user_input = "what is the root cause of this error?"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"

    def test_troubleshoot_routes_to_diagnostic(self) -> None:
        """Troubleshoot query should route to diagnostic."""
        user_input = "help me troubleshoot this issue"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"


class TestScoreComparison:
    """Tests for score comparison with other domains."""

    def test_diagnostic_beats_job_for_failure(self) -> None:
        """Diagnostic should score higher than job for failure with traces."""
        user_input = "my job failed with ExecutorLostFailure"

        diag_intent = DOMAIN_INTENTS["diagnostic"]
        job_intent = DOMAIN_INTENTS["job"]

        diag_score, _ = score_domain(user_input.lower(), diag_intent, {})
        job_score, _ = score_domain(user_input.lower(), job_intent, {})

        assert diag_score > job_score

    def test_diagnostic_beats_cluster_for_oom(self) -> None:
        """Diagnostic should score higher than cluster for OOM."""
        user_input = "cluster ran out of memory, got OutOfMemoryError"

        diag_intent = DOMAIN_INTENTS["diagnostic"]
        cluster_intent = DOMAIN_INTENTS["cluster"]

        diag_score, _ = score_domain(user_input.lower(), diag_intent, {})
        cluster_score, _ = score_domain(user_input.lower(), cluster_intent, {})

        assert diag_score >= cluster_score

    def test_diagnostic_wins_for_stack_trace(self) -> None:
        """Diagnostic should win for any input with stack trace."""
        user_input = """query failed with:
            org.apache.spark.SparkException: Task failed
            Caused by: java.lang.OutOfMemoryError"""

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "diagnostic"


class TestEdgeCases:
    """Tests for edge cases in diagnostic routing."""

    def test_empty_input_does_not_route_diagnostic(self) -> None:
        """Empty input should not route to diagnostic."""
        domain, confidence, reason = route_by_scoring("", {})

        # Should get a fallback or no match
        assert confidence < 0.5 or domain != "diagnostic"

    def test_simple_job_query_routes_to_job(self) -> None:
        """Simple job query without errors should go to job agent."""
        user_input = "optimize my job"

        domain, confidence, reason = route_by_scoring(user_input.lower(), {})

        assert domain == "job"

    def test_diagnostic_with_job_id_still_routes(self) -> None:
        """Diagnostic patterns with job_id should still route to diagnostic."""
        user_input = "job 12345 failed with exit code 137"

        domain, confidence, reason = route_by_scoring(
            user_input.lower(), {"job_id": "12345"}
        )

        # Diagnostic wins due to exit code pattern
        assert domain == "diagnostic"
