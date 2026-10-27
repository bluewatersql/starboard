# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Domain conversation types re-exported for agent layer consumption.

Agents should import from this module instead of api.models to maintain
the architectural boundary: agents → domain (not agents → api).
"""
