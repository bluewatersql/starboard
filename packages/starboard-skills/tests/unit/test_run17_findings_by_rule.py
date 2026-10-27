# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 17: the ``analyze`` digest counts findings per review rule.

A host paged ``findings-manifest.json`` to count each rule's findings and read
``rule_findings_dropped`` for the caps; ``findings_by_rule`` carries both.
"""

from __future__ import annotations

import pytest
from starboard_skills.helpers.engagement import analysis_cmds as ac


@pytest.mark.unit
def test_findings_by_rule_counts_findings_and_cap_drops() -> None:
    manifest = {
        "findings": [
            {
                "rule_id": "job_high_failure_rate",
                "rule_finding_cap": 2,
                "rule_findings_dropped": 5,
            },
            {
                "rule_id": "job_high_failure_rate",
                "rule_finding_cap": 2,
                "rule_findings_dropped": 5,
            },
            {"rule_id": "job_cron_overlap", "rule_findings_dropped": None},
            {"id": "no-rule"},
        ]
    }
    assert ac.findings_by_rule(manifest) == {
        "job_high_failure_rate": {"findings": 2, "dropped": 5},
        "job_cron_overlap": {"findings": 1, "dropped": 0},
    }
    # Most findings first.
    assert list(ac.findings_by_rule(manifest)) == [
        "job_high_failure_rate",
        "job_cron_overlap",
    ]


@pytest.mark.unit
@pytest.mark.parametrize("manifest", [None, {}, {"findings": None}, []])
def test_findings_by_rule_without_a_manifest_is_empty(manifest) -> None:
    assert ac.findings_by_rule(manifest) == {}
