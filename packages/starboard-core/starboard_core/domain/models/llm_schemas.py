# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pydantic V2 models for LLM response validation.

This module defines validated schemas for all LLM interactions to ensure
type safety and catch malformed responses early.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanIntent(BaseModel):
    """Individual intent within an optimization plan."""

    intent: str = Field(..., description="Intent identifier")
    reason: str = Field(default="", description="Reasoning for this intent")


class InputClassification(BaseModel):
    """Classification of the user-provided input."""

    input_type: Literal[
        "job_id", "job_name", "source_code", "statement_id", "sql", "undetermined"
    ] = Field(..., description="Type of input provided by user")
    target: str = Field(
        ...,
        description="The actual target value that was classified (ID, name, or SQL/code text)",
    )
    confidence: Literal["low", "medium", "high"] = Field(
        ..., description="Confidence level of classification"
    )
    reasoning: str = Field(
        ..., description="Brief explanation of classification decision"
    )


class OptimizationPlan(BaseModel):
    """LLM-generated optimization plan with intents."""

    goal: str = Field(..., description="Optimization goal")
    mode: str = Field(..., description="Optimization mode")
    input_classification: InputClassification = Field(
        ..., description="Classification of the user-provided input"
    )
    intents: list[PlanIntent] = Field(..., description="List of optimization intents")


class CriticVerdict(BaseModel):
    """LLM critique of an optimization plan."""

    status: Literal["ok", "revise", "reject"] = Field(..., description="Verdict status")
    reason: str = Field(..., description="Reasoning for the verdict")
    revised_intents: list[PlanIntent] | None = Field(
        default=None, description="Revised intents if status is revise"
    )


class TableReference(BaseModel):
    """Extracted table reference from code."""

    raw: str = Field(..., description="Raw table reference string")
    catalog: str | None = Field(default=None, description="Catalog name")
    schema_name: str | None = Field(
        default=None, description="Schema name", alias="schema"
    )
    table: str = Field(..., description="Table name")
    type: str = Field(
        default="table",
        description="Table type: table, system_table,view, temp_table, temp_view, or cte",
    )
    is_source: bool = Field(default=False, description="Is this a source table")
    is_destination: bool = Field(
        default=False, description="Is this a destination table"
    )

    model_config = {"populate_by_name": True}


class TableExtraction(BaseModel):
    """LLM extraction of table references from code."""

    language: str = Field(..., description="Detected programming language")
    tables: list[TableReference] = Field(..., description="Extracted table references")


class CodeHotspot(BaseModel):
    """Code issue identified by LLM."""

    artifact: str = Field(..., description="Artifact name (file, function, etc.)")
    line_range: str = Field(default="", description="Line range where issue occurs")
    issue: str = Field(..., description="Description of the issue")
    signal: list[str] = Field(
        default_factory=list, description="Signals indicating the issue"
    )
    evidence: str = Field(default="", description="Evidence supporting the issue")
    risk: str = Field(default="medium", description="Risk level: low, medium, high")
    fix_strategy: str = Field(..., description="Strategy to fix the issue")
    snippet_before: str = Field(default="", description="Code before fix")
    snippet_after: str = Field(default="", description="Code after fix")


class CodeAnalysis(BaseModel):
    """LLM code analysis results."""

    hotspots: list[CodeHotspot] = Field(..., description="Identified code issues")
    notes: list[str] = Field(default_factory=list, description="Additional notes")


class ComputeMisconfiguration(BaseModel):
    """Compute configuration issue."""

    setting: str = Field(..., description="Configuration setting name")
    observed: str = Field(default="", description="Observed value")
    impact: str = Field(default="", description="Impact description")
    recommendation: str = Field(..., description="Recommended fix")


class ComputeRightSizing(BaseModel):
    """Compute right-sizing recommendation."""

    current: str = Field(default="", description="Current configuration")
    suggested: str = Field(..., description="Suggested configuration")
    justification: str = Field(..., description="Justification for change")


class ComputeAnalysis(BaseModel):
    """LLM compute configuration analysis."""

    misconfigs: list[ComputeMisconfiguration] = Field(
        default_factory=list, description="Configuration issues"
    )
    right_sizing: ComputeRightSizing | None = Field(
        default=None, description="Right-sizing recommendations"
    )


class LayoutFinding(BaseModel):
    """Data layout issue finding."""

    object: str = Field(..., description="Table or data object name", alias="object")
    symptom: str = Field(default="", description="Symptom observed")
    evidence: str = Field(default="", description="Supporting evidence")
    recommendation: str = Field(..., description="Recommended action")

    model_config = {"populate_by_name": True}


class DataAnalysis(BaseModel):
    """LLM data layout analysis."""

    layout_findings: list[LayoutFinding] = Field(..., description="Layout issues found")
    io_optimizations: list[str] = Field(
        default_factory=list, description="I/O optimization suggestions"
    )
    risk_items: list[str] = Field(
        default_factory=list, description="Risk items to note"
    )


class RecommendationItem(BaseModel):
    """Prioritized recommendation."""

    title: str = Field(..., description="Recommendation title")
    category: Literal["code", "cluster", "data"] = Field(..., description="Category")
    changes: list[str] = Field(..., description="Required changes")
    benefit: int = Field(..., ge=0, le=5, description="Benefit score (0-5)")
    confidence: int = Field(..., ge=0, le=3, description="Confidence level (0-3)")
    risk: int = Field(..., ge=0, le=3, description="Risk level (0-3)")
    owner_suggested: str = Field(default="", description="Suggested owner")


class Synthesis(BaseModel):
    """LLM synthesis of prioritized recommendations."""

    prioritized: list[RecommendationItem] = Field(
        ..., description="Prioritized recommendations"
    )


class IntentClassification(BaseModel):
    """LLM intent classification result."""

    intent: str = Field(..., description="Classified intent or 'unknown'")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    reasoning: str = Field(..., description="Classification reasoning")


class ImpactEstimate(BaseModel):
    """Impact estimate for a recommendation."""

    query_time_pct: float = Field(..., description="Query time impact percentage")
    data_read_pct: float = Field(default=0.0, description="Data read impact percentage")
    shuffle_pct: float = Field(default=0.0, description="Shuffle impact percentage")
    cost_pct: float = Field(default=0.0, description="Cost impact percentage")
    confidence: Literal["low", "medium", "high"] = Field(
        ..., description="Confidence level"
    )


class EffortEstimate(BaseModel):
    """Effort estimate for a recommendation."""

    level: Literal["low", "medium", "high"] = Field(..., description="Effort level")
    estimate_hours: float | None = Field(default=None, description="Estimated hours")


class ReferenceMaterial(BaseModel):
    """Reference material link."""

    title: str = Field(..., description="Reference title")
    url: str = Field(default="", description="Reference URL")
    cloud: str = Field(default="", description="Cloud provider")


class CodeLineRef(BaseModel):
    """Code line reference."""

    object: str = Field(..., description="Object name", alias="object")
    line: int = Field(..., description="Line number")

    model_config = {"populate_by_name": True}


class Proofs(BaseModel):
    """Evidence supporting a finding."""

    evidence: list[str] = Field(default_factory=list, description="Evidence items")
    code_line_refs: list[CodeLineRef] = Field(
        default_factory=list, description="Code line references"
    )
    references: list[ReferenceMaterial] = Field(
        default_factory=list, description="Reference materials"
    )


class Fix(BaseModel):
    """Fix suggestion (unified for query and job optimization)."""

    type: Literal[
        "SQL_REWRITE",
        "DDL_DML",
        "CONFIG_CHANGE",
        "PROCESS_CHANGE",
        "CODE_REWRITE",
        "CLUSTER_TUNING",
        "DATA_OPTIMIZATION",
    ] = Field(..., description="Fix type")
    snippet: str = Field(..., description="Code snippet")
    notes: str = Field(default="", description="Additional notes")


class Finding(BaseModel):
    """Query or job optimization finding (unified schema v1/v2).

    Supports all agent domains including UC-specific categories:
    - LINEAGE: Data lineage findings (UC Agent)
    - POLICY: Access control / governance findings (UC Agent)
    - STORAGE: Storage optimization findings (UC Agent)
    """

    id: str = Field(..., description="Finding identifier")
    category: Literal[
        # Core categories (all agents)
        "QUERY",
        "TABLE",
        "WAREHOUSE",
        "JOB_CONFIG",
        "CODE",
        "CLUSTER",
        "DATA",
        "RUNTIME",
        "SCHEMA",
        "RESOURCE",
        # UC-specific categories
        "LINEAGE",  # Data lineage findings
        "POLICY",  # Access control / governance
        "STORAGE",  # Storage optimization (OPTIMIZE/VACUUM)
    ] = Field(..., description="Category")
    title: str = Field(..., description="Finding title")
    recommendation: str = Field(..., description="Recommendation text")
    fixes: list[Fix] = Field(default_factory=list, description="Fix suggestions")
    proofs: Proofs = Field(..., description="Supporting evidence (nested structure)")
    impact_estimate: ImpactEstimate = Field(..., description="Impact estimate")
    effort: EffortEstimate = Field(..., description="Effort estimate")
    risks: list[str] = Field(default_factory=list, description="Risk items")
    rank: int = Field(..., description="Priority rank")


class QueryRewrite(BaseModel):
    """Query rewrite suggestion."""

    applicable: bool = Field(..., description="Is rewrite applicable")
    sql: str = Field(default="", description="Rewritten SQL")
    notes: str = Field(default="", description="Rewrite notes")


class CurrentState(BaseModel):
    """Current system state (supports all domains)."""

    cloud_provider: str = Field(..., description="Cloud provider")
    runtime_version: str = Field(default="", description="Runtime version")
    # Query/Warehouse domain fields
    warehouse_tier: str = Field(default="", description="Warehouse tier")
    warehouse_size: str = Field(default="", description="Warehouse size")
    # Job/Cluster domain fields
    cluster_type: str = Field(default="", description="Cluster type")
    cluster_size: str = Field(default="", description="Cluster size")
    # Table domain fields
    table_format: str = Field(
        default="", description="Table format (Delta, Parquet, etc.)"
    )
    # Compute domain fields
    resource_type: str = Field(
        default="", description="Resource type (Cluster, Warehouse)"
    )
    resource_size: str = Field(default="", description="Resource size configuration")
    # Common
    key_symptoms: list[str] = Field(default_factory=list, description="Key symptoms")


class Summary(BaseModel):
    """Analysis summary."""

    overview: str = Field(..., description="Overview text")
    current_state: CurrentState = Field(..., description="Current state")


class Analysis(BaseModel):
    """Complete analysis results."""

    findings: list[Finding] = Field(..., description="Analysis findings")
    query_rewrite: QueryRewrite | None = Field(
        None, description="Query rewrite suggestion (query domain only)"
    )


class NextStepAction(BaseModel):
    """Detailed next step action for interactive conversation flow.

    Used by all agent types to present structured, actionable options to users.
    This format enables the routing system to handle cross-domain handoffs,
    tool calls, and continuation within the same agent.

    Attributes:
        id: Unique identifier for this step
        number: Display number for user selection (1-9)
        title: Short, actionable title (3-7 words)
        description: Longer explanation of what this action does
        action_type: Type of action (continue, route, tool_call)
        target_agent: Target agent ID for routing (if action_type=route)
        tool_name: Tool name for tool calls (if action_type=tool_call)
        parameters: Parameters to pass to target agent/tool

    Example:
        >>> step = NextStepAction(
        ...     id="analyze_table_1",
        ...     number=1,
        ...     title="Analyze table optimization opportunities",
        ...     description="Deep dive into table partitioning and statistics",
        ...     action_type="route",
        ...     target_agent="uc",
        ...     tool_name=None,
        ...     parameters={"table_names": ["sales", "customers"]}
        ... )
    """

    id: str = Field(..., description="Unique identifier for this step", min_length=1)
    number: int = Field(
        ..., description="Display number for user selection", ge=1, le=9
    )
    title: str = Field(
        ..., description="Short, actionable title", min_length=1, max_length=100
    )
    description: str | None = Field(
        None, description="Longer explanation of the action"
    )
    action_type: Literal["continue", "route", "tool_call"] = Field(
        ..., description="Type of action (continue, route, tool_call)"
    )
    target_agent: str | None = Field(None, description="Target agent ID for routing")
    tool_name: str | None = Field(None, description="Tool name for tool calls")
    parameters: dict[str, Any] | None = Field(None, description="Action parameters")


class OptimizerAdvisorReport(BaseModel):
    """Complete optimization advisor report for all domains (query, job, table, compute, diagnostic)."""

    summary: Summary = Field(..., description="Report summary")
    analysis: Analysis = Field(..., description="Analysis results")
    next_steps: list[NextStepAction] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="1-3 suggested next actions for the conversation (consider tools not used, top N slowest queries/jobs, etc.)",
    )


# Backward compatibility aliases
QueryAdvisorReport = OptimizerAdvisorReport
NextStep = NextStepAction
