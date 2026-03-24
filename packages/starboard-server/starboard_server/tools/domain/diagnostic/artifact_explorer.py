# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
ArtifactExplorer - Incremental discovery orchestrator for diagnostic artifacts.

This module provides:
- Exploration step/result dataclasses
- Strategy dispatch for diagnostic components
- Stopping conditions for exploration loop
- Exploration history and summary aggregation

Design reference:
- changes/diagnostic_agent/IMPLEMENTATION_CHECKLIST.md
- changes/diagnostic_agent/UNIFIED_DESIGN.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starboard_server.tools.domain.diagnostic.artifact_detector import (
        ArtifactDetector,
    )
    from starboard_server.tools.domain.diagnostic.context_extractor import (
        DatabricksContextExtractor,
    )
    from starboard_server.tools.domain.diagnostic.evidence_extractor import (
        EvidenceWindowExtractor,
    )
    from starboard_server.tools.domain.diagnostic.pattern_matcher import (
        PatternMatcher,
    )


class ExplorationStrategy(str, Enum):
    """Available exploration strategies.

    Phase 1 strategies (MVP - OFFLINE):
    - DETECT_TYPE: Identify artifact type
    - EXTRACT_EVIDENCE: Extract evidence windows
    - EXTRACT_IDS: Extract Databricks IDs

    Phase 2 strategies (Analysis):
    - MATCH_PATTERNS: Match against error patterns
    - EXPAND_WINDOW: Get more context around evidence
    - SUMMARIZE: Token-efficient summarization
    - CORRELATE: Cross-reference patterns
    - SYNTHESIZE: Final diagnosis synthesis

    Phase 3 strategies (ONLINE - require Databricks API):
    - FETCH_RUN_OUTPUT: Get job run output with task-level details
    - FETCH_CLUSTER_EVENTS: Get cluster events for context
    - FETCH_QUERY_HISTORY: Get query execution history
    """

    # OFFLINE strategies (work without Databricks API)
    DETECT_TYPE = "detect_type"
    EXTRACT_EVIDENCE = "extract_evidence"
    EXTRACT_IDS = "extract_ids"
    MATCH_PATTERNS = "match_patterns"
    EXPAND_WINDOW = "expand_window"
    SUMMARIZE = "summarize"
    CORRELATE = "correlate"
    SYNTHESIZE = "synthesize"

    # ONLINE strategies (require Databricks API)
    FETCH_RUN_OUTPUT = "fetch_run_output"
    FETCH_CLUSTER_EVENTS = "fetch_cluster_events"
    FETCH_QUERY_HISTORY = "fetch_query_history"


# Strategies that require Databricks API (ONLINE mode)
ONLINE_STRATEGIES: set[ExplorationStrategy] = {
    ExplorationStrategy.FETCH_RUN_OUTPUT,
    ExplorationStrategy.FETCH_CLUSTER_EVENTS,
    ExplorationStrategy.FETCH_QUERY_HISTORY,
}


@dataclass(frozen=True)
class ExplorationStep:
    """A single exploration step to execute.

    Attributes:
        strategy: The exploration strategy to use.
        target: What to explore (artifact text, window ID, etc.).
        rationale: Why this step is being taken.
    """

    strategy: ExplorationStrategy
    target: str
    rationale: str


@dataclass
class ToolCallRequest:
    """Request for an ONLINE tool call.

    When an ONLINE strategy is executed, it returns a ToolCallRequest
    that the agent should fulfill before continuing exploration.
    """

    tool_name: str
    """Name of the tool to call (e.g., 'get_run_output')."""

    parameters: dict[str, Any]
    """Parameters to pass to the tool."""

    rationale: str
    """Why this tool call is needed."""


@dataclass
class ExplorationResult:
    """Result of an exploration step.

    Attributes:
        strategy: The strategy that was executed.
        findings: Dictionary of findings from the step.
        confidence: Confidence level (0.0-1.0).
        next_steps: Suggested next strategies.
        evidence_refs: Evidence window IDs for citation.
        tool_call_request: For ONLINE strategies, the tool to call next.
        requires_online: True if this result requires ONLINE mode to continue.
    """

    strategy: ExplorationStrategy
    findings: dict[str, Any]
    confidence: float
    next_steps: list[ExplorationStrategy] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    tool_call_request: ToolCallRequest | None = None
    requires_online: bool = False


@dataclass
class ExplorationState:
    """Current state of exploration.

    Attributes:
        artifact_text: The artifact being explored.
        history: List of (step, result) tuples.
        current_confidence: Current confidence level.
        mode: Determined mode (online/offline/hybrid).
    """

    artifact_text: str
    history: list[tuple[ExplorationStep, ExplorationResult]]
    current_confidence: float
    mode: str | None

    @property
    def step_count(self) -> int:
        """Number of steps taken."""
        return len(self.history)


# Default configuration
_DEFAULT_MAX_STEPS = 6
_DEFAULT_CONFIDENCE_THRESHOLD = 0.80


class ArtifactExplorer:
    """Orchestrates incremental discovery through diagnostic components.

    The explorer uses a strategy pattern to dispatch exploration steps
    to the appropriate component (detector, evidence extractor, etc.).

    Example:
        >>> explorer = ArtifactExplorer(
        ...     detector=ArtifactDetector(),
        ...     evidence_extractor=EvidenceWindowExtractor(),
        ...     context_extractor=DatabricksContextExtractor(),
        ... )
        >>> result = explorer.explore(
        ...     "java.lang.OutOfMemoryError",
        ...     strategy=ExplorationStrategy.DETECT_TYPE
        ... )
        >>> print(result.findings["artifact_type"])
        'ERROR_MESSAGE'
    """

    def __init__(
        self,
        detector: ArtifactDetector,
        evidence_extractor: EvidenceWindowExtractor,
        context_extractor: DatabricksContextExtractor,
        *,
        pattern_matcher: PatternMatcher | None = None,
        max_steps: int = _DEFAULT_MAX_STEPS,
        confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        """Initialize explorer with dependencies.

        Args:
            detector: Artifact type detector.
            evidence_extractor: Evidence window extractor.
            context_extractor: Databricks ID extractor.
            pattern_matcher: Error pattern matcher (optional, required for match_patterns).
            max_steps: Maximum exploration steps.
            confidence_threshold: Confidence level to stop exploring.
        """
        self._detector = detector
        self._evidence_extractor = evidence_extractor
        self._context_extractor = context_extractor
        self._pattern_matcher = pattern_matcher
        self._max_steps = max_steps
        self._confidence_threshold = confidence_threshold

    def explore(
        self,
        text: str,
        *,
        strategy: ExplorationStrategy,
    ) -> ExplorationResult:
        """Execute a single exploration step.

        Args:
            text: Artifact text to explore.
            strategy: Strategy to use.

        Returns:
            ExplorationResult with findings and next steps.

        Raises:
            ValueError: If strategy is unknown.
        """
        if strategy == ExplorationStrategy.DETECT_TYPE:
            return self._explore_detect_type(text)
        elif strategy == ExplorationStrategy.EXTRACT_EVIDENCE:
            return self._explore_extract_evidence(text)
        elif strategy == ExplorationStrategy.EXTRACT_IDS:
            return self._explore_extract_ids(text)
        elif strategy == ExplorationStrategy.MATCH_PATTERNS:
            return self._explore_match_patterns(text)
        elif strategy == ExplorationStrategy.EXPAND_WINDOW:
            return self._explore_expand_window(text)
        elif strategy == ExplorationStrategy.SUMMARIZE:
            return self._explore_summarize(text)
        elif strategy == ExplorationStrategy.CORRELATE:
            return self._explore_correlate(text)
        elif strategy == ExplorationStrategy.SYNTHESIZE:
            return self._explore_not_implemented(strategy)
        # ONLINE strategies - require parsed IDs
        elif strategy == ExplorationStrategy.FETCH_RUN_OUTPUT:
            return self._explore_fetch_run_output(text)
        elif strategy == ExplorationStrategy.FETCH_CLUSTER_EVENTS:
            return self._explore_fetch_cluster_events(text)
        elif strategy == ExplorationStrategy.FETCH_QUERY_HISTORY:
            return self._explore_fetch_query_history(text)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

    def should_continue_exploring(self, state: ExplorationState) -> bool:
        """Determine if exploration should continue.

        Stopping conditions:
        1. Confidence >= threshold (default 80%)
        2. Max steps reached (default 6)
        3. No more suggested next steps (edge case)

        Args:
            state: Current exploration state.

        Returns:
            True if exploration should continue.
        """
        # Stop at high confidence
        if state.current_confidence >= self._confidence_threshold:
            return False

        # Stop at max steps
        return not state.step_count >= self._max_steps

    def get_exploration_summary(self, state: ExplorationState) -> dict[str, Any]:
        """Aggregate exploration history into summary.

        Args:
            state: Current exploration state.

        Returns:
            Summary dict with step_count, confidence, mode, evidence_refs.
        """
        # Collect all evidence refs
        all_evidence_refs: list[str] = []
        for _, result in state.history:
            all_evidence_refs.extend(result.evidence_refs)

        # Collect all findings
        all_findings: dict[str, Any] = {}
        for _, result in state.history:
            all_findings.update(result.findings)

        return {
            "step_count": state.step_count,
            "confidence": state.current_confidence,
            "mode": state.mode,
            "evidence_refs": all_evidence_refs,
            "findings": all_findings,
            "strategies_used": [result.strategy.value for _, result in state.history],
        }

    # =========================================================================
    # STRATEGY IMPLEMENTATIONS
    # =========================================================================

    def _explore_detect_type(self, text: str) -> ExplorationResult:
        """Detect artifact type using ArtifactDetector.

        Returns:
            ExplorationResult with artifact_type and language.
        """
        detection = self._detector.detect(text)

        findings = {
            "artifact_type": detection.artifact_type.value,
            "language": detection.language.value if detection.language else None,
        }

        # Suggest next steps based on detection
        next_steps = [
            ExplorationStrategy.EXTRACT_EVIDENCE,
            ExplorationStrategy.EXTRACT_IDS,
        ]

        return ExplorationResult(
            strategy=ExplorationStrategy.DETECT_TYPE,
            findings=findings,
            confidence=detection.confidence,
            next_steps=next_steps,
            evidence_refs=[],
        )

    def _explore_extract_evidence(self, text: str) -> ExplorationResult:
        """Extract evidence windows using EvidenceWindowExtractor.

        Returns:
            ExplorationResult with evidence windows.
        """
        extraction = self._evidence_extractor.extract(text)

        # Collect evidence refs
        evidence_refs = [w.window_id for w in extraction.windows]

        findings = {
            "window_count": extraction.window_count,
            "has_fatal": extraction.has_fatal,
            "summary": extraction.summary,
            "primary_type": (
                extraction.primary_evidence.evidence_type.value
                if extraction.primary_evidence
                else None
            ),
        }

        # Calculate confidence based on evidence quality
        confidence = 0.5
        if extraction.has_fatal:
            confidence = 0.8
        elif extraction.window_count > 0:
            confidence = 0.6

        # Suggest next steps
        next_steps = [ExplorationStrategy.EXTRACT_IDS]
        if confidence < 0.8:
            next_steps.append(ExplorationStrategy.MATCH_PATTERNS)

        return ExplorationResult(
            strategy=ExplorationStrategy.EXTRACT_EVIDENCE,
            findings=findings,
            confidence=confidence,
            next_steps=next_steps,
            evidence_refs=evidence_refs,
        )

    def _explore_extract_ids(self, text: str) -> ExplorationResult:
        """Extract Databricks IDs using ContextExtractor.

        Returns:
            ExplorationResult with mode and extracted IDs.
        """
        extraction = self._context_extractor.extract(text)

        # Collect extracted IDs
        ids = {
            "cluster_id": extraction.primary_cluster_id,
            "job_id": extraction.primary_job_id,
            "run_id": extraction.primary_run_id,
        }
        # Filter out None values
        ids = {k: v for k, v in ids.items() if v is not None}

        findings = {
            "mode": extraction.mode.value,
            "ids": ids,
            "has_online_capability": extraction.has_online_capability,
            "id_count": len(extraction.extracted_ids),
        }

        # Confidence based on ID extraction
        confidence = 0.7 if extraction.has_online_capability else 0.6

        # Suggest next steps
        next_steps = [ExplorationStrategy.MATCH_PATTERNS]

        return ExplorationResult(
            strategy=ExplorationStrategy.EXTRACT_IDS,
            findings=findings,
            confidence=confidence,
            next_steps=next_steps,
            evidence_refs=[],
        )

    def _explore_match_patterns(self, text: str) -> ExplorationResult:
        """Match artifact against known error patterns.

        Uses the PatternMatcher to identify known error patterns in the text.

        Returns:
            ExplorationResult with matched patterns and confidence.

        Raises:
            ValueError: If pattern_matcher was not provided at initialization.
        """
        if self._pattern_matcher is None:
            raise ValueError(
                "PatternMatcher not provided. Initialize ArtifactExplorer with "
                "pattern_matcher=PatternMatcher(registry) to use match_patterns strategy."
            )

        match_result = self._pattern_matcher.match(text)

        # Extract pattern information for findings
        patterns = []
        evidence_refs = []
        for match in match_result.matches:
            pattern_info = {
                "pattern_id": match.pattern_id,
                "confidence": match.confidence,
                "category": match.pattern.category.value,
                "title": match.pattern.name,
            }
            patterns.append(pattern_info)
            # Add pattern ID as evidence reference
            evidence_refs.append(f"pattern:{match.pattern_id}")

        findings = {
            "patterns": patterns,
            "match_count": match_result.match_count,
            "top_pattern": (
                match_result.top_match.pattern_id if match_result.top_match else None
            ),
        }

        # Calculate confidence from top match
        confidence = (
            match_result.top_match.confidence if match_result.top_match else 0.3
        )

        # Suggest next steps based on confidence
        next_steps: list[ExplorationStrategy] = []
        if confidence >= 0.8:
            next_steps.append(ExplorationStrategy.SYNTHESIZE)
        elif confidence >= 0.5:
            next_steps.append(ExplorationStrategy.CORRELATE)
            next_steps.append(ExplorationStrategy.SYNTHESIZE)
        else:
            next_steps.append(ExplorationStrategy.EXPAND_WINDOW)
            next_steps.append(ExplorationStrategy.CORRELATE)

        return ExplorationResult(
            strategy=ExplorationStrategy.MATCH_PATTERNS,
            findings=findings,
            confidence=confidence,
            next_steps=next_steps,
            evidence_refs=evidence_refs,
        )

    def _explore_expand_window(self, text: str) -> ExplorationResult:
        """Expand context around evidence windows for better analysis.

        Uses the EvidenceWindowExtractor to find key evidence and expands
        the context around it for more thorough analysis.

        Returns:
            ExplorationResult with expanded text and context information.
        """
        lines = text.split("\n")
        total_lines = len(lines)

        # Use evidence extractor to find key windows
        extraction = self._evidence_extractor.extract(text)

        # Find line ranges with evidence
        evidence_lines: set[int] = set()
        for window in extraction.windows:
            # Find the line(s) containing this evidence
            for i, line in enumerate(lines):
                if window.content.strip() in line or any(
                    part.strip() in line
                    for part in window.content.split("\n")
                    if part.strip()
                ):
                    evidence_lines.add(i)

        # Expand context around evidence lines (±3 lines)
        context_radius = 3
        expanded_lines: set[int] = set()
        for line_num in evidence_lines:
            for offset in range(-context_radius, context_radius + 1):
                expanded_line = line_num + offset
                if 0 <= expanded_line < total_lines:
                    expanded_lines.add(expanded_line)

        # Build expanded text
        sorted_lines = sorted(expanded_lines)
        expanded_text_parts: list[str] = []
        prev_line = -2
        for line_num in sorted_lines:
            if line_num > prev_line + 1 and expanded_text_parts:
                # Gap in lines - add separator
                expanded_text_parts.append("...")
            expanded_text_parts.append(lines[line_num])
            prev_line = line_num

        expanded_text = "\n".join(expanded_text_parts)

        # Calculate line range
        start_line = min(sorted_lines) if sorted_lines else 0
        end_line = max(sorted_lines) if sorted_lines else 0

        findings = {
            "context_lines": len(sorted_lines),
            "expanded_text": expanded_text,
            "line_range": f"{start_line + 1}-{end_line + 1}",
            "start_line": start_line + 1,
            "end_line": end_line + 1,
            "evidence_count": extraction.window_count,
            "original_lines": total_lines,
        }

        # Calculate confidence based on evidence quality
        confidence = 0.5
        if extraction.has_fatal:
            confidence = 0.7
        elif extraction.window_count > 0:
            confidence = 0.6

        # Suggest next steps
        next_steps: list[ExplorationStrategy] = [
            ExplorationStrategy.MATCH_PATTERNS,
            ExplorationStrategy.CORRELATE,
        ]

        # Collect evidence refs
        evidence_refs = [f"window:{w.window_id}" for w in extraction.windows]

        return ExplorationResult(
            strategy=ExplorationStrategy.EXPAND_WINDOW,
            findings=findings,
            confidence=confidence,
            next_steps=next_steps,
            evidence_refs=evidence_refs,
        )

    def _explore_summarize(self, text: str) -> ExplorationResult:
        """Summarize large artifacts to key evidence for token efficiency.

        Extracts key evidence windows and builds a condensed summary
        that preserves diagnostic information while reducing token usage.

        Returns:
            ExplorationResult with summarized text and compression stats.
        """
        lines = text.split("\n")
        original_lines = len(lines)

        # Use evidence extractor to find key windows
        extraction = self._evidence_extractor.extract(text)

        # Build summary from evidence windows
        summary_parts = []
        for window in extraction.windows:
            summary_parts.append(
                f"[{window.evidence_type.value}] {window.content.strip()}"
            )

        # If no evidence found, extract error-like lines
        if not summary_parts:
            error_keywords = ["error", "exception", "failed", "failure", "fatal"]
            for line in lines:
                line_lower = line.lower()
                if any(kw in line_lower for kw in error_keywords):
                    summary_parts.append(line.strip())
                    if len(summary_parts) >= 10:  # Limit summary lines
                        break

        # If still nothing, take first and last few lines
        if not summary_parts:
            summary_parts = [ln.strip() for ln in lines[:3] if ln.strip()]
            if original_lines > 6:
                summary_parts.append("...")
                summary_parts.extend([ln.strip() for ln in lines[-3:] if ln.strip()])

        summary = "\n".join(summary_parts)

        # Calculate compression ratio
        original_chars = len(text)
        summary_chars = len(summary)
        compression_ratio = (
            1 - (summary_chars / original_chars) if original_chars > 0 else 0
        )

        findings = {
            "summary": summary,
            "original_lines": original_lines,
            "summary_lines": len(summary_parts),
            "compression_ratio": round(compression_ratio, 2),
            "evidence_count": extraction.window_count,
        }

        # Confidence based on evidence found
        confidence = 0.6 if extraction.window_count > 0 else 0.4

        # Suggest next steps
        next_steps: list[ExplorationStrategy] = [
            ExplorationStrategy.MATCH_PATTERNS,
            ExplorationStrategy.EXTRACT_EVIDENCE,
        ]

        evidence_refs = [f"window:{w.window_id}" for w in extraction.windows]

        return ExplorationResult(
            strategy=ExplorationStrategy.SUMMARIZE,
            findings=findings,
            confidence=confidence,
            next_steps=next_steps,
            evidence_refs=evidence_refs,
        )

    def _explore_correlate(self, text: str) -> ExplorationResult:
        """Cross-reference patterns and evidence to disambiguate root cause.

        Combines evidence from multiple sources (patterns, evidence windows,
        context IDs) to identify the most likely root cause.

        Returns:
            ExplorationResult with correlation analysis and primary cause.
        """
        # Extract all available information
        extraction = self._evidence_extractor.extract(text)
        context = self._context_extractor.extract(text)

        # Get pattern matches if pattern matcher available
        pattern_matches = []
        if self._pattern_matcher:
            match_result = self._pattern_matcher.match(text)
            pattern_matches = list(match_result.matches)

        # Build correlation data
        evidence_types = [w.evidence_type.value for w in extraction.windows]
        pattern_ids = [m.pattern_id for m in pattern_matches]
        pattern_confidences = [m.confidence for m in pattern_matches]

        # Determine primary cause based on highest confidence pattern
        primary_cause = None
        primary_confidence = 0.0
        if pattern_matches:
            top_match = pattern_matches[0]
            primary_cause = top_match.pattern_id
            primary_confidence = top_match.confidence

        # Calculate correlation confidence
        # Higher if multiple sources agree
        confidence = 0.5
        if extraction.has_fatal and pattern_matches:
            confidence = 0.8
        elif extraction.window_count > 0 and pattern_matches:
            confidence = 0.7
        elif pattern_matches:
            confidence = pattern_confidences[0] if pattern_confidences else 0.5

        findings = {
            "primary_cause": primary_cause,
            "primary_confidence": primary_confidence,
            "correlation": {
                "evidence_types": evidence_types,
                "pattern_ids": pattern_ids,
                "pattern_count": len(pattern_matches),
                "evidence_count": extraction.window_count,
                "mode": context.mode.value,
            },
            "has_online_capability": context.has_online_capability,
        }

        # Always suggest synthesize after correlation
        next_steps: list[ExplorationStrategy] = [ExplorationStrategy.SYNTHESIZE]

        # Collect evidence refs
        evidence_refs = [f"window:{w.window_id}" for w in extraction.windows]
        evidence_refs.extend([f"pattern:{m.pattern_id}" for m in pattern_matches])

        return ExplorationResult(
            strategy=ExplorationStrategy.CORRELATE,
            findings=findings,
            confidence=confidence,
            next_steps=next_steps,
            evidence_refs=evidence_refs,
        )

    def _explore_not_implemented(
        self, strategy: ExplorationStrategy
    ) -> ExplorationResult:
        """Placeholder for Phase 2 strategies.

        Returns:
            ExplorationResult indicating strategy not yet implemented.
        """
        return ExplorationResult(
            strategy=strategy,
            findings={"status": "not_implemented", "phase": 2},
            confidence=0.0,
            next_steps=[],
            evidence_refs=[],
        )

    # =========================================================================
    # ONLINE Exploration Strategies (require Databricks API)
    # =========================================================================

    def _explore_fetch_run_output(self, text: str) -> ExplorationResult:
        """Request job run output fetch via ONLINE tool.

        This strategy extracts run_id from the text and creates a tool call
        request for get_run_output. The agent should execute this tool and
        pass results to process_tool_result().

        Returns:
            ExplorationResult with tool_call_request for get_run_output.
        """
        # Extract context to get run_id
        context = self._context_extractor.extract(text)

        run_id = context.primary_run_id
        if not run_id:
            # No run_id found - can't proceed with ONLINE fetch
            return ExplorationResult(
                strategy=ExplorationStrategy.FETCH_RUN_OUTPUT,
                findings={
                    "status": "missing_id",
                    "error": "No run_id found in artifact. Cannot fetch run output.",
                    "suggestion": "Provide run_id or job_id to enable ONLINE lookup.",
                },
                confidence=0.4,
                next_steps=[ExplorationStrategy.MATCH_PATTERNS],
                evidence_refs=[],
                requires_online=False,
            )

        # Create tool call request
        tool_request = ToolCallRequest(
            tool_name="get_run_output",
            parameters={"run_id": run_id},
            rationale=f"Fetch detailed run output and task logs for run {run_id}",
        )

        return ExplorationResult(
            strategy=ExplorationStrategy.FETCH_RUN_OUTPUT,
            findings={
                "status": "tool_call_required",
                "run_id": run_id,
                "mode": "online",
            },
            confidence=0.6,  # Will increase after tool response
            next_steps=[ExplorationStrategy.CORRELATE],
            evidence_refs=[],
            tool_call_request=tool_request,
            requires_online=True,
        )

    def _explore_fetch_cluster_events(self, text: str) -> ExplorationResult:
        """Request cluster events fetch via ONLINE tool.

        This strategy extracts cluster_id from the text and creates a tool call
        request for get_cluster_events.

        Returns:
            ExplorationResult with tool_call_request for get_cluster_events.
        """
        # Extract context to get cluster_id
        context = self._context_extractor.extract(text)

        cluster_id = context.primary_cluster_id
        if not cluster_id:
            return ExplorationResult(
                strategy=ExplorationStrategy.FETCH_CLUSTER_EVENTS,
                findings={
                    "status": "missing_id",
                    "error": "No cluster_id found in artifact.",
                    "suggestion": "Provide cluster_id to enable ONLINE lookup.",
                },
                confidence=0.4,
                next_steps=[ExplorationStrategy.MATCH_PATTERNS],
                evidence_refs=[],
                requires_online=False,
            )

        # Create tool call request
        tool_request = ToolCallRequest(
            tool_name="get_cluster_events",
            parameters={"cluster_id": cluster_id},
            rationale=f"Fetch cluster events for {cluster_id} to identify issues",
        )

        return ExplorationResult(
            strategy=ExplorationStrategy.FETCH_CLUSTER_EVENTS,
            findings={
                "status": "tool_call_required",
                "cluster_id": cluster_id,
                "mode": "online",
            },
            confidence=0.6,
            next_steps=[ExplorationStrategy.CORRELATE],
            evidence_refs=[],
            tool_call_request=tool_request,
            requires_online=True,
        )

    def _explore_fetch_query_history(self, text: str) -> ExplorationResult:
        """Request query history fetch via ONLINE tool.

        This strategy extracts query_id/statement_id from the text and creates
        a tool call request for query history lookup.

        Returns:
            ExplorationResult with tool_call_request for query lookup.
        """
        # Extract context to get query IDs
        context = self._context_extractor.extract(text)

        # Look for query-related IDs
        query_id = None
        for extracted_id in context.extracted_ids:
            if extracted_id.id_type.value in ("query_id", "statement_id"):
                query_id = extracted_id.value
                break
        if not query_id:
            return ExplorationResult(
                strategy=ExplorationStrategy.FETCH_QUERY_HISTORY,
                findings={
                    "status": "missing_id",
                    "error": "No query_id or statement_id found in artifact.",
                    "suggestion": "Provide query_id to enable ONLINE lookup.",
                },
                confidence=0.4,
                next_steps=[ExplorationStrategy.MATCH_PATTERNS],
                evidence_refs=[],
                requires_online=False,
            )

        # Create tool call request
        tool_request = ToolCallRequest(
            tool_name="resolve_query",
            parameters={"target": query_id},
            rationale=f"Fetch query details for {query_id} to analyze execution",
        )

        return ExplorationResult(
            strategy=ExplorationStrategy.FETCH_QUERY_HISTORY,
            findings={
                "status": "tool_call_required",
                "query_id": query_id,
                "mode": "online",
            },
            confidence=0.6,
            next_steps=[ExplorationStrategy.CORRELATE],
            evidence_refs=[],
            tool_call_request=tool_request,
            requires_online=True,
        )

    def process_tool_result(
        self,
        strategy: ExplorationStrategy,
        tool_result: dict[str, Any],
    ) -> ExplorationResult:
        """Process the result of an ONLINE tool call.

        After the agent executes a tool requested by an ONLINE strategy,
        call this method to process the result and update confidence.

        Args:
            strategy: The ONLINE strategy that requested the tool.
            tool_result: The result returned by the tool.

        Returns:
            ExplorationResult with updated confidence based on tool findings.
        """
        # Extract relevant information from tool result
        error = tool_result.get("error")
        summary = tool_result.get("summary")
        state = tool_result.get("state", "")

        # Build findings from tool result
        findings: dict[str, Any] = {
            "status": "tool_completed",
            "tool_state": state,
        }

        # Check for errors
        if error:
            findings["tool_error"] = error
        if summary:
            findings["task_summary"] = summary

        # Extract failed task info
        failed_tasks = tool_result.get("failed_tasks", [])
        if failed_tasks:
            findings["failed_task_count"] = len(failed_tasks)
            findings["first_failure"] = failed_tasks[0] if failed_tasks else None

        # Calculate confidence boost based on findings
        confidence = 0.7
        if error or summary or failed_tasks:
            # Tool provided useful diagnostic info
            confidence = 0.85
        if state == "FAILED":
            confidence = 0.9

        # Suggest correlation after tool result
        next_steps = [ExplorationStrategy.CORRELATE, ExplorationStrategy.SYNTHESIZE]

        # Build evidence refs from tool result
        evidence_refs = [f"tool:{strategy.value}"]
        if failed_tasks:
            for task in failed_tasks[:3]:
                task_key = task.get("task_key", "unknown")
                evidence_refs.append(f"task:{task_key}")

        return ExplorationResult(
            strategy=strategy,
            findings=findings,
            confidence=confidence,
            next_steps=next_steps,
            evidence_refs=evidence_refs,
            requires_online=False,  # Tool already executed
        )

    def process_tool_failure(
        self,
        strategy: ExplorationStrategy,
        error_message: str,
        *,
        fallback_to_offline: bool = True,
    ) -> ExplorationResult:
        """Handle tool failure with graceful fallback to OFFLINE mode.

        When an ONLINE tool call fails (e.g., timeout, permission denied,
        API unavailable), this method provides a fallback path that continues
        exploration in OFFLINE mode.

        Args:
            strategy: The ONLINE strategy that failed.
            error_message: The error message from the failed tool call.
            fallback_to_offline: If True, suggest OFFLINE strategies. If False,
                abort exploration.

        Returns:
            ExplorationResult indicating tool failure and suggesting next steps.
        """
        findings: dict[str, Any] = {
            "status": "tool_failed",
            "error": error_message,
            "fallback_mode": "offline" if fallback_to_offline else "abort",
        }

        if fallback_to_offline:
            # Suggest OFFLINE strategies to continue without API
            next_steps = [
                ExplorationStrategy.MATCH_PATTERNS,
                ExplorationStrategy.CORRELATE,
            ]
            findings["guidance"] = (
                "Tool call failed. Continuing with OFFLINE analysis based on "
                "artifact content only. Consider providing additional context."
            )
            confidence = 0.5  # Lower confidence without API confirmation
        else:
            next_steps = []
            findings["guidance"] = (
                "Tool call failed and no fallback available. "
                "Unable to complete ONLINE analysis."
            )
            confidence = 0.3

        return ExplorationResult(
            strategy=strategy,
            findings=findings,
            confidence=confidence,
            next_steps=next_steps,
            evidence_refs=[],
            requires_online=False,  # Falling back to OFFLINE
        )

    def is_online_strategy(self, strategy: ExplorationStrategy) -> bool:
        """Check if a strategy requires ONLINE mode.

        Args:
            strategy: The strategy to check.

        Returns:
            True if strategy requires Databricks API access.
        """
        return strategy in ONLINE_STRATEGIES

    def get_offline_alternative(
        self, strategy: ExplorationStrategy
    ) -> ExplorationStrategy | None:
        """Get an OFFLINE alternative for an ONLINE strategy.

        Args:
            strategy: The ONLINE strategy to find an alternative for.

        Returns:
            An OFFLINE strategy that can provide similar (but limited) insights,
            or None if no alternative exists.
        """
        # Map ONLINE strategies to OFFLINE alternatives
        alternatives = {
            ExplorationStrategy.FETCH_RUN_OUTPUT: ExplorationStrategy.MATCH_PATTERNS,
            ExplorationStrategy.FETCH_CLUSTER_EVENTS: ExplorationStrategy.MATCH_PATTERNS,
            ExplorationStrategy.FETCH_QUERY_HISTORY: ExplorationStrategy.MATCH_PATTERNS,
        }
        return alternatives.get(strategy)
