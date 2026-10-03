# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Context type identifiers for analyzing user-provided context.

This module defines context types used by the planning system to determine
which lookup operations are necessary versus which can be skipped.
"""


class ContextType:
    """
    Context type identifiers for user-provided input.

    These constants help the planner determine whether user-provided context
    is direct content (SQL, code) or identifiers that require lookups.

    Attributes:
        JOB_ID: Databricks job ID requiring lookup
        JOB_NAME: Databricks job name requiring lookup
        STATEMENT_ID: SQL statement ID requiring lookup
        RAW_SQL: Direct SQL query (no lookup needed)
        SOURCE_CODE: Direct source code (no lookup needed)
        UNKNOWN: Ambiguous or unrecognized input
    """

    # Identifiers that require lookups
    JOB_ID = "job_id"
    JOB_NAME = "job_name"
    STATEMENT_ID = "statement_id"

    # Direct context that doesn't require lookups
    RAW_SQL = "raw_sql"
    SOURCE_CODE = "source_code"

    # Unknown/ambiguous
    UNKNOWN = "unknown"
