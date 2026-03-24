# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Declarative domain intent configuration for scoring-based routing.

This module defines what each domain agent handles using a declarative
configuration that enables scoring-based routing instead of sequential
rule matching.

Architecture:
    - Each domain defines its intent patterns declaratively
    - Scoring system evaluates all domains simultaneously
    - Highest score wins (no sequence dependency)
    - Compound keywords naturally handle specificity

See docs/INTENT_ROUTER.md for detailed documentation.
"""

import re
from dataclasses import dataclass, field


def _word_match(keyword: str, text: str) -> bool:
    """Check if keyword appears as a whole word in text.

    Prevents "price" from matching "cprice_main".
    """
    # Use word boundary matching
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


@dataclass(frozen=True)
class CompoundPattern:
    """
    A compound pattern requiring multiple keywords to match.

    Compound patterns score higher than simple keywords because they're
    more specific. For example, ("warehouse", "chargeback") is more
    specific than just "report".

    Attributes:
        keywords: Tuple of keywords that must ALL be present
        weight: Base weight when all keywords match (0.0-1.0)
    """

    keywords: tuple[str, ...]
    weight: float = 0.8

    def matches(self, text: str) -> bool:
        """Check if all keywords are present in text as whole words."""
        return all(_word_match(kw, text) for kw in self.keywords)

    def score(self, text: str) -> float:
        """Calculate score for this pattern."""
        if self.matches(text):
            # More keywords = higher score (specificity bonus)
            return self.weight * (1 + 0.1 * len(self.keywords))
        return 0.0


@dataclass
class DomainIntent:
    """
    Intent configuration for a domain agent.

    Attributes:
        domain: Domain identifier (e.g., "warehouse", "analytics")
        description: Human-readable description of what the domain handles
        simple_keywords: Single keywords that suggest this domain
        compound_patterns: Multi-keyword patterns (higher priority)
        exclusive_patterns: Patterns that exclusively match this domain
        identifier_types: ID types that strongly suggest this domain
        specificity: Tiebreaker - higher values win ties (default: 1)
        base_confidence: Confidence level for matches (default: 0.9)
    """

    domain: str
    description: str
    simple_keywords: list[str] = field(default_factory=list)
    compound_patterns: list[CompoundPattern] = field(default_factory=list)
    exclusive_patterns: list[str] = field(default_factory=list)
    identifier_types: list[str] = field(default_factory=list)
    specificity: int = 1
    base_confidence: float = 0.9


# =============================================================================
# DOMAIN INTENT DEFINITIONS
# =============================================================================

DOMAIN_INTENTS: dict[str, DomainIntent] = {
    # =========================================================================
    # QUERY AGENT - SQL Query Optimization
    # =========================================================================
    "query": DomainIntent(
        domain="query",
        description="SQL query optimization, query plan analysis, execution tuning",
        simple_keywords=[
            "query",
            "sql",
            "select",
            "statement",
            "explain",
            "plan",
        ],
        compound_patterns=[
            CompoundPattern(("query", "optimize"), 0.9),
            CompoundPattern(("query", "slow"), 0.9),
            CompoundPattern(("sql", "performance"), 0.9),
            CompoundPattern(("query", "plan"), 0.9),
            CompoundPattern(("execution", "plan"), 0.9),
        ],
        exclusive_patterns=[
            "statement_id",
            "query plan",
            "explain plan",
        ],
        identifier_types=["statement_id"],
        specificity=2,
        base_confidence=0.95,
    ),
    # =========================================================================
    # JOB AGENT - Databricks Job Optimization
    # =========================================================================
    "job": DomainIntent(
        domain="job",
        description="Databricks job optimization, task performance, workflow tuning",
        simple_keywords=[
            "job",
            "workflow",
            "task",
            "notebook",
            "pipeline",
            "etl",
            "schedule",
        ],
        compound_patterns=[
            CompoundPattern(("job", "optimize"), 0.9),
            CompoundPattern(("job", "slow"), 0.9),
            CompoundPattern(("job", "failed"), 0.9),
            CompoundPattern(("job", "performance"), 0.9),
            CompoundPattern(("workflow", "optimize"), 0.9),
        ],
        exclusive_patterns=[
            "job_id",
            "job run",
            "job failure",
        ],
        identifier_types=["job_id"],
        specificity=2,
        base_confidence=0.95,
    ),
    # =========================================================================
    # WAREHOUSE AGENT - SQL Warehouse Portfolio Optimization
    # Specificity: 3 (highest) - beats analytics for warehouse-specific cost
    # =========================================================================
    "warehouse": DomainIntent(
        domain="warehouse",
        description="SQL warehouse portfolio optimization, health, SLO, chargeback",
        simple_keywords=[
            "warehouse",
            "warehouses",
            "sql warehouse",
        ],
        compound_patterns=[
            # Chargeback - warehouse-specific cost attribution
            CompoundPattern(("warehouse", "chargeback"), 0.95),
            CompoundPattern(("chargeback", "warehouse"), 0.95),
            CompoundPattern(("generate", "chargeback"), 0.9),
            CompoundPattern(("chargeback", "report"), 0.9),
            # Portfolio analysis
            CompoundPattern(("warehouse", "portfolio"), 0.95),
            CompoundPattern(("warehouse", "fleet"), 0.95),
            # NOTE: Lowered confidence for generic warehouse queries
            # to allow analytics agent to handle general cost questions
            # when "cost"/"spend"/"expensive" keywords are also present
            CompoundPattern(
                ("show", "warehouse"), 0.65
            ),  # Lowered to allow analytics to win for cost queries
            CompoundPattern(
                ("list", "warehouse"), 0.75
            ),  # Keep higher for non-cost queries
            # Health and monitoring
            CompoundPattern(("warehouse", "health"), 0.95),
            CompoundPattern(("warehouse", "status"), 0.9),
            # SLO management
            CompoundPattern(("warehouse", "slo"), 0.95),
            CompoundPattern(("slo", "compliance"), 0.9),
            # Topology and optimization
            CompoundPattern(("warehouse", "topology"), 0.95),
            CompoundPattern(("warehouse", "overlap"), 0.95),
            CompoundPattern(("warehouse", "optimize"), 0.9),
            CompoundPattern(("optimize", "warehouse"), 0.9),
            # Fingerprinting
            CompoundPattern(("warehouse", "fingerprint"), 0.95),
            # Serverless analysis
            CompoundPattern(("serverless", "warehouse"), 0.9),
            CompoundPattern(("warehouse", "serverless"), 0.9),
            # Rightsizing
            CompoundPattern(("warehouse", "rightsize"), 0.9),
            CompoundPattern(("rightsize", "warehouse"), 0.9),
        ],
        exclusive_patterns=[
            "warehouse portfolio",
            "warehouse fleet",
            "warehouse chargeback",
            "warehouse topology",
        ],
        identifier_types=["warehouse_id"],  # warehouse_id routes to warehouse domain
        specificity=3,  # Higher than analytics - wins for warehouse cost questions
        base_confidence=0.95,
    ),
    # =========================================================================
    # ANALYTICS AGENT - FinOps Cost Analysis
    # Specificity: 1 (lowest) - generic cost questions
    # =========================================================================
    "analytics": DomainIntent(
        domain="analytics",
        description="Cost analysis, FinOps, billing reports, usage tracking, DBU consumption",
        simple_keywords=[
            "cost",
            "expensive",
            "spend",
            "spending",
            "billing",
            "budget",
            "price",
            "usage",
            "utilization",
            "waste",
            "finops",
            "dbu",
            "dbus",  # Plural form
            "dbut",
        ],
        compound_patterns=[
            CompoundPattern(("cost", "breakdown"), 0.9),
            CompoundPattern(("cost", "analysis"), 0.9),
            CompoundPattern(("usage", "trend"), 0.9),
            CompoundPattern(("cost", "report"), 0.85),
            CompoundPattern(("billing", "report"), 0.9),
            CompoundPattern(("dbu", "usage"), 0.9),
            CompoundPattern(("dbus", "usage"), 0.9),  # Plural
            # Warehouse cost queries (override warehouse domain for general cost analysis)
            # Higher confidence (0.98) than warehouse domain's patterns (0.95)
            # This ensures analytics handles "Show me warehouse costs" type queries
            CompoundPattern(("warehouse", "cost"), 0.98),
            CompoundPattern(("warehouse", "costs"), 0.98),
            CompoundPattern(("warehouse", "spend"), 0.98),
            CompoundPattern(("warehouse", "spending"), 0.98),
            CompoundPattern(("warehouse", "expensive"), 0.98),
            CompoundPattern(("warehouses", "expensive"), 0.98),  # Plural form
            CompoundPattern(("expensive", "warehouse"), 0.98),
            CompoundPattern(("expensive", "warehouses"), 0.98),  # Plural form
            # DBU consumption queries (override job domain for billing data)
            # Singular forms
            CompoundPattern(("dbu", "job"), 0.95),
            CompoundPattern(("dbu", "run"), 0.95),
            CompoundPattern(("dbu", "spend"), 0.95),
            CompoundPattern(("dbu", "consumption"), 0.95),
            CompoundPattern(("how", "many", "dbu"), 0.95),
            # Plural forms (users often say "DBUs")
            CompoundPattern(("dbus", "job"), 0.95),
            CompoundPattern(("dbus", "run"), 0.95),
            CompoundPattern(("dbus", "spend"), 0.95),
            CompoundPattern(("dbus", "consumption"), 0.95),
            CompoundPattern(("how", "many", "dbus"), 0.95),
            # Cost attribution to jobs/runs
            CompoundPattern(("cost", "job"), 0.9),
            CompoundPattern(("cost", "run"), 0.9),
            CompoundPattern(("expensive", "job"), 0.9),
        ],
        exclusive_patterns=[
            "finops",
            "cost breakdown",
            "billing analysis",
            "dbu consumption",
            "dbus consumption",  # Plural
            "warehouse cost",  # Override warehouse domain for cost analysis
            "warehouse costs",  # Plural form
        ],
        identifier_types=[],
        specificity=3,  # Increased to match warehouse - wins for warehouse cost queries with exclusive patterns
        base_confidence=0.9,
    ),
    # =========================================================================
    # UC AGENT - Unity Catalog / Governance
    # =========================================================================
    "uc": DomainIntent(
        domain="uc",
        description="Unity Catalog, table metadata, lineage, governance, data quality",
        simple_keywords=[
            "catalog",
            "lineage",
            "grant",
            "permission",
            "volume",
            "governance",
            "medallion",
            "bronze",
            "silver",
            "gold",
        ],
        compound_patterns=[
            CompoundPattern(("unity", "catalog"), 0.95),
            CompoundPattern(("table", "lineage"), 0.95),
            CompoundPattern(("data", "lineage"), 0.95),
            CompoundPattern(("schema", "drift"), 0.95),
            CompoundPattern(("access", "policy"), 0.9),
            CompoundPattern(("who", "access"), 0.9),
            CompoundPattern(("table", "governance"), 0.9),
            # Table/schema browsing
            CompoundPattern(("tables", "catalog"), 0.9),
            CompoundPattern(("tables", "schema"), 0.9),
            CompoundPattern(("schemas", "catalog"), 0.9),
            CompoundPattern(("what", "tables"), 0.85),
            CompoundPattern(("list", "tables"), 0.85),
            CompoundPattern(("show", "tables"), 0.85),
        ],
        exclusive_patterns=[
            "unity catalog",
            "lineage",
            "schema drift",
            "access policy",
        ],
        identifier_types=["table_name"],
        specificity=2,
        base_confidence=0.9,
    ),
    # =========================================================================
    # CLUSTER AGENT - Databricks Cluster Configuration
    # =========================================================================
    "cluster": DomainIntent(
        domain="cluster",
        description="Databricks cluster configuration, autoscaling, Spark tuning",
        simple_keywords=[
            "cluster",
            "autoscaling",
            "spark",
            "executor",
            "driver",
            "instance",
            "node",
            "workers",
        ],
        compound_patterns=[
            CompoundPattern(("cluster", "config"), 0.9),
            CompoundPattern(("cluster", "optimize"), 0.9),
            CompoundPattern(("cluster", "size"), 0.9),
            CompoundPattern(("autoscaling", "config"), 0.9),
            CompoundPattern(("spark", "config"), 0.9),
            CompoundPattern(("cluster", "metrics"), 0.9),
        ],
        exclusive_patterns=[
            "cluster configuration",
            "autoscaling policy",
            "spark config",
        ],
        identifier_types=["cluster_id"],
        specificity=2,
        base_confidence=0.95,
    ),
    # =========================================================================
    # DIAGNOSTIC AGENT - Troubleshooting & Artifact Analysis
    # Enhanced for artifact-first, evidence-based diagnostics
    # =========================================================================
    "diagnostic": DomainIntent(
        domain="diagnostic",
        description="Troubleshooting, error investigation, root cause analysis, log analysis",
        simple_keywords=[
            "error",
            "exception",
            "fail",
            "crash",
            "debug",
            "troubleshoot",
            "issue",
            "problem",
            "broken",
            "stuck",
            "oom",
            "sigkill",
            "sigterm",
            "traceback",
        ],
        compound_patterns=[
            # Exit codes (high confidence - clear diagnostic signals)
            CompoundPattern(("exit", "code"), 0.95),
            CompoundPattern(("exit", "137"), 0.98),
            CompoundPattern(("exit", "143"), 0.98),
            CompoundPattern(("exit", "139"), 0.98),
            # OOM patterns
            CompoundPattern(("out", "of", "memory"), 0.95),
            CompoundPattern(("heap", "space"), 0.95),
            CompoundPattern(("gc", "overhead"), 0.95),
            # Spark failures
            CompoundPattern(("task", "failed"), 0.9),
            CompoundPattern(("shuffle", "failed"), 0.95),
            CompoundPattern(("fetch", "failed"), 0.95),
            CompoundPattern(("stage", "failed"), 0.95),
            # Root cause analysis
            CompoundPattern(("root", "cause"), 0.95),
            CompoundPattern(("why", "fail"), 0.9),
            CompoundPattern(("why", "error"), 0.9),
            CompoundPattern(("what", "wrong"), 0.9),
            # Error investigation
            CompoundPattern(("error", "message"), 0.9),
            CompoundPattern(("debug", "error"), 0.9),
            CompoundPattern(("stack", "trace"), 0.95),
        ],
        exclusive_patterns=[
            # Stack trace patterns (lowercase for matching)
            "traceback (most recent call last)",
            "caused by:",
            "exception in thread",
            "java.lang.outofmemoryerror",
            "java.lang.runtimeexception",
            "org.apache.spark",
            "fetchfailedexception",
            "executorlostfailure",
            "sparkexception",
            "analysisexception",
            "outofmemoryerror",
            "oomkilled",
            "oom-killer",
            # Exit code references
            "exit code 137",
            "exit code 143",
            "exit code 139",
            "exited with code",
            # Diagnostic keywords
            "troubleshoot",
            "root cause",
        ],
        identifier_types=[],  # Diagnostics work with any ID or no ID (OFFLINE mode)
        specificity=3,  # High - wins for artifact-based routing
        base_confidence=0.9,
    ),
    # =========================================================================
    # DISCOVERY AGENT - Workspace Health Assessment
    # =========================================================================
    "discovery": DomainIntent(
        domain="discovery",
        description="Workspace health assessment, discovery scan, system table analysis",
        simple_keywords=[
            "discovery",
            "discover",
            "health check",
            "health assessment",
            "workspace health",
            "workspace scan",
            "workspace assessment",
            "workspace audit",
            "system tables",
        ],
        compound_patterns=[
            CompoundPattern(("workspace", "health"), 0.95),
            CompoundPattern(("workspace", "discovery"), 0.95),
            CompoundPattern(("workspace", "scan"), 0.95),
            CompoundPattern(("workspace", "audit"), 0.95),
            CompoundPattern(("health", "check"), 0.95),
            CompoundPattern(("health", "assessment"), 0.95),
            CompoundPattern(("run", "discovery"), 0.95),
            CompoundPattern(("system", "table", "analysis"), 0.95),
            CompoundPattern(("platform", "health"), 0.9),
            CompoundPattern(("platform", "assessment"), 0.9),
            CompoundPattern(("best", "practice", "audit"), 0.9),
        ],
        exclusive_patterns=[
            "workspace health check",
            "workspace discovery",
            "run discovery",
            "workspace health assessment",
            "discover workspace",
            "platform health check",
        ],
        identifier_types=[],
        specificity=3,
        base_confidence=0.95,
    ),
}


# =============================================================================
# SCORING FUNCTIONS
# =============================================================================


def score_domain(
    user_input: str,
    intent: DomainIntent,
    extracted_ids: dict[str, str],
) -> tuple[float, str]:
    """
    Calculate score for a domain based on user input.

    Scoring algorithm:
    1. Check exclusive patterns (instant high score)
    2. Check identifier types (high score if ID matches)
    3. Check compound patterns (medium-high score)
    4. Check simple keywords (lower score)
    5. Apply specificity multiplier

    Args:
        user_input: Normalized (lowercase) user input
        intent: Domain intent configuration
        extracted_ids: Extracted identifiers from input

    Returns:
        Tuple of (score, reasoning)
    """
    score = 0.0
    reasons: list[str] = []

    # 1. Check exclusive patterns (highest priority - instant match)
    for pattern in intent.exclusive_patterns:
        if pattern in user_input:
            return (
                1.0 * intent.specificity,
                f"Exclusive pattern matched: '{pattern}'",
            )

    # 2. Check identifier types (high priority)
    for id_type in intent.identifier_types:
        if extracted_ids.get(id_type):
            score = max(score, 0.9)
            reasons.append(f"Identifier matched: {id_type}")

    # 3. Check compound patterns (medium-high priority)
    compound_scores: list[float] = []
    for compound in intent.compound_patterns:
        pattern_score = compound.score(user_input)
        if pattern_score > 0:
            compound_scores.append(pattern_score)
            reasons.append(f"Compound: {'+'.join(compound.keywords)}")

    if compound_scores:
        # Take best compound score
        score = max(score, max(compound_scores))

    # 4. Check simple keywords (lower priority, additive but capped)
    # Use word boundary matching to prevent "price" matching "cprice_main"
    keyword_matches = [
        kw for kw in intent.simple_keywords if _word_match(kw, user_input)
    ]
    if keyword_matches:
        keyword_score = min(0.3 + 0.1 * len(keyword_matches), 0.6)
        if keyword_score > score:
            score = keyword_score
            reasons = [f"Keywords: {', '.join(keyword_matches[:3])}"]

    # 5. Apply specificity multiplier
    final_score = score * intent.specificity

    reasoning = "; ".join(reasons[:3]) if reasons else "No patterns matched"
    return (final_score, reasoning)


def route_by_scoring(
    user_input: str,
    extracted_ids: dict[str, str],
    disabled_domains: set[str] | None = None,
) -> tuple[str | None, float, str]:
    """
    Route user input to best-matching domain using scoring.

    This replaces sequential rule matching with parallel scoring:
    - All domains are scored simultaneously
    - Highest score wins
    - Specificity acts as tiebreaker

    Args:
        user_input: User's request text
        extracted_ids: Extracted identifiers from input
        disabled_domains: Domains to exclude from routing

    Returns:
        Tuple of (domain, confidence, reasoning)

    Example:
        >>> domain, conf, reason = route_by_scoring(
        ...     "generate chargeback for my warehouse",
        ...     {}
        ... )
        >>> domain
        'warehouse'
        >>> conf
        0.95
    """
    disabled = disabled_domains or set()
    user_lower = user_input.lower()

    # Score all enabled domains
    scores: dict[
        str, tuple[float, float, str]
    ] = {}  # domain -> (score, confidence, reason)

    for domain, intent in DOMAIN_INTENTS.items():
        if domain in disabled:
            continue

        score, reasoning = score_domain(user_lower, intent, extracted_ids)
        scores[domain] = (score, intent.base_confidence, reasoning)

    # Find highest scoring domain
    if not scores:
        return ("query", 0.5, "No domains available, using query as fallback")

    best_domain = max(scores.keys(), key=lambda d: scores[d][0])
    best_score, confidence, reasoning = scores[best_domain]

    # If no domain scored, return None to trigger LLM fallback
    if best_score == 0:
        return (None, 0.0, "No patterns matched")

    return (best_domain, confidence, reasoning)


def get_domain_descriptions() -> dict[str, str]:
    """Get domain descriptions for LLM fallback prompt."""
    return {domain: intent.description for domain, intent in DOMAIN_INTENTS.items()}
