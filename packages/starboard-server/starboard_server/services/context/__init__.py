# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Context building services for Databricks optimization.

This package provides services for building analysis contexts from
Databricks resources like jobs, queries, notebooks, and pipelines.

Architecture:
- SharedContextProvider: Centralized context management with caching
- transforms: Transform functions for converting raw API data

Usage:
    from starboard_server.services.context import SharedContextProvider
    from starboard_server.services.context.transforms import (
        get_job_metadata,
        get_explain_plan,
        analyze_cluster_metrics,
    )

    provider = SharedContextProvider(client)
    job_data = await get_job_metadata(provider, job_id)
"""

from starboard_server.services.context.provider import (
    ContextCache,
    SharedContextProvider,
)

__all__ = [
    "SharedContextProvider",
    "ContextCache",
]
