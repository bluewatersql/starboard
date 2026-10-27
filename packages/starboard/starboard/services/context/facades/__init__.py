# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Context facades package.

All facades have been removed. Use SharedContextProvider directly with transforms:

    from starboard.services.context.provider import SharedContextProvider
    from starboard.services.context.transforms import (
        get_transformed,
        get_job_metadata,
        get_explain_plan,
        analyze_cluster_metrics,
        # ... etc
    )

    provider = SharedContextProvider(client)
    job_data = await get_job_metadata(provider, job_id)

See starboard.services.context.transforms for available helper functions.
"""

__all__: list[str] = []
