# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x.review`` — pure Workload Review helper (Phase-3 D1b).

Exposes the deterministic Workload Review engine
(:mod:`starboard_core.domain.rules.evaluator`) behind the stable
``starboard_x`` JSON-envelope + exit-code contract. Like the ``warehouse`` /
``uc`` helpers it is **I/O-free and SDK-free**: it scores query-pack rows read
from a JSON file, never connecting to Databricks. The SDK-touching pack
execution lives in the ``starboard`` server tier (the ``starboard review`` CLI).
"""
