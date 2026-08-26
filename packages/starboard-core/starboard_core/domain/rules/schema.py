# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pydantic schema for workload-review rule YAML (Phase-1 D3).

Seed rules are **data only** — this schema validates them fail-fast at load
time. It intentionally ships **no engine**: the ``RuleRegistry`` and reviewer
flow are Phase-3 (D1). The shape is harvested (paraphrased) from the Isaac
``/review`` rule frontmatter (name / short_description / rationale / severity /
bad-good / suggested-fix) and the ``databricks-elt-review`` per-domain
checklists.

Kernel-clean: pure pydantic, no ``databricks-sdk`` / ``openai`` / ``fastapi`` /
``mcp``. Mirrors the style of
``starboard.tools.domain.diagnostic.patterns.schema``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from starboard_core.domain.models.finding import Effort, Severity


class Rule(BaseModel):
    """A single workload-review rule definition (loaded from YAML).

    Carries the default ``severity`` / ``default_effort`` / ``default_impact``
    that the shared scorer consumes when the rule produces a
    :class:`~starboard_core.domain.models.finding.Finding`.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    id: str = Field(
        ...,
        description="Stable identifier (e.g. 'select_star_projection')",
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    name: str = Field(..., description="Human-readable name", min_length=1)
    category: str = Field(
        ..., description="Domain category (query, cluster, warehouse, uc, ...)"
    )

    # Description / justification (Isaac /review frontmatter)
    short_description: str = Field(
        ..., description="One-line description of the check", min_length=1
    )
    rationale: str = Field(
        ..., description="Why this matters — used to judge edge cases", min_length=1
    )

    # Classification / scoring inputs
    severity: Severity = Field(
        ..., description="Default severity for findings this rule produces"
    )
    default_effort: Effort = Field(
        ..., description="Default remediation effort (XS-XL)"
    )
    default_impact: int = Field(
        ..., ge=1, le=5, description="Default impact multiplier (1-5)"
    )

    # Bad/Good pattern + fix (Isaac /review body)
    bad: str | None = Field(
        default=None, description="The anti-pattern / 'bad' example"
    )
    good: str | None = Field(
        default=None, description="The preferred / 'good' example"
    )
    suggested_fix: str = Field(
        ..., description="Recommended remediation", min_length=1
    )

    # Detection hints (free text in Phase 1 — no engine wires these yet)
    detect: str | None = Field(
        default=None, description="How to detect the condition (heuristic / signal)"
    )
    evidence_query: str | None = Field(
        default=None,
        description=(
            "Name of a query-pack entry that supplies evidence. Free-text in "
            "Phase 1; the Phase-3 engine resolves it against the query packs."
        ),
    )

    # Metadata / governance
    source: str | None = Field(
        default=None,
        description="Public reference (nullable; no internal go/ links)",
    )
    enabled: bool = Field(default=True, description="Whether the rule is active")


class RuleSet(BaseModel):
    """Root schema for a rule YAML file — a domain-scoped set of rules."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(default="1.0.0", description="Ruleset schema version")
    domain: str = Field(..., description="Domain this ruleset covers", min_length=1)
    rules: list[Rule] = Field(
        ..., min_length=1, description="One or more rule definitions"
    )

    @model_validator(mode="after")
    def validate_unique_rule_ids(self) -> RuleSet:
        """Ensure all rule IDs are unique within the ruleset."""
        ids = [r.id for r in self.rules]
        duplicates = sorted({id_ for id_ in ids if ids.count(id_) > 1})
        if duplicates:
            raise ValueError(f"Duplicate rule IDs found: {duplicates}")
        return self
