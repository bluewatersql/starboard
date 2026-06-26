# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Domain transformers - pure data transformation functions.

These transformers condense raw API responses into compact summaries
suitable for LLM context windows while preserving key insights.
"""

from starboard_core.domain.transformers.job_transformers import (
    transform_job_config,
    transform_job_runs,
    transform_system_tables_job_detail,
    transform_task_sources,
)
from starboard_core.domain.transformers.uc_transformers import (
    AccessPatternTransformer,
    LineageGraphTransformer,
    QueryFingerprint,
    QueryOperation,
    SchemaHistoryTransformer,
    TableFingerprintTransformer,
    classify_query,
    resolve_3part,
    transform_delta_history,
    transform_table_lineage,
    transform_table_metadata,
)

__all__ = [
    # Enums and models
    "QueryOperation",
    "QueryFingerprint",
    # UC Transformers
    "LineageGraphTransformer",
    "TableFingerprintTransformer",
    "AccessPatternTransformer",
    "SchemaHistoryTransformer",
    # UC Functions
    "classify_query",
    "transform_table_metadata",
    "resolve_3part",
    "transform_delta_history",
    "transform_table_lineage",
    # Job Transformers
    "transform_task_sources",
    "transform_job_config",
    "transform_job_runs",
    "transform_system_tables_job_detail",
]
