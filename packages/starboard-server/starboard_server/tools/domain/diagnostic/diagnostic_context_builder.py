# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
DiagnosticContextBuilder - Builds exploration context for prompt injection.

This module provides:
- Initial exploration of artifacts before LLM reasoning
- Context formatting for prompt injection
- Exploration state tracking for multi-turn diagnostics

Design reference:
- changes/diagnostic_agent/IMPLEMENTATION_CHECKLIST.md (LLM Integration)
- changes/diagnostic_agent/UNIFIED_DESIGN.md (Exploration Strategy)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starboard_server.tools.domain.diagnostic.artifact_explorer import (
        ArtifactExplorer,
    )

from starboard_server.tools.domain.diagnostic.artifact_explorer import (
    ExplorationState,
    ExplorationStrategy,
)

# Maximum artifact length before truncation (chars)
_MAX_ARTIFACT_LENGTH = 100_000


@dataclass
class ToolResultCache:
    """Cache for tool results during multi-step exploration.

    Prevents redundant tool calls by caching results keyed by tool name + parameters.

    Attributes:
        _cache: Dict mapping cache keys to tool results.
        _hit_count: Number of cache hits.
        _miss_count: Number of cache misses.
    """

    _cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    _hit_count: int = 0
    _miss_count: int = 0

    def get(self, tool_name: str, parameters: dict[str, Any]) -> dict[str, Any] | None:
        """Get cached result if available.

        Args:
            tool_name: Name of the tool.
            parameters: Tool parameters (used as cache key).

        Returns:
            Cached result or None if not found.
        """
        cache_key = self._make_key(tool_name, parameters)
        if cache_key in self._cache:
            self._hit_count += 1
            return self._cache[cache_key]
        self._miss_count += 1
        return None

    def put(
        self, tool_name: str, parameters: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """Store result in cache.

        Args:
            tool_name: Name of the tool.
            parameters: Tool parameters (used as cache key).
            result: Tool result to cache.
        """
        cache_key = self._make_key(tool_name, parameters)
        self._cache[cache_key] = result

    def has(self, tool_name: str, parameters: dict[str, Any]) -> bool:
        """Check if result is cached.

        Args:
            tool_name: Name of the tool.
            parameters: Tool parameters.

        Returns:
            True if result is cached.
        """
        cache_key = self._make_key(tool_name, parameters)
        return cache_key in self._cache

    def clear(self) -> None:
        """Clear all cached results."""
        self._cache.clear()
        self._hit_count = 0
        self._miss_count = 0

    def _make_key(self, tool_name: str, parameters: dict[str, Any]) -> str:
        """Create a cache key from tool name and parameters."""
        # Sort parameters for consistent key generation
        sorted_params = sorted(parameters.items())
        param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
        return f"{tool_name}:{param_str}"

    @property
    def stats(self) -> dict[str, int | float]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "hits": self._hit_count,
            "misses": self._miss_count,
            "hit_rate": (
                round(self._hit_count / (self._hit_count + self._miss_count), 2)
                if (self._hit_count + self._miss_count) > 0
                else 0.0
            ),
        }


@dataclass
class DiagnosticContext:
    """Context built from initial artifact exploration.

    Attributes:
        artifact_type: Detected artifact type (error_message, logs, stack_trace, etc.).
        mode: Context mode (online, offline, hybrid).
        confidence: Current confidence level (0.0-1.0).
        evidence_refs: List of evidence window IDs for citation.
        extracted_ids: Dict of Databricks IDs (job_id, cluster_id, etc.).
        patterns: List of matched pattern info dicts.
        suggested_strategies: List of suggested next exploration strategies.
        strategies_executed: List of strategies already executed.
        has_online_capability: Whether ONLINE mode tools can be used.
        was_truncated: Whether the artifact was truncated.
        exploration_state: Full exploration state for multi-step.
        tool_result_cache: Cache for tool results during exploration.
    """

    artifact_type: str | None
    mode: str
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)
    extracted_ids: dict[str, str] = field(default_factory=dict)
    patterns: list[dict[str, Any]] = field(default_factory=list)
    suggested_strategies: list[str] = field(default_factory=list)
    strategies_executed: list[str] = field(default_factory=list)
    has_online_capability: bool = False
    was_truncated: bool = False
    exploration_state: ExplorationState | None = None
    tool_result_cache: ToolResultCache = field(default_factory=ToolResultCache)

    def get_cached_tool_result(
        self, tool_name: str, parameters: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Get cached tool result if available.

        Args:
            tool_name: Name of the tool.
            parameters: Tool parameters.

        Returns:
            Cached result or None.
        """
        return self.tool_result_cache.get(tool_name, parameters)

    def cache_tool_result(
        self, tool_name: str, parameters: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """Cache a tool result for reuse.

        Args:
            tool_name: Name of the tool.
            parameters: Tool parameters.
            result: Tool result to cache.
        """
        self.tool_result_cache.put(tool_name, parameters, result)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "artifact_type": self.artifact_type,
            "mode": self.mode,
            "confidence": self.confidence,
            "evidence_refs": self.evidence_refs,
            "extracted_ids": self.extracted_ids,
            "patterns": self.patterns,
            "suggested_strategies": self.suggested_strategies,
            "strategies_executed": self.strategies_executed,
            "has_online_capability": self.has_online_capability,
            "was_truncated": self.was_truncated,
            "cache_stats": self.tool_result_cache.stats,
        }


class DiagnosticContextBuilder:
    """Builds exploration context from artifacts for prompt injection.

    The context builder runs initial exploration strategies on user-provided
    artifacts to build context that gets injected into the diagnostic agent's
    prompt. This enables "artifact-first" analysis where the LLM receives
    preprocessed information about the artifact before reasoning.

    Example:
        >>> from starboard_server.tools.domain.diagnostic.artifact_detector import ArtifactDetector
        >>> from starboard_server.tools.domain.diagnostic.artifact_explorer import ArtifactExplorer
        >>> from starboard_server.tools.domain.diagnostic.evidence_extractor import EvidenceWindowExtractor
        >>> from starboard_server.tools.domain.diagnostic.context_extractor import DatabricksContextExtractor
        >>>
        >>> explorer = ArtifactExplorer(
        ...     detector=ArtifactDetector(),
        ...     evidence_extractor=EvidenceWindowExtractor(),
        ...     context_extractor=DatabricksContextExtractor(),
        ... )
        >>> builder = DiagnosticContextBuilder(explorer)
        >>>
        >>> artifact = "java.lang.OutOfMemoryError: Java heap space"
        >>> context = builder.build_context(artifact)
        >>> print(context.artifact_type)
        'error_message'
        >>>
        >>> prompt_section = builder.format_for_prompt(context)
        >>> print(prompt_section)
        ## Exploration State
        - Artifact Type: error_message
        - Mode: OFFLINE
        ...
    """

    def __init__(
        self,
        explorer: ArtifactExplorer,
        *,
        initial_strategies: list[ExplorationStrategy] | None = None,
    ) -> None:
        """Initialize the context builder.

        Args:
            explorer: ArtifactExplorer instance with all dependencies.
            initial_strategies: Strategies to run initially. Defaults to
                [DETECT_TYPE, EXTRACT_EVIDENCE, EXTRACT_IDS, MATCH_PATTERNS].
        """
        self._explorer = explorer
        self._initial_strategies = initial_strategies or [
            ExplorationStrategy.DETECT_TYPE,
            ExplorationStrategy.EXTRACT_EVIDENCE,
            ExplorationStrategy.EXTRACT_IDS,
            ExplorationStrategy.MATCH_PATTERNS,
        ]

    @property
    def _has_pattern_matcher(self) -> bool:
        """Check if pattern matcher is available."""
        return self._explorer._pattern_matcher is not None

    def build_context(self, artifact: str) -> DiagnosticContext:
        """Build exploration context from an artifact.

        Runs initial exploration strategies and aggregates results into
        a DiagnosticContext that can be injected into the prompt.

        Args:
            artifact: Raw artifact text (logs, error, code, etc.).

        Returns:
            DiagnosticContext with exploration results.
        """
        # Handle empty artifacts
        if not artifact or not artifact.strip():
            return DiagnosticContext(
                artifact_type=None,
                mode="offline",
                confidence=0.0,
                suggested_strategies=[ExplorationStrategy.DETECT_TYPE.value],
                strategies_executed=[],
            )

        # Truncate if necessary
        was_truncated = len(artifact) > _MAX_ARTIFACT_LENGTH
        if was_truncated:
            artifact = artifact[:_MAX_ARTIFACT_LENGTH]

        # Run initial exploration strategies
        state = ExplorationState(
            artifact_text=artifact,
            history=[],
            current_confidence=0.0,
            mode=None,
        )

        # Track results from each strategy
        artifact_type: str | None = None
        mode = "offline"
        evidence_refs: list[str] = []
        extracted_ids: dict[str, str] = {}
        patterns: list[dict[str, Any]] = []
        suggested_strategies: list[str] = []
        strategies_executed: list[str] = []
        has_online_capability = False
        max_confidence = 0.0

        for strategy in self._initial_strategies:
            # Skip pattern matching if no pattern matcher
            if (
                strategy == ExplorationStrategy.MATCH_PATTERNS
                and not self._has_pattern_matcher
            ):
                continue

            try:
                result = self._explorer.explore(artifact, strategy=strategy)

                # Update state
                from starboard_server.tools.domain.diagnostic.artifact_explorer import (
                    ExplorationStep,
                )

                step = ExplorationStep(
                    strategy=strategy,
                    target=artifact[:100],  # First 100 chars for reference
                    rationale="Initial exploration",
                )
                state.history.append((step, result))
                strategies_executed.append(strategy.value)

                # Track max confidence
                if result.confidence > max_confidence:
                    max_confidence = result.confidence
                    state.current_confidence = max_confidence

                # Extract findings based on strategy
                if strategy == ExplorationStrategy.DETECT_TYPE:
                    artifact_type = result.findings.get("artifact_type")

                elif strategy == ExplorationStrategy.EXTRACT_EVIDENCE:
                    evidence_refs.extend(result.evidence_refs)

                elif strategy == ExplorationStrategy.EXTRACT_IDS:
                    mode = result.findings.get("mode", "offline")
                    has_online_capability = result.findings.get(
                        "has_online_capability", False
                    )
                    ids = result.findings.get("ids", {})
                    extracted_ids.update(ids)

                elif strategy == ExplorationStrategy.MATCH_PATTERNS:
                    patterns = result.findings.get("patterns", [])
                    evidence_refs.extend(result.evidence_refs)

                # Track suggested strategies from last result
                suggested_strategies = [s.value for s in result.next_steps]

            except Exception:
                # Continue with other strategies on error
                continue

        # Update state mode
        state.mode = mode

        return DiagnosticContext(
            artifact_type=artifact_type,
            mode=mode,
            confidence=max_confidence,
            evidence_refs=evidence_refs,
            extracted_ids=extracted_ids,
            patterns=patterns,
            suggested_strategies=suggested_strategies,
            strategies_executed=strategies_executed,
            has_online_capability=has_online_capability,
            was_truncated=was_truncated,
            exploration_state=state,
        )

    def format_for_prompt(self, context: DiagnosticContext) -> str:
        """Format exploration context for prompt injection.

        Creates a markdown-formatted section that can be injected into
        the diagnostic agent's system prompt or as additional context.

        Args:
            context: DiagnosticContext from build_context().

        Returns:
            Formatted string for prompt injection.
        """
        lines: list[str] = []

        lines.append("## Exploration State (Pre-analyzed)")
        lines.append("")

        # Mode and confidence
        lines.append(f"**Mode:** {context.mode.upper()}")
        lines.append(f"**Confidence:** {context.confidence:.0%}")
        if context.artifact_type:
            lines.append(f"**Artifact Type:** {context.artifact_type}")
        lines.append("")

        # Extracted IDs (for ONLINE mode)
        if context.extracted_ids:
            lines.append("**Extracted Databricks IDs:**")
            for id_type, id_value in context.extracted_ids.items():
                lines.append(f"- {id_type}: `{id_value}`")
            lines.append("")

        # Pattern matches
        if context.patterns:
            lines.append("**Matched Patterns:**")
            for pattern in context.patterns[:5]:  # Limit to top 5
                conf = pattern.get("confidence", 0)
                title = pattern.get("title", pattern.get("pattern_id", "Unknown"))
                lines.append(f"- {title} (confidence: {conf:.0%})")
            lines.append("")

        # Evidence references
        if context.evidence_refs:
            lines.append("**Evidence Windows:**")
            for ref in context.evidence_refs[:10]:  # Limit to 10
                lines.append(f"- `{ref}`")
            lines.append("")

        # Suggested next steps
        if context.suggested_strategies:
            lines.append("**Suggested Next Steps:**")
            for strategy in context.suggested_strategies:
                lines.append(f"- {strategy}")
            lines.append("")

        # Strategies executed
        if context.strategies_executed:
            lines.append(
                f"*Strategies executed: {', '.join(context.strategies_executed)}*"
            )

        # Truncation warning
        if context.was_truncated:
            lines.append("")
            lines.append(
                "⚠️ *Artifact was truncated due to size. "
                "Consider requesting specific log sections.*"
            )

        return "\n".join(lines)
