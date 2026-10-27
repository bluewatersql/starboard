# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 6b: how ``active_rule_findings`` reconciles with a capped manifest.

``active_rule_findings`` counts the family's findings the manifest lists (one per
``rule::entity``); a capped rule lists exactly ``rule_finding_cap`` findings and its
``rule_findings_dropped`` matches are not listed, so they are never counted. In the
live run a 50-item ``engagement read`` cut the manifest list, which made a capped rule
look like it listed 10 findings under a cap of 20.
"""

from __future__ import annotations

import pytest

from .test_families import finding, manifest, rc

pytestmark = pytest.mark.unit


def _capped(rule_id: str, n: int, dropped: int) -> list[dict]:
    return [
        finding(rule_id, f"job-{i}", rule_finding_cap=20, rule_findings_dropped=dropped)
        for i in range(n)
    ]


def test_active_rule_findings_counts_listed_findings_not_dropped_ones() -> None:
    entries = [
        *_capped("job_high_failure_rate", 20, 12),
        *_capped("job_wasted_dbu_on_failures_retries", 20, 9),
        finding("portfolio_unreliable_production_workload", "job-a"),
        finding("portfolio_unreliable_production_workload", "job-b"),
    ]
    out = rc(manifest(*entries), reviewed_domains=["jobs", "portfolio_readiness"])
    assert out[("reliability", "active_rule_findings")].value == 42.0
