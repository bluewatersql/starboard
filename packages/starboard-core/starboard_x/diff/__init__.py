# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x.diff`` — deterministic diffs of two JSON documents (D3-24).

``python -m starboard_x.diff settings`` lists the JSON-path adds, removes and
changes between two documents (two ``job fetch`` outputs); ``metrics`` gives the
per-key delta and unit of their numeric values (two ``query fetch`` /
``diagnostic profile`` outputs, ``pp`` for a percentage). Pure and SDK-free
(import-linter contract 3); read-only: it writes nothing.
"""

__all__: list[str] = []
