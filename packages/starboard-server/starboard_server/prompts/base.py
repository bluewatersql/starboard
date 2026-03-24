"""
Prompt base utilities and types.

Common types and utilities used across all domain prompts.

Extracted from domain_prompts.py for better organization.
"""

from typing import Literal, get_args

# Agent domain type definition
AgentDomain = Literal[
    "router",
    "query",
    "job",
    "uc",
    "cluster",
    "diagnostic",
    "analytics",
    "warehouse",
    "discovery",
]
"""Type for domain specialist identifiers.

Note: "uc" (Unity Catalog) replaces the deprecated "table" domain.
Note: "warehouse" handles SQL warehouse portfolio optimization.
Note: "cluster" replaces the deprecated "compute" domain for cluster configuration.
Note: "discovery" handles workspace health assessment and discovery.
"""

# All domains that can be routed to (excludes "router" which is the orchestrator)
ROUTABLE_DOMAINS: frozenset[str] = frozenset(
    d for d in get_args(AgentDomain) if d != "router"
)
"""Domains that can be targets of routing decisions.

Excludes "router" since it's the orchestrator, not a specialist.
Use this for validation instead of hardcoded sets.
"""
