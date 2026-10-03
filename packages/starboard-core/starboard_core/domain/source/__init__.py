# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Source-resolution domain logic — pure stdlib, no I/O."""

from starboard_core.domain.source.run_following import (
    extract_run_targets,
    resolve_run_path,
)

__all__ = ["extract_run_targets", "resolve_run_path"]
