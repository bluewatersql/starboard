# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Internal-env integration tests for the gated adapters (Phase-3 O1).

These tests exercise the **real** backends against a live/staging internal
deployment. They are guarded by :mod:`pytest.mark.skipif` on the internal
``STARBOARD_INTERNAL_*`` env vars, so they SKIP cleanly wherever that env is
absent (CI, public dev). They are the owner-runbook (Internal-env gate) parity
run: with the env wired, each adapter must return real data that is a strict
SUPERSET of the public adapter's contract.
"""
