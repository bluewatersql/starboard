# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Domain-specific system prompts for specialized agents.

This package provides system prompts for each domain specialist agent
in the multi-agent architecture. Each prompt is tailored to the agent's
specific focus area and curated tool set.

Domain specialists:
- router: Intent classification and request routing
- query: SQL query optimization and analysis
- job: Databricks job optimization
- uc: Unity Catalog governance, lineage, schema analysis, access policies
- cluster: Databricks cluster configuration and optimization
- diagnostic: Troubleshooting and root cause analysis
- analytics: Cost analysis, FinOps, billing, usage tracking
- warehouse: SQL warehouse portfolio optimization

Architecture:
- Prompts organized by domain in separate modules
- Single version per domain (v1.0.0 baseline)
- Factories for dynamic prompt building
"""

# Base utilities
# Domain prompts
from starboard_server.prompts.analytics import ANALYTICS_SYSTEM_PROMPT
from starboard_server.prompts.base import ROUTABLE_DOMAINS, AgentDomain
from starboard_server.prompts.cluster import CLUSTER_SYSTEM_PROMPT
from starboard_server.prompts.diagnostic import DIAGNOSTIC_SYSTEM_PROMPT

# Factory functions
from starboard_server.prompts.factories import (
    build_analytics_prompt,
    build_cluster_prompt,
    build_diagnostic_prompt,
    build_job_prompt,
    build_query_prompt,
    build_router_prompt,
    build_uc_prompt,
    build_warehouse_prompt,
    get_prompt_builder_for_domain,
    get_system_prompt,
)
from starboard_server.prompts.job import JOB_SYSTEM_PROMPT
from starboard_server.prompts.query import QUERY_SYSTEM_PROMPT
from starboard_server.prompts.router import ROUTER_SYSTEM_PROMPT
from starboard_server.prompts.uc import UC_SYSTEM_PROMPT
from starboard_server.prompts.warehouse import WAREHOUSE_SYSTEM_PROMPT

__all__ = [
    # Types
    "AgentDomain",
    "ROUTABLE_DOMAINS",
    # Prompts
    "ROUTER_SYSTEM_PROMPT",
    "QUERY_SYSTEM_PROMPT",
    "JOB_SYSTEM_PROMPT",
    "UC_SYSTEM_PROMPT",
    "CLUSTER_SYSTEM_PROMPT",
    "DIAGNOSTIC_SYSTEM_PROMPT",
    "ANALYTICS_SYSTEM_PROMPT",
    "WAREHOUSE_SYSTEM_PROMPT",
    # Factories
    "get_system_prompt",
    "build_router_prompt",
    "build_query_prompt",
    "build_job_prompt",
    "build_uc_prompt",
    "build_cluster_prompt",
    "build_diagnostic_prompt",
    "build_analytics_prompt",
    "build_warehouse_prompt",
    "get_prompt_builder_for_domain",
]
