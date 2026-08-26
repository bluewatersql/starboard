# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x.discovery`` — dep-light discovery (data-only) CLI (Phase-2 D4).

Wraps the deterministic ``data_only`` path of the discovery engine
(``starboard.discovery.engine`` with ``EngineConfig(data_only=True)``) — the
audit + query-pack phases only, **no LLM analysis or synthesis**. The engine
lives in the heavier ``starboard`` server package, so ``python -m
starboard_x.discovery`` imports it **lazily** inside :func:`build_engine`: merely
importing this sub-package never pulls ``starboard`` / ``databricks-sdk`` /
``openai`` into the process (the arg-error path stays dep-light and the builder
is a clean seam for tests).

Ships behind the ``[discovery]`` extra (polars + databricks-sql-connector + sdk).
"""

__all__: list[str] = []
