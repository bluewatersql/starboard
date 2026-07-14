# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Analysis services for Databricks resources.

This package provides analysis capabilities for jobs, queries, notebooks, and pipelines.
"""

from starboard.services.analysis.table_metadata import (
    TableDiscovery,
    TableEnricher,
)

__all__ = ["TableDiscovery", "TableEnricher"]
