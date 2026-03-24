"""
Core evaluation logic for agent behavior testing.

This module provides:
- EvalCase: Test case definition
- EvalResult: Individual evaluation result
- EvalSummary: Aggregated evaluation metrics
- Evaluator: Main evaluation engine
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class EvalCase:
    """
    A single evaluation test case.

    Attributes:
        id: Unique identifier for the case
        description: Human-readable description
        domain: Agent domain (query, job, warehouse, etc.)
        input_goal: User goal to evaluate
        input_context: Additional context for the evaluation
        expected_contains: Keywords expected in output
        expected_category: Expected finding category
        min_confidence: Minimum confidence threshold
        tags: Classification tags for filtering
    """

    id: str
    description: str
    domain: str
    input_goal: str
    input_context: dict[str, Any] = field(default_factory=dict)
    expected_contains: tuple[str, ...] = ()
    expected_category: str | None = None
    min_confidence: float = 0.0
    tags: tuple[str, ...] = ()


@dataclass
class EvalResult:
    """
    Result of evaluating a single case.

    Attributes:
        case_id: ID of the evaluated case
        passed: Whether the evaluation passed
        latency_ms: Execution time in milliseconds
        tokens_used: Total tokens consumed
        output: Raw output from the agent
        errors: Any errors encountered
        assertions: Results of individual assertions
    """

    case_id: str
    passed: bool
    latency_ms: float
    tokens_used: int = 0
    output: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    assertions: dict[str, bool] = field(default_factory=dict)


@dataclass
class EvalSummary:
    """
    Aggregated evaluation summary.

    Attributes:
        domain: Agent domain evaluated
        total_cases: Number of cases run
        passed_cases: Number of cases passed
        failed_cases: Number of cases failed
        accuracy: Pass rate (0.0 to 1.0)
        latency_p50_ms: Median latency
        latency_p95_ms: 95th percentile latency
        avg_tokens: Average tokens per evaluation
        total_time_s: Total evaluation time
        failed_ids: IDs of failed cases
    """

    domain: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    accuracy: float
    latency_p50_ms: float
    latency_p95_ms: float
    avg_tokens: float
    total_time_s: float
    failed_ids: list[str] = field(default_factory=list)

    @property
    def status(self) -> Literal["pass", "fail", "degraded"]:
        """Overall status based on accuracy threshold."""
        if self.accuracy >= 0.90:
            return "pass"
        elif self.accuracy >= 0.80:
            return "degraded"
        return "fail"


class Evaluator:
    """
    Main evaluation engine.

    Runs evaluation cases against agents and collects metrics.

    Example:
        >>> evaluator = Evaluator()
        >>> results = await evaluator.run_cases(cases, agent)
        >>> summary = evaluator.summarize(results, "query")
    """

    def __init__(self) -> None:
        """Initialize the evaluator."""
        self._start_time: float = 0.0

    async def run_case(
        self,
        case: EvalCase,
        agent_fn: Any,  # Callable that accepts goal/context and returns output
    ) -> EvalResult:
        """
        Run a single evaluation case.

        Args:
            case: The evaluation case to run
            agent_fn: Async function that simulates agent execution

        Returns:
            EvalResult with pass/fail status and metrics
        """
        start = time.perf_counter()
        errors: list[str] = []
        assertions: dict[str, bool] = {}
        output: dict[str, Any] = {}
        tokens_used = 0

        try:
            # Execute the agent
            result = await agent_fn(
                goal=case.input_goal,
                context=case.input_context,
            )

            output = result.get("output", {})
            tokens_used = result.get("tokens_used", 0)

            # Run assertions
            if case.expected_contains:
                output_str = str(output).lower()
                for keyword in case.expected_contains:
                    key = f"contains_{keyword}"
                    assertions[key] = keyword.lower() in output_str
                    if not assertions[key]:
                        errors.append(f"Missing keyword: {keyword}")

            if case.expected_category:
                actual_category = output.get("category", "")
                assertions["category_match"] = actual_category == case.expected_category
                if not assertions["category_match"]:
                    errors.append(
                        f"Category mismatch: expected {case.expected_category}, "
                        f"got {actual_category}"
                    )

            if case.min_confidence > 0:
                actual_confidence = output.get("confidence", 0.0)
                assertions["confidence_threshold"] = (
                    actual_confidence >= case.min_confidence
                )
                if not assertions["confidence_threshold"]:
                    errors.append(
                        f"Confidence below threshold: {actual_confidence} < "
                        f"{case.min_confidence}"
                    )

        except Exception as e:
            errors.append(f"Execution error: {e!s}")

        latency_ms = (time.perf_counter() - start) * 1000
        passed = len(errors) == 0

        return EvalResult(
            case_id=case.id,
            passed=passed,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            output=output,
            errors=errors,
            assertions=assertions,
        )

    async def run_cases(
        self,
        cases: list[EvalCase],
        agent_fn: Any,
    ) -> list[EvalResult]:
        """
        Run multiple evaluation cases.

        Args:
            cases: List of cases to evaluate
            agent_fn: Async function for agent execution

        Returns:
            List of EvalResult for each case
        """
        results = []
        for case in cases:
            result = await self.run_case(case, agent_fn)
            results.append(result)
        return results

    def summarize(self, results: list[EvalResult], domain: str) -> EvalSummary:
        """
        Summarize evaluation results.

        Args:
            results: List of individual results
            domain: Agent domain for the summary

        Returns:
            EvalSummary with aggregated metrics
        """
        if not results:
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

        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]

        latencies = sorted(r.latency_ms for r in results)
        tokens = [r.tokens_used for r in results]

        p50_idx = len(latencies) // 2
        p95_idx = int(len(latencies) * 0.95)

        return EvalSummary(
            domain=domain,
            total_cases=len(results),
            passed_cases=len(passed),
            failed_cases=len(failed),
            accuracy=len(passed) / len(results),
            latency_p50_ms=latencies[p50_idx] if latencies else 0.0,
            latency_p95_ms=latencies[min(p95_idx, len(latencies) - 1)]
            if latencies
            else 0.0,
            avg_tokens=sum(tokens) / len(tokens) if tokens else 0.0,
            total_time_s=sum(r.latency_ms for r in results) / 1000,
            failed_ids=[r.case_id for r in failed],
        )
