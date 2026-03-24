"""
CI/CD evaluation runner for fast smoke tests.

This runner executes a subset of critical test cases designed for
quick feedback in CI pipelines.

Usage:
    python -m evals.runners.ci_runner
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from evals.metrics.evaluator import EvalCase, EvalSummary, Evaluator
from evals.runners.batch_runner import mock_agent_fn

# Critical cases that must pass for CI to succeed
CRITICAL_CASES = [
    # Query domain smoke tests
    EvalCase(
        id="ci_query_001",
        description="Query agent responds to basic optimization request",
        domain="query",
        input_goal="Optimize this SQL query for better performance",
        expected_contains=("query", "optimization"),
        min_confidence=0.5,
        tags=("smoke", "critical"),
    ),
    # Job domain smoke tests
    EvalCase(
        id="ci_job_001",
        description="Job agent responds to performance analysis",
        domain="job",
        input_goal="Analyze job performance and identify bottlenecks",
        expected_contains=("job", "performance"),
        min_confidence=0.5,
        tags=("smoke", "critical"),
    ),
    # Warehouse domain smoke tests
    EvalCase(
        id="ci_warehouse_001",
        description="Warehouse agent responds to portfolio request",
        domain="warehouse",
        input_goal="Show me our SQL warehouses",
        expected_contains=("warehouse",),
        min_confidence=0.5,
        tags=("smoke", "critical"),
    ),
]


@dataclass
class CIResult:
    """Result of CI evaluation run."""

    passed: bool
    total_cases: int
    failed_cases: int
    duration_s: float
    summaries: dict[str, EvalSummary]


class CIRunner:
    """
    CI/CD evaluation runner.

    Runs critical smoke tests for fast CI feedback.
    """

    def __init__(self) -> None:
        """Initialize CI runner."""
        self.evaluator = Evaluator()

    async def run(self) -> CIResult:
        """
        Run CI smoke tests.

        Returns:
            CIResult with pass/fail status and metrics
        """
        import time

        start = time.perf_counter()

        # Group cases by domain
        cases_by_domain: dict[str, list[EvalCase]] = {}
        for case in CRITICAL_CASES:
            if case.domain not in cases_by_domain:
                cases_by_domain[case.domain] = []
            cases_by_domain[case.domain].append(case)

        # Run evaluations
        summaries: dict[str, EvalSummary] = {}
        all_failed = 0

        for domain, cases in cases_by_domain.items():
            results = await self.evaluator.run_cases(cases, mock_agent_fn)
            summary = self.evaluator.summarize(results, domain)
            summaries[domain] = summary
            all_failed += summary.failed_cases

        duration = time.perf_counter() - start

        return CIResult(
            passed=all_failed == 0,
            total_cases=len(CRITICAL_CASES),
            failed_cases=all_failed,
            duration_s=duration,
            summaries=summaries,
        )


def print_ci_result(result: CIResult) -> None:
    """Print CI evaluation result."""
    status = "✅ PASSED" if result.passed else "❌ FAILED"

    print("\n" + "=" * 50)
    print(f"CI Evaluation: {status}")
    print("=" * 50)
    print(f"Cases: {result.total_cases - result.failed_cases}/{result.total_cases}")
    print(f"Duration: {result.duration_s:.2f}s")

    for domain, summary in result.summaries.items():
        status_icon = "✅" if summary.failed_cases == 0 else "❌"
        print(f"  {status_icon} {domain}: {summary.passed_cases}/{summary.total_cases}")

        for case_id in summary.failed_ids:
            print(f"      ❌ {case_id}")


async def main() -> int:
    """Main entry point for CI runner."""
    runner = CIRunner()
    result = await runner.run()
    print_ci_result(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
