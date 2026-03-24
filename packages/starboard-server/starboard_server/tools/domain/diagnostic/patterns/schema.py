# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Pydantic v2 schema models for YAML pattern validation.

This module defines the schema for error patterns loaded from YAML files.
Patterns are validated at startup and fail-fast on invalid definitions.

Design reference:
- changes/diagnostic_agent/IMPLEMENTATION_CHECKLIST.md
- changes/diag_patterns/merged.md
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Severity(str, Enum):
    """Pattern severity level for triage prioritization.

    Values guide the urgency of remediation:
    - CRITICAL: Job fails immediately or data-loss/corruption risk
    - HIGH: Job likely to fail or significant impact
    - MEDIUM: Job may complete but degraded
    - LOW: Minor issue or informative signal
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Category(str, Enum):
    """Pattern category for taxonomy grouping.

    Categories match the diagnostic domain taxonomy from merged.md.
    """

    MEMORY = "memory"
    """JVM heap/metaspace/direct buffers, GC issues, OOM kills."""

    EXECUTION = "execution"
    """Executor lost, stage retry, task serialization, spot preemption."""

    SHUFFLE = "shuffle"
    """Fetch failed, connection reset, heartbeat timeout, RPC issues."""

    NETWORK = "network"
    """DNS, SSL/TLS, throttling, general network failures."""

    SQL = "sql"
    """Analysis exceptions, missing table/view, type mismatch, parse errors."""

    STORAGE = "storage"
    """Cloud storage auth/throttling, disk space, missing files."""

    DELTA = "delta"
    """Concurrent write conflicts, protocol mismatch, schema issues."""

    UC = "uc"
    """Unity Catalog permission denied, missing catalog/schema."""

    STREAMING = "streaming"
    """Streaming query exceptions, Kafka offsets, state store issues."""

    DATA_QUALITY = "data_quality"
    """Corrupt records, encoding errors, datetime parsing, overflows."""

    CLUSTER = "cluster"
    """Startup failures, init script errors, autoscale issues."""

    PERFORMANCE = "performance"
    """Skew, spill storms, driver bottlenecks (signal-based)."""


class ResponsibilityScope(str, Enum):
    """Who is responsible for remediation.

    Tags each pattern to steer remediation towards the right owner.
    """

    USER_CODE = "user_code"
    """Fix code, schema assumptions, UDF handling, query semantics."""

    CONFIGURATION = "configuration"
    """Spark/DBR/job/cluster config tuning, resource sizing."""

    INFRASTRUCTURE = "infrastructure"
    """Cloud outages/capacity/throttling, network/DNS/certs, spot interruptions."""


class PatternCapture(BaseModel):
    """Named capture group definition for regex matches.

    Captures allow extracting structured data from log lines.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Capture group name (e.g., 'executor_id')")
    description: str = Field(default="", description="What this capture represents")


class RecommendationYAML(BaseModel):
    """Remediation recommendation from YAML.

    Converted to internal Recommendation model at load time.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique recommendation ID")
    priority: Annotated[str, Field(pattern=r"^(high|medium|low)$")] = Field(
        ..., description="Priority: high, medium, low"
    )
    action: str = Field(..., description="Short description of action")
    implementation: str = Field(default="", description="Code or config to implement")
    verification: str = Field(default="", description="How to verify the fix")
    tradeoffs: str | None = Field(default=None, description="Potential tradeoffs")


class ConfidenceFactorsYAML(BaseModel):
    """Factors that adjust pattern match confidence.

    Both increase and decrease factors are lists of evidence descriptions.
    """

    model_config = ConfigDict(frozen=True)

    increase: list[str] = Field(
        default_factory=list,
        description="Evidence that increases confidence",
    )
    decrease: list[str] = Field(
        default_factory=list,
        description="Evidence that decreases confidence (negative signals)",
    )


class EvidenceChecklistYAML(BaseModel):
    """Evidence requirements for pattern matching.

    Required evidence must be present; supporting evidence increases confidence.
    """

    model_config = ConfigDict(frozen=True)

    required: list[str] = Field(
        default_factory=list,
        description="Evidence that must be present",
    )
    supporting: list[str] = Field(
        default_factory=list,
        description="Evidence that increases confidence",
    )


class PatternYAML(BaseModel):
    """Complete error pattern definition loaded from YAML.

    This is the source-of-truth schema for pattern definitions.
    Validated at startup; invalid patterns cause fail-fast.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    id: str = Field(
        ...,
        description="Stable identifier (e.g., 'exit_code_137')",
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    name: str = Field(..., description="Human-readable name")

    # Classification
    category: Category = Field(..., description="Pattern category")
    severity: Severity = Field(..., description="Severity level")
    responsibility: ResponsibilityScope = Field(..., description="Who should fix this")

    # Matching criteria
    keywords: list[str] = Field(
        ...,
        min_length=1,
        description="Fast pre-filter keywords (stable tokens)",
    )
    regex_patterns: list[str] = Field(
        default_factory=list,
        description="Regex patterns for matching (case-insensitive)",
    )
    exit_code: int | None = Field(
        default=None, description="Exit code to match (e.g., 137)"
    )
    exception_class: str | None = Field(
        default=None, description="Exception class pattern (regex)"
    )
    message_pattern: str | None = Field(
        default=None, description="Error message pattern (regex)"
    )

    # Captures for structured extraction
    captures: dict[str, str] = Field(
        default_factory=dict,
        description="Named capture groups: name -> description",
    )

    # Root cause and remediation
    root_cause: str = Field(..., description="Why this happens")
    symptoms: list[str] = Field(default_factory=list, description="Observable symptoms")
    root_causes: list[str] = Field(
        default_factory=list, description="Alternative root cause hypotheses"
    )
    remediation: list[str] = Field(
        default_factory=list, description="Short remediation steps"
    )
    recommendations: list[RecommendationYAML] = Field(
        default_factory=list, description="Detailed recommendations"
    )

    # Documentation
    docs: list[str] = Field(
        default_factory=list, description="Databricks/Spark docs links"
    )

    # Evidence and confidence
    evidence_checklist: EvidenceChecklistYAML = Field(
        default_factory=EvidenceChecklistYAML,
        description="Required and supporting evidence",
    )
    confidence_factors: ConfidenceFactorsYAML = Field(
        default_factory=ConfidenceFactorsYAML,
        description="Confidence adjustment factors",
    )

    # Pattern relationships
    related_patterns: list[str] = Field(
        default_factory=list,
        description="Related pattern IDs for enrichment",
    )

    # Metadata
    version: str = Field(default="1.0.0", description="Pattern version")
    databricks_runtimes: list[str] = Field(
        default_factory=list, description="Tested DBR versions"
    )

    @field_validator("regex_patterns", mode="after")
    @classmethod
    def validate_regex_patterns(cls, v: list[str]) -> list[str]:
        """Validate that all regex patterns compile."""
        for i, pattern in enumerate(v):
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex pattern at index {i}: {pattern!r} - {e}"
                ) from e
        return v

    @field_validator("exception_class", mode="after")
    @classmethod
    def validate_exception_class_regex(cls, v: str | None) -> str | None:
        """Validate that exception_class pattern compiles."""
        if v is not None:
            try:
                re.compile(v, re.IGNORECASE)
            except re.error as e:
                raise ValueError(f"Invalid exception_class regex: {v!r} - {e}") from e
        return v

    @field_validator("message_pattern", mode="after")
    @classmethod
    def validate_message_pattern_regex(cls, v: str | None) -> str | None:
        """Validate that message_pattern compiles."""
        if v is not None:
            try:
                re.compile(v, re.IGNORECASE)
            except re.error as e:
                raise ValueError(f"Invalid message_pattern regex: {v!r} - {e}") from e
        return v

    @model_validator(mode="after")
    def validate_has_matching_criteria(self) -> PatternYAML:
        """Ensure pattern has at least one matching criterion."""
        has_criteria = any(
            [
                self.regex_patterns,
                self.exit_code is not None,
                self.exception_class,
                self.message_pattern,
            ]
        )
        if not has_criteria:
            raise ValueError(
                f"Pattern '{self.id}' must have at least one matching criterion "
                "(regex_patterns, exit_code, exception_class, or message_pattern)"
            )
        return self


class PatternCatalogYAML(BaseModel):
    """Root schema for pattern catalog YAML files.

    A catalog file contains multiple patterns.
    """

    model_config = ConfigDict(frozen=True)

    version: str = Field(default="1.0.0", description="Catalog schema version")
    patterns: list[PatternYAML] = Field(
        ..., min_length=1, description="List of pattern definitions"
    )

    @model_validator(mode="after")
    def validate_unique_pattern_ids(self) -> PatternCatalogYAML:
        """Ensure all pattern IDs are unique within the catalog."""
        ids = [p.id for p in self.patterns]
        duplicates = [id_ for id_ in ids if ids.count(id_) > 1]
        if duplicates:
            raise ValueError(f"Duplicate pattern IDs found: {set(duplicates)}")
        return self
