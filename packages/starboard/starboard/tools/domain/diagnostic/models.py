# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Domain models for artifact-first diagnostics.

This module defines the core data structures for the Diagnostic Agent v2:
- Artifact representation (type, content, metadata)
- Detection results (type classification, confidence)
- Evidence windows (extracted snippets for diagnosis)
- Pattern matching structures (signatures, matches)
- Databricks context extraction

Design reference: changes/diagnostic_agent/UNIFIED_DESIGN.md Section 5
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

# =============================================================================
# ARTIFACT TYPE AND LANGUAGE ENUMS
# =============================================================================


class ArtifactType(Enum):
    """Classification of user-provided artifacts.

    Each type has specific detection patterns and processing rules.
    """

    ERROR_MESSAGE = "error_message"
    """Short error message or exception (typically <50 lines)."""

    LOGS = "logs"
    """Application or system logs with timestamps and log levels."""

    STACK_TRACE = "stack_trace"
    """Java/Python/Scala stack trace with exception chain."""

    GC_LOGS = "gc_logs"
    """JVM garbage collection logs with GC events."""

    CODE = "code"
    """Source code (SQL, Python, Scala) with or without errors."""

    MIXED = "mixed"
    """Combination of multiple artifact types."""

    # Large file artifact types (for incremental discovery)
    SPARK_EVENT_LOG = "spark_event_log"
    """Spark event log (JSON-lines with SparkListener* events)."""

    QUERY_PROFILE = "query_profile"
    """Databricks query profile (Liquid format JSON with operator metrics)."""

    EXPLAIN_PLAN = "explain_plan"
    """SQL EXPLAIN plan text output with Physical/Logical plan sections."""

    UNKNOWN = "unknown"
    """Artifact type could not be determined."""


class CodeLanguage(Enum):
    """Detected programming language for code artifacts."""

    SQL = "sql"
    """SQL query (SELECT, INSERT, UPDATE, CREATE, WITH)."""

    PYTHON = "python"
    """Python code (def, import, class)."""

    SCALA = "scala"
    """Scala code (val, var, case class, SparkSession)."""

    UNKNOWN = "unknown"
    """Language could not be determined."""


class ArtifactSource(Enum):
    """Origin of the artifact."""

    CHAT = "chat"
    """User pasted directly in chat."""

    FILE = "file"
    """Uploaded as a file attachment."""

    TOOL = "tool"
    """Retrieved via tool call (get_logs, etc.)."""


# =============================================================================
# ARTIFACT STATISTICS AND METADATA
# =============================================================================


@dataclass(frozen=True)
class ArtifactStats:
    """Statistics about an artifact's content.

    Used for size validation, truncation decisions, and deduplication.
    """

    char_count: int
    """Total character count."""

    line_count: int
    """Total line count."""

    sha256: str
    """SHA-256 hash of normalized content for deduplication."""

    @classmethod
    def from_content(cls, content: str) -> ArtifactStats:
        """Compute stats from content string.

        Args:
            content: The artifact content to analyze.

        Returns:
            ArtifactStats with computed values.
        """
        lines = content.split("\n")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls(
            char_count=len(content),
            line_count=len(lines),
            sha256=content_hash,
        )


@dataclass(frozen=True)
class TruncationInfo:
    """Information about how an artifact was truncated.

    Recorded when size guardrails are applied.
    """

    policy: Literal["head_tail", "error_windows", "uniform"]
    """Truncation strategy used."""

    original_lines: int
    """Original line count before truncation."""

    kept_ranges: tuple[tuple[int, int], ...]
    """Line ranges that were preserved (start, end) tuples."""

    notice: str
    """Human-readable notice about truncation."""


# =============================================================================
# DETECTION RESULT
# =============================================================================


@dataclass(frozen=True)
class DetectionResult:
    """Result of artifact type and language detection.

    Returned by ArtifactDetector.detect().
    """

    artifact_type: ArtifactType
    """Detected artifact type."""

    language: CodeLanguage | None
    """Detected language (for CODE type, None otherwise)."""

    confidence: float
    """Detection confidence (0.0 to 1.0)."""

    signals: tuple[str, ...]
    """Detection signals that contributed to classification.

    Examples: "timestamp_density_high", "stack_trace_pattern", "exit_code_found"
    """


# =============================================================================
# EVIDENCE WINDOW
# =============================================================================


@dataclass(frozen=True)
class EvidenceWindow:
    """A snippet of evidence extracted from an artifact.

    Evidence windows are verbatim extracts with stable IDs for citation.
    The LLM can reference these by ID in its response.
    """

    window_id: str
    """Stable unique identifier for citation (e.g., 'ev_001')."""

    pattern_type: str
    """Type of pattern that triggered extraction.

    Examples: "fatal_exception", "cause_chain", "exit_code", "oom"
    """

    line_start: int
    """Starting line number (1-indexed)."""

    line_end: int
    """Ending line number (1-indexed, inclusive)."""

    content: str
    """Verbatim content of the evidence window."""

    confidence: float
    """Confidence that this window is relevant (0.0 to 1.0)."""


# =============================================================================
# DATABRICKS CONTEXT
# =============================================================================


@dataclass(frozen=True)
class DatabricksContext:
    """Databricks identifiers extracted from an artifact.

    These IDs enable ONLINE mode where we can fetch additional context.
    """

    cluster_id: str | None = None
    """Cluster ID (format: XXXX-XXXXXX-xxxxxxxx)."""

    job_id: int | None = None
    """Job ID (numeric)."""

    run_id: int | None = None
    """Run ID (numeric)."""

    task_run_id: int | None = None
    """Task run ID (numeric)."""

    warehouse_id: str | None = None
    """SQL warehouse ID (16-char hex)."""

    statement_id: str | None = None
    """Query statement ID."""

    pipeline_id: str | None = None
    """DLT pipeline ID (UUID format)."""

    notebook_path: str | None = None
    """Notebook path (/Users/... or /Repos/...)."""

    workspace_url: str | None = None
    """Workspace URL (https://xxx.cloud.databricks.com)."""

    def has_any_id(self) -> bool:
        """Check if any Databricks identifier was extracted.

        Returns:
            True if at least one ID is present.
        """
        return any(
            [
                self.cluster_id,
                self.job_id,
                self.run_id,
                self.task_run_id,
                self.warehouse_id,
                self.statement_id,
                self.pipeline_id,
                self.notebook_path,
                self.workspace_url,
            ]
        )

    def get_mode(self) -> Literal["online", "offline"]:
        """Determine diagnostic mode based on available IDs.

        Returns:
            "online" if IDs are available for tool calls, "offline" otherwise.
        """
        return "online" if self.has_any_id() else "offline"


# =============================================================================
# ARTIFACT SUMMARY
# =============================================================================


@dataclass(frozen=True)
class ArtifactSummary:
    """Token-efficient summary of an artifact.

    Generated by the two-pass summarization process:
    - Pass A: Extractive (verbatim evidence)
    - Pass B: Abstractive (grounded in evidence)
    """

    log_summary: str
    """Short natural language summary (1-2 sentences)."""

    timeline: tuple[tuple[str, str], ...]
    """Sequence of (timestamp, event) tuples."""

    hypotheses: tuple[str, ...]
    """Potential root causes with confidence indicators."""


# =============================================================================
# CANONICAL ARTIFACT
# =============================================================================


@dataclass(frozen=True)
class Artifact:
    """Canonical representation of a user-provided artifact.

    This is the primary data structure flowing through the diagnostic pipeline:
    Detection → Normalization → Guardrails → Evidence Extraction → Summarization

    Attributes:
        artifact_id: Unique identifier for this artifact.
        artifact_type: Classification (ERROR_MESSAGE, LOGS, STACK_TRACE, etc.).
        language: Detected language for code artifacts.
        source: Where the artifact came from (CHAT, FILE, TOOL).
        content_original: Raw user input (preserved for reference).
        content_normalized: Cleaned/formatted content for analysis.
        stats: Size and hash statistics.
        truncation: Truncation info if size limits were applied.
        evidence_windows: Key snippets extracted for diagnosis.
        extracted_ids: Databricks identifiers found in content.
        summary: Token-efficient summary.
    """

    artifact_id: str
    """UUID for this artifact."""

    artifact_type: ArtifactType
    """Detected artifact type."""

    language: CodeLanguage | None
    """Detected language (for CODE type)."""

    source: ArtifactSource
    """Origin of the artifact."""

    content_original: str
    """Raw user input."""

    content_normalized: str
    """Cleaned/formatted content."""

    stats: ArtifactStats
    """Size and hash statistics."""

    truncation: TruncationInfo | None = None
    """Truncation info if applied."""

    evidence_windows: tuple[EvidenceWindow, ...] = field(default_factory=tuple)
    """Extracted evidence snippets."""

    extracted_ids: DatabricksContext = field(default_factory=DatabricksContext)
    """Databricks identifiers from content."""

    summary: ArtifactSummary | None = None
    """Token-efficient summary."""

    @classmethod
    def create(
        cls,
        content: str,
        artifact_type: ArtifactType,
        source: ArtifactSource = ArtifactSource.CHAT,
        language: CodeLanguage | None = None,
    ) -> Artifact:
        """Factory method to create a new artifact.

        Args:
            content: The artifact content.
            artifact_type: Classification of the artifact.
            source: Where the artifact came from.
            language: Detected language (for code artifacts).

        Returns:
            New Artifact instance with generated ID and stats.
        """
        return cls(
            artifact_id=str(uuid.uuid4()),
            artifact_type=artifact_type,
            language=language,
            source=source,
            content_original=content,
            content_normalized=content,  # Normalized later by ArtifactNormalizer
            stats=ArtifactStats.from_content(content),
        )


# =============================================================================
# PATTERN MATCHING MODELS (Week 2)
# =============================================================================


class PatternCategory(Enum):
    """Categories of error patterns."""

    MEMORY = "memory"
    """OOM, GC overhead, heap exhaustion."""

    NETWORK = "network"
    """Shuffle failures, connection timeouts."""

    DATA = "data"
    """Data skew, shuffle spill."""

    CONFIG = "config"
    """Misconfiguration issues."""

    DELTA = "delta"
    """Delta Lake specific issues."""

    UC = "uc"
    """Unity Catalog issues."""

    SQL = "sql"
    """SQL parsing, permission, analysis errors."""


@dataclass(frozen=True)
class PatternSignature:
    """Matching criteria for an error pattern.

    A pattern matches if its signature criteria are met.
    """

    exit_code: int | None = None
    """Exit code to match (e.g., 137, 143)."""

    exception_class: str | None = None
    """Exception class name pattern (regex)."""

    message_pattern: str | None = None
    """Error message pattern (regex)."""


@dataclass(frozen=True)
class Recommendation:
    """A recommended fix for an error pattern."""

    id: str
    """Unique identifier for this recommendation."""

    priority: Literal["high", "medium", "low"]
    """Priority of this recommendation."""

    action: str
    """Short description of the action."""

    implementation: str
    """Code or config to implement the fix."""

    verification: str
    """How to verify the fix worked."""

    tradeoffs: str | None = None
    """Potential tradeoffs or side effects."""


@dataclass(frozen=True)
class ConfidenceFactors:
    """Factors that increase or decrease pattern match confidence."""

    increase: tuple[str, ...] = field(default_factory=tuple)
    """Evidence that increases confidence."""

    decrease: tuple[str, ...] = field(default_factory=tuple)
    """Evidence that decreases confidence."""


@dataclass(frozen=True)
class EvidenceChecklist:
    """Evidence requirements for a pattern match."""

    required: tuple[str, ...]
    """Evidence that must be present for a match."""

    supporting: tuple[str, ...] = field(default_factory=tuple)
    """Evidence that increases confidence but isn't required."""


@dataclass(frozen=True)
class ErrorPattern:
    """Definition of a known error pattern.

    Patterns are matched against artifacts to generate diagnoses.
    """

    pattern_id: str
    """Unique identifier for this pattern."""

    name: str
    """Human-readable name."""

    category: PatternCategory
    """Pattern category."""

    signature: PatternSignature
    """Matching criteria."""

    log_patterns: tuple[str, ...]
    """Regex patterns to match in logs."""

    root_cause: str
    """Explanation of why this happens."""

    symptoms: tuple[str, ...]
    """Observable symptoms."""

    evidence_checklist: EvidenceChecklist
    """Required and supporting evidence."""

    recommendations: tuple[Recommendation, ...]
    """Recommended fixes."""

    confidence_factors: ConfidenceFactors
    """Factors affecting confidence."""

    version: str = "1.0.0"
    """Pattern version for tracking updates."""

    databricks_runtimes: tuple[str, ...] = field(default_factory=tuple)
    """Tested Databricks runtime versions."""

    success_rate: float = 0.0
    """Historical accuracy (0.0 if not tracked)."""


@dataclass(frozen=True)
class PatternMatch:
    """Result of matching an artifact against a pattern.

    Contains the matched pattern, confidence score, and supporting evidence.
    """

    match_id: str
    """Stable identifier for this match (hash of pattern + evidence)."""

    pattern_id: str
    """ID of the matched pattern (e.g., 'java_heap_space')."""

    pattern: ErrorPattern
    """The matched pattern."""

    confidence: float
    """Match confidence (0.0 to 1.0)."""

    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    """Evidence lines that contributed to the match."""

    captures: dict[str, str] = field(default_factory=dict)
    """Captured values from regex named groups."""

    matched_evidence: tuple[str, ...] = field(default_factory=tuple)
    """Evidence that contributed to the match (legacy, use evidence_refs)."""

    missing_evidence: tuple[str, ...] = field(default_factory=tuple)
    """Required evidence that was not found."""


# =============================================================================
# EXIT CODE TRIAGE MODELS (Week 2)
# =============================================================================


@dataclass(frozen=True)
class ExitCodeDiagnosis:
    """Diagnosis result from exit code triage.

    Exit codes tell HOW a process ended, not WHY.
    This structure captures the decoded information and hypotheses.
    """

    exit_code: int
    """The original exit code."""

    signal_number: int | None
    """Signal number if exit_code >= 128 (exit_code - 128)."""

    signal_name: str | None
    """Signal name (SIGKILL, SIGTERM, etc.)."""

    termination_origin: str
    """Classification of why termination occurred.

    Values: "resource_enforcement", "orchestrator_control",
            "user_control", "hard_crash", "unknown"
    """

    hypotheses: tuple[tuple[str, Literal["high", "medium", "low"]], ...]
    """Potential causes with confidence levels.

    Each tuple is (cause_description, confidence).
    """

    evidence_refs: tuple[str, ...]
    """References to evidence windows that support diagnosis."""

    requires_corroboration: bool
    """Whether additional evidence is needed for high confidence."""


# =============================================================================
# DIAGNOSTIC FINGERPRINT MODELS (Week 8 - Handoff Protocol)
# =============================================================================


class PrimarySymptom(Enum):
    """Classification of the primary symptom detected.

    Used for handoff routing and pattern-to-symptom mapping.
    """

    EXECUTOR_LOST = "executor_lost"
    """Spark executor was lost during job execution."""

    OOM = "oom"
    """Out of memory error (Java heap, GC overhead)."""

    PERMISSION = "permission"
    """Access denied or permission-related error."""

    PARSE_ERROR = "parse_error"
    """SQL/code parsing or analysis error."""

    TIMEOUT = "timeout"
    """Query or operation timed out."""

    CONNECTION_ERROR = "connection_error"
    """Network connectivity or connection issues."""

    SERIALIZATION_ERROR = "serialization_error"
    """Task not serializable or serialization failure."""

    DATA_SKEW = "data_skew"
    """Data skew causing performance issues."""

    SHUFFLE_FAILURE = "shuffle_failure"
    """Shuffle fetch failed or shuffle-related error."""

    DRIVER_CRASH = "driver_crash"
    """Spark driver process crashed."""

    DELTA_ERROR = "delta_error"
    """Delta Lake-specific error (concurrent write, corruption)."""

    UC_ERROR = "uc_error"
    """Unity Catalog-related error."""

    UNKNOWN = "unknown"
    """Could not determine primary symptom."""


# Mapping from symptom to default handoff target
_SYMPTOM_HANDOFF_MAP: dict[PrimarySymptom, str] = {
    PrimarySymptom.OOM: "cluster",
    PrimarySymptom.EXECUTOR_LOST: "cluster",
    PrimarySymptom.DRIVER_CRASH: "cluster",
    PrimarySymptom.CONNECTION_ERROR: "cluster",
    PrimarySymptom.DATA_SKEW: "job",
    PrimarySymptom.SHUFFLE_FAILURE: "job",
    PrimarySymptom.SERIALIZATION_ERROR: "job",
    PrimarySymptom.PERMISSION: "uc",
    PrimarySymptom.UC_ERROR: "uc",
    PrimarySymptom.PARSE_ERROR: "query",
    PrimarySymptom.TIMEOUT: "warehouse",
    PrimarySymptom.DELTA_ERROR: "job",
    PrimarySymptom.UNKNOWN: "diagnostic",
}

# Mapping from pattern IDs to symptoms
_PATTERN_TO_SYMPTOM: dict[str, PrimarySymptom] = {
    "java_heap_space": PrimarySymptom.OOM,
    "gc_overhead": PrimarySymptom.OOM,
    "container_killed": PrimarySymptom.OOM,
    "shuffle_fetch_failed": PrimarySymptom.SHUFFLE_FAILURE,
    "shuffle_spill": PrimarySymptom.SHUFFLE_FAILURE,
    "data_skew": PrimarySymptom.DATA_SKEW,
    "executor_lost": PrimarySymptom.EXECUTOR_LOST,
    "task_not_serializable": PrimarySymptom.SERIALIZATION_ERROR,
    "uc_permission_denied": PrimarySymptom.PERMISSION,
    "uc_not_found": PrimarySymptom.UC_ERROR,
    "delta_concurrent_write": PrimarySymptom.DELTA_ERROR,
    "delta_corruption": PrimarySymptom.DELTA_ERROR,
    "python_worker_crash": PrimarySymptom.DRIVER_CRASH,
    "network_throttling": PrimarySymptom.CONNECTION_ERROR,
}


@dataclass
class ExplorationSummary:
    """Summary of the diagnostic exploration process.

    Captures metadata about how the diagnosis was reached.
    """

    steps_completed: int
    """Number of exploration steps executed."""

    final_confidence: float
    """Final confidence level (0.0 to 1.0)."""

    strategies_used: list[str]
    """List of exploration strategies that were executed."""

    patterns_matched: list[str] | None = None
    """Pattern IDs that matched during exploration."""

    tool_calls_made: list[str] | None = None
    """Tool names called during ONLINE exploration."""

    total_duration_ms: int | None = None
    """Total exploration duration in milliseconds."""


@dataclass
class DiagnosticFingerprint:
    """Compact payload for agent handoffs.

    Contains the essential diagnosis information needed by receiving agents.
    This is the output of the diagnostic exploration process.
    """

    primary_symptom: PrimarySymptom
    """The main symptom classification."""

    likely_root_causes: list[str]
    """List of probable root causes in priority order."""

    extracted_context: dict[str, str] = field(default_factory=dict)
    """Databricks IDs and other context extracted from artifacts."""

    evidence_snippets: list[str] = field(default_factory=list)
    """Key evidence excerpts supporting the diagnosis."""

    exploration_summary: ExplorationSummary | None = None
    """Optional summary of the exploration process."""

    recommended_handoff: str | None = None
    """Explicit handoff target (overrides symptom-based default)."""

    def get_handoff_target(self) -> str:
        """Determine the appropriate agent for handoff.

        Returns:
            Agent domain name (cluster, job, query, uc, warehouse, diagnostic).
        """
        if self.recommended_handoff:
            return self.recommended_handoff
        return _SYMPTOM_HANDOFF_MAP.get(self.primary_symptom, "diagnostic")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation suitable for handoff protocol.
        """
        result: dict[str, Any] = {
            "primary_symptom": self.primary_symptom.value,
            "likely_root_causes": self.likely_root_causes,
            "extracted_context": self.extracted_context,
            "evidence_snippets": self.evidence_snippets,
        }
        if self.exploration_summary:
            result["exploration_summary"] = {
                "steps_completed": self.exploration_summary.steps_completed,
                "final_confidence": self.exploration_summary.final_confidence,
                "strategies_used": self.exploration_summary.strategies_used,
                "patterns_matched": self.exploration_summary.patterns_matched,
                "tool_calls_made": self.exploration_summary.tool_calls_made,
                "total_duration_ms": self.exploration_summary.total_duration_ms,
            }
        if self.recommended_handoff:
            result["recommended_handoff"] = self.recommended_handoff
        return result

    @classmethod
    def from_exploration(
        cls,
        matched_patterns: list[str],
        extracted_ids: dict[str, str],
        evidence_refs: list[str],
        confidence: float,
        steps_completed: int,
        strategies_used: list[str],
    ) -> DiagnosticFingerprint:
        """Factory method to create fingerprint from exploration results.

        Args:
            matched_patterns: Pattern IDs that matched.
            extracted_ids: Databricks IDs extracted from artifact.
            evidence_refs: Evidence window references.
            confidence: Final exploration confidence.
            steps_completed: Number of exploration steps.
            strategies_used: Strategies that were executed.

        Returns:
            DiagnosticFingerprint summarizing the exploration.
        """
        # Determine primary symptom from matched patterns
        symptom = PrimarySymptom.UNKNOWN
        for pattern_id in matched_patterns:
            if pattern_id in _PATTERN_TO_SYMPTOM:
                symptom = _PATTERN_TO_SYMPTOM[pattern_id]
                break

        # Build root causes from patterns
        root_causes = matched_patterns if matched_patterns else ["undetermined"]

        # Create exploration summary
        summary = ExplorationSummary(
            steps_completed=steps_completed,
            final_confidence=confidence,
            strategies_used=strategies_used,
            patterns_matched=matched_patterns if matched_patterns else None,
        )

        return cls(
            primary_symptom=symptom,
            likely_root_causes=root_causes,
            extracted_context=extracted_ids,
            evidence_snippets=evidence_refs,
            exploration_summary=summary,
        )


# =============================================================================
# AGENT-DRIVEN ARTIFACT EXPLORATION MODELS
# =============================================================================


@dataclass(frozen=True)
class ArtifactMetadata:
    """Lightweight metadata about an available artifact for agent context.

    Passed to the agent instead of full artifact content, enabling
    intent-driven exploration via the explore_artifact tool.

    Attributes:
        attachment_id: Cache key for retrieving full content.
        filename: Original filename.
        size_bytes: File size in bytes.
        detected_type: Detected artifact type.
        type_confidence: Confidence in type detection (0-1).
        preview: First ~500 chars for quick context.
    """

    attachment_id: str
    """Cache key for retrieving full content."""

    filename: str
    """Original filename."""

    size_bytes: int
    """File size in bytes."""

    detected_type: ArtifactType
    """Detected artifact type (query_profile, spark_event_log, etc.)."""

    type_confidence: float
    """Confidence in type detection (0.0 to 1.0)."""

    preview: str
    """First ~500 chars for quick context."""

    def to_dict(self) -> dict:
        """Convert to dictionary for context serialization.

        Returns:
            Dictionary representation for agent context.
        """
        return {
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "detected_type": self.detected_type.value,
            "type_confidence": self.type_confidence,
            "preview": self.preview,
        }


@dataclass(frozen=True)
class ExplorationResult:
    """Result from intent-aware artifact exploration.

    Returned by the explore_artifact tool after extracting
    relevant sections based on the user's focus query.

    Attributes:
        focus_query: The focus query that was used.
        content: Extracted content based on focus (markdown formatted).
        evidence_count: Number of evidence items found.
        sections_found: List of section types found (joins, shuffles, etc.).
        has_more: Whether more detail is available with narrower focus.
        suggested_followups: Suggested focus queries for deeper exploration.
    """

    focus_query: str
    """The focus query that was used for extraction."""

    content: str
    """Extracted content based on focus (markdown formatted)."""

    evidence_count: int
    """Number of evidence items found."""

    sections_found: tuple[str, ...]
    """List of section types found (joins, shuffles, scans, etc.)."""

    has_more: bool
    """Whether more detail is available with exhaustive detail level."""

    suggested_followups: tuple[str, ...]
    """Suggested focus queries for deeper exploration."""

    def to_dict(self) -> dict:
        """Convert to dictionary for tool response.

        Returns:
            Dictionary representation for tool output.
        """
        return {
            "focus_query": self.focus_query,
            "content": self.content,
            "evidence_count": self.evidence_count,
            "sections_found": list(self.sections_found),
            "has_more": self.has_more,
            "suggested_followups": list(self.suggested_followups),
        }
