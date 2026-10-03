# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x.warehouse`` — dep-light SQL-warehouse analysis CLI (Phase-2 D4).

Wraps the **pure** warehouse analyzers that already live in the kernel
(``starboard_core.domain.analyzers.warehouse_analyzer``): no re-home is needed
because those analyzers are SDK-free by construction (enforced by the
``starboard_core.domain`` import-linter contract). ``python -m
starboard_x.warehouse analyze`` therefore computes a fingerprint + health score
over a query-history JSON with **no** ``databricks-sdk`` import.

Ships behind the ``[warehouse]`` extra.
"""

__all__: list[str] = []
