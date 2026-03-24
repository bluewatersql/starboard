"""
Analysis services for Databricks resources.

This package provides analysis capabilities for jobs, queries, notebooks, and pipelines.
"""

from starboard_server.services.analysis.table_metadata import (
    TableDiscovery,
    TableEnricher,
)

__all__ = ["TableDiscovery", "TableEnricher"]
