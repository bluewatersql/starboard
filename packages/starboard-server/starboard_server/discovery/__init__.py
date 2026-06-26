# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Databricks workspace discovery and health assessment pipeline.

Provides the ``DiscoveryEngine`` for running a full workspace health
assessment across Databricks system tables. The pipeline runs in four phases:

1. **Audit** — discover active product surfaces
2. **Query** — execute conditional SQL packs in parallel
3. **Analyze** — deterministic heuristics + LLM domain analysis
4. **Synthesize** — aggregate into a graded report with priorities
"""

from starboard_server.discovery.engine import (
    DiscoveryEngine,
    EngineConfig,
    EngineResult,
    ProgressCallback,
)

__all__ = [
    "DiscoveryEngine",
    "EngineConfig",
    "EngineResult",
    "ProgressCallback",
]
