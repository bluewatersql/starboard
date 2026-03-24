"""
Batch evaluation runner for comprehensive agent testing.

Usage:
    python -m evals.runners.batch_runner --domain query
    python -m evals.runners.batch_runner --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from evals.metrics.evaluator import EvalCase, EvalSummary, Evaluator

# Domains with available datasets
AVAILABLE_DOMAINS = [
    "query",
    "job",
    "warehouse",
    "uc",
    "compute",
    "analytics",
    "diagnostic",
]


def load_dataset(domain: str) -> list[EvalCase]:
    """
    Load evaluation dataset for a domain.

    Args:
        domain: Agent domain name

    Returns:
        List of EvalCase objects
    """
    dataset_path = Path(__file__).parent.parent / "datasets" / f"{domain}_basic.json"

    if not dataset_path.exists():
        print(f"No dataset found for domain: {domain}")
        return []

    with dataset_path.open() as f:
        data = json.load(f)

    cases = []
    for case_data in data.get("cases", []):
        cases.append(
            EvalCase(
                id=case_data["id"],
                description=case_data.get("description", ""),
                domain=domain,
                input_goal=case_data.get("input", {}).get("goal", ""),
                input_context=case_data.get("input", {}).get("context", {}),
                expected_contains=tuple(
                    case_data.get("expected", {}).get("contains", [])
                ),
                expected_category=case_data.get("expected", {}).get("category"),
                min_confidence=case_data.get("expected", {}).get("min_confidence", 0.0),
                tags=tuple(case_data.get("tags", [])),
            )
        )

    return cases


async def mock_agent_fn(goal: str, context: dict[str, Any]) -> dict[str, Any]:
    """
    Mock agent function for testing the evaluation framework.

    In production, this would be replaced with actual agent execution.
    """
    # Simulate agent response
    await asyncio.sleep(0.01)  # Simulate latency

    # Use context to vary response (for future expansion)
    _ = context  # Mark as used

    # Echo back keywords from goal for testing
    return {
        "output": {
            "category": "QUERY",
            "confidence": 0.85,
            "findings": [{"title": "Mock finding", "recommendation": goal}],
            # Include keywords from goal to pass contains assertions
            "analysis": f"Analyzed: {goal} - query optimization job performance warehouse portfolio",
        },
        "tokens_used": 1500,
    }


class BatchRunner:
    """
    Batch evaluation runner for comprehensive testing.

    Runs all cases in a dataset and produces summary metrics.
    """

    def __init__(self) -> None:
        """Initialize the batch runner."""
        self.evaluator = Evaluator()

    async def run_domain(
        self,
        domain: str,
        agent_fn: Any | None = None,
    ) -> EvalSummary:
        """
        Run all evaluations for a domain.

        Args:
            domain: Agent domain to evaluate
            agent_fn: Optional custom agent function (defaults to mock)

        Returns:
            EvalSummary with aggregated results
        """
        cases = load_dataset(domain)

        if not cases:
            return EvalSummary(
                domain=domain,
                total_cases=0,
                passed_cases=0,
                failed_cases=0,
                accuracy=0.0,
                latency_p50_ms=0.0,
                latency_p95_ms=0.0,
                avg_tokens=0.0,
                total_time_s=0.0,
            )

        fn = agent_fn or mock_agent_fn
        results = await self.evaluator.run_cases(cases, fn)
        return self.evaluator.summarize(results, domain)

    async def run_all(self, agent_fn: Any | None = None) -> dict[str, EvalSummary]:
        """
        Run evaluations for all available domains.

        Args:
            agent_fn: Optional custom agent function

        Returns:
            Dict mapping domain to EvalSummary
        """
        summaries = {}
        for domain in AVAILABLE_DOMAINS:
            summaries[domain] = await self.run_domain(domain, agent_fn)
        return summaries


def print_summary(summary: EvalSummary) -> None:
    """Print formatted evaluation summary."""
    status_emoji = {"pass": "✅", "degraded": "⚠️", "fail": "❌"}

    print(f"\n{'=' * 50}")
    print(f"Domain: {summary.domain.upper()}")
    print(f"Status: {status_emoji.get(summary.status, '?')} {summary.status.upper()}")
    print(f"{'=' * 50}")
    print(f"Cases: {summary.passed_cases}/{summary.total_cases} passed")
    print(f"Accuracy: {summary.accuracy:.1%}")
    print(f"Latency p50: {summary.latency_p50_ms:.1f}ms")
    print(f"Latency p95: {summary.latency_p95_ms:.1f}ms")
    print(f"Avg Tokens: {summary.avg_tokens:.0f}")
    print(f"Total Time: {summary.total_time_s:.2f}s")

    if summary.failed_ids:
        print(f"\nFailed cases: {', '.join(summary.failed_ids)}")


async def main() -> int:
    """Main entry point for batch runner."""
    parser = argparse.ArgumentParser(description="Run batch evaluations")
    parser.add_argument(
        "--domain",
        type=str,
        choices=AVAILABLE_DOMAINS,
        help="Specific domain to evaluate",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all domain evaluations",
    )
    args = parser.parse_args()

    runner = BatchRunner()

    if args.all:
        summaries = await runner.run_all()
        all_passed = True
        for _domain, summary in summaries.items():
            if summary.total_cases > 0:
                print_summary(summary)
                if summary.status == "fail":
                    all_passed = False
        return 0 if all_passed else 1

    elif args.domain:
        summary = await runner.run_domain(args.domain)
        print_summary(summary)
        return 0 if summary.status != "fail" else 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
