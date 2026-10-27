# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Six-family metric catalog (spec §C, D3-15).

Pure data. Each health family lists the metrics that can assess it, with their
unit, entity grain, source (discovery fact IDs, verify templates, or
``findings_manifest`` for the rule-coverage metrics) and whether the metric is
*required* for ``complete`` family coverage (D3-6). Workspace reliability comes
only from F-06; per-job reliability (F-12 / ``vt-job-run-states``) never feeds
the workspace read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from starboard_core.domain.rules.schema import RULE_FAMILIES

__all__ = ["FAMILY_METRICS", "METHOD_VERSION", "SIX_FAMILIES", "MetricSpec"]

#: ``method_version`` of observations derived from this catalog.
METHOD_VERSION = "family_observations_v1"
#: The six health families: the rule-schema tuple itself (one source of truth),
#: in ``records.FAMILIES`` order without ``other``.
SIX_FAMILIES: tuple[str, ...] = RULE_FAMILIES


@dataclass(frozen=True)
class MetricSpec:
    """One catalog metric.

    Attributes:
        metric: Observation ``metric`` name.
        unit: One of :data:`starboard_core.engagement.records.UNITS`.
        entity_kind: Observation ``entity_kind`` (grain).
        source: Fact / template IDs (``|``-separated) or ``findings_manifest``.
        required: Needed (measured, complete) for complete family coverage.
    """

    metric: str
    unit: str
    entity_kind: str
    source: str
    required: bool = False


_RULES = "findings_manifest"


def _rule_metrics(family: str) -> tuple[MetricSpec, ...]:
    required = family == "governance"
    return (
        MetricSpec("rules_evaluated", "count", "workspace", _RULES, required),
        MetricSpec("active_rule_findings", "count", "workspace", _RULES, required),
    )


_PER_JOB = "F-12|vt-job-run-states"

_FACT_METRICS: dict[str, tuple[MetricSpec, ...]] = {
    "consumption_trajectory": (
        MetricSpec("total_dbus", "DBU", "workspace", "F-01", True),
        MetricSpec("total_dsu", "DSU", "workspace", "F-01", True),
        MetricSpec("last_full_month_dbus", "DBU", "workspace", "F-02"),
        MetricSpec("month_over_month_pct", "pct", "workspace", "F-02"),
        MetricSpec("step_change_present", "flag", "workspace", "F-03"),
        MetricSpec("step_change_lift_daily_dbus", "DBU/day", "workspace", "F-03"),
    ),
    "efficiency": (
        MetricSpec("performance_optimized_pct", "pct", "workspace", "F-07", True),
        MetricSpec("warehouse_serverless_share_pct", "pct", "workspace", "F-08|F-09"),
    ),
    "reliability": (
        MetricSpec("job_runs", "count", "workspace", "F-06", True),
        MetricSpec("failed_job_runs", "count", "workspace", "F-06", True),
        MetricSpec("cancelled_job_runs", "count", "workspace", "F-06", True),
        MetricSpec("job_failure_rate_pct", "pct", "workspace", "F-06", True),
        MetricSpec("job_runs", "count", "job", _PER_JOB),
        MetricSpec("failed_job_runs", "count", "job", _PER_JOB),
        MetricSpec("job_failure_rate_pct", "pct", "job", _PER_JOB),
    ),
    "governance": (),
    "adoption_breadth": (
        MetricSpec("products_in_use", "count", "workspace", "F-01", True),
        MetricSpec("product_in_use", "flag", "product", "F-01"),
    ),
    "concentration": (
        MetricSpec("top_job_share_pct", "pct", "workspace", "F-04", True),
        MetricSpec("top10_jobs_share_pct", "pct", "workspace", "F-04", True),
        MetricSpec("top_warehouse_share_pct", "pct", "workspace", "F-11"),
        MetricSpec("top_product_share_pct", "pct", "workspace", "F-01"),
    ),
}

#: Family → metrics, in :data:`SIX_FAMILIES` order.
FAMILY_METRICS: Mapping[str, tuple[MetricSpec, ...]] = MappingProxyType(
    {f: (*_FACT_METRICS[f], *_rule_metrics(f)) for f in SIX_FAMILIES}
)
