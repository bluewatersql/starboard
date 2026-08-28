# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Keyword-to-domain map for natural-language query domain recall.

Deterministic, embedding-free resolution of Databricks RAG resource domains
from free-text queries that do not mention ``system.<schema>.<table>`` explicitly.

The map is curated and intentionally extensible: add entries here when new query
patterns emerge.  Domain slugs match ``RagResourceDomain`` values in
``starboard_core.rag.resource_domains``.

Usage::

    from starboard.infra.rag.domain_keywords import resolve_domains_from_nl_query

    domains = resolve_domains_from_nl_query("why is my warehouse slow")
    # → ["compute_warehouses", "query"]
"""

from __future__ import annotations

import re

# Curated keyword → tuple-of-domain-slugs mapping (all keys lowercase).
# Within each tuple, domains are ordered by relevance (first = most relevant).
# Domain slugs match the ``RagResourceDomain`` StrEnum values in starboard_core.
_KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    # --- workload_jobs ---
    "job": ("workload_jobs",),
    "jobs": ("workload_jobs",),
    "task": ("workload_jobs",),
    "workflow": ("workload_jobs",),
    "lakeflow": ("workload_jobs",),
    "fail": ("workload_jobs",),
    "failed": ("workload_jobs",),
    "failure": ("workload_jobs",),
    "failing": ("workload_jobs",),
    "retry": ("workload_jobs",),
    "retries": ("workload_jobs",),
    "timeout": ("workload_jobs", "compute_warehouses"),
    "scheduled": ("workload_jobs",),
    "trigger": ("workload_jobs",),
    # --- workload_pipelines ---
    "pipeline": ("workload_pipelines",),
    "pipelines": ("workload_pipelines",),
    "dlt": ("workload_pipelines",),
    "streaming": ("workload_pipelines", "compute_clusters"),
    # --- compute_warehouses / query ---
    "warehouse": ("compute_warehouses",),
    "warehouses": ("compute_warehouses",),
    "sql": ("query", "compute_warehouses"),
    "query": ("query",),
    "queries": ("query",),
    "slow": ("query", "compute_warehouses"),
    "slowness": ("query", "compute_warehouses"),
    "latency": ("query", "compute_warehouses"),
    "performance": ("query", "compute_warehouses"),
    "queue": ("compute_warehouses",),
    "queuing": ("compute_warehouses",),
    "spill": ("query",),
    "scan": ("query",),
    "photon": ("compute_warehouses",),
    # --- compute_clusters ---
    "cluster": ("compute_clusters",),
    "clusters": ("compute_clusters",),
    "autoscale": ("compute_clusters",),
    "autoscaling": ("compute_clusters",),
    "spot": ("compute_clusters",),
    "worker": ("compute_clusters",),
    "driver": ("compute_clusters",),
    "node": ("compute_clusters",),
    # --- finops_billing ---
    "cost": ("finops_billing",),
    "costs": ("finops_billing",),
    "billing": ("finops_billing",),
    "spend": ("finops_billing",),
    "dbu": ("finops_billing",),
    "budget": ("finops_billing",),
    "expensive": ("finops_billing",),
    "price": ("finops_billing",),
    "pricing": ("finops_billing",),
    "invoice": ("finops_billing",),
    # --- governance_unity_catalog ---
    "catalog": ("governance_unity_catalog",),
    "schema": ("governance_unity_catalog",),
    "freshness": ("governance_unity_catalog", "storage_optimization"),
    "stale": ("storage_optimization", "governance_unity_catalog"),
    "metadata": ("governance_unity_catalog",),
    "ownership": ("governance_unity_catalog",),
    "tag": ("governance_unity_catalog",),
    "tags": ("governance_unity_catalog",),
    # --- storage_optimization ---
    "storage": ("storage_optimization",),
    "optimize": ("storage_optimization",),
    "vacuum": ("storage_optimization",),
    "compaction": ("storage_optimization",),
    "predictive": ("storage_optimization",),
    "bloat": ("storage_optimization",),
    "fragmentation": ("storage_optimization",),
    # --- security_access ---
    "access": ("security_access",),
    "permission": ("security_access",),
    "permissions": ("security_access",),
    "audit": ("security_access",),
    "grant": ("security_access",),
    "revoke": ("security_access",),
    "privilege": ("security_access",),
    "acl": ("security_access",),
    # --- lineage ---
    "lineage": ("lineage",),
    "upstream": ("lineage",),
    "downstream": ("lineage",),
    "dependency": ("lineage",),
    "dependencies": ("lineage",),
    # --- mlflow ---
    "mlflow": ("mlflow",),
    "experiment": ("mlflow",),
    "experiments": ("mlflow",),
    "tracking": ("mlflow",),
    # --- serving ---
    "endpoint": ("serving",),
    "endpoints": ("serving",),
    "serving": ("serving",),
    "inference": ("serving",),
    "deployment": ("serving",),
    # --- workspace_admin ---
    "workspace": ("workspace_admin",),
    "admin": ("workspace_admin",),
    # --- network ---
    "network": ("network",),
    "firewall": ("network",),
    "egress": ("network",),
    "ingress": ("network",),
    "vpc": ("network",),
}

# Tokenises the lowercased query into alphanumeric+underscore tokens.
_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]*")


def resolve_domains_from_nl_query(
    query: str,
    max_domains: int = 3,
) -> list[str]:
    """Resolve RAG resource domains from a natural-language query.

    Tokenises the query, scores each candidate domain by keyword hit count,
    and returns the top ``max_domains`` domain slugs ordered by descending score.

    Returns an empty list when no keywords match — callers decide whether to
    fall back to a default set or return empty context.

    Args:
        query: The raw user query string.
        max_domains: Maximum number of domains to return (default 3).  Keeps the
            returned context *bounded* so the agent isn't flooded with irrelevant
            reference material.

    Returns:
        Ordered list of ``RagResourceDomain`` slug strings (may be empty).
    """
    tokens = _TOKEN_RE.findall(query.lower())
    scores: dict[str, float] = {}
    for token in tokens:
        for domain in _KEYWORD_MAP.get(token, ()):
            scores[domain] = scores.get(domain, 0.0) + 1.0

    if not scores:
        return []

    ranked = sorted(scores, key=lambda d: -scores[d])
    return ranked[:max_domains]
