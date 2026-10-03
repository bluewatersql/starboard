# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x.uc`` — dep-light Unity Catalog analysis CLI (Phase-2 D4).

Wraps the **pure** UC analyzers already in the kernel
(``starboard_core.domain.analyzers.uc_analyzer``). Those static methods are
SDK-free (enforced by the ``starboard_core.domain`` import-linter contract), so
``python -m starboard_x.uc analyze`` detects schema anomalies, classifies the
table, and scores schema health over a columns JSON with **no**
``databricks-sdk`` import.

Ships behind the ``[uc]`` extra.
"""

__all__: list[str] = []
