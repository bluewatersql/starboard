# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""W-W02 ``warehouse_auto_stop_disabled`` qualification (run-4 D2-2).

The rule fired ``high`` on every serverless warehouse whose idle running share
crossed the threshold, even though serverless idle time is the post-query tail
before suspend (``est_idle_dbus`` is NULL by design) and the warehouses all had
a 10-minute auto-stop. The detector now reads the current ``auto_stop_minutes``
(W-W02 column) and ``warehouse_type``:

- auto-stop off / too long -> the rule severity (any type);
- serverless + short auto-stop -> no finding;
- serverless + setting unknown -> ``low``, worded as an idle tail;
- classic/pro + short auto-stop -> the rule severity, worded as idle between
  queries (not "auto-stop disabled");
- type and setting both unknown -> the original wording.
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.finding import Severity
from starboard_core.domain.rules.detectors import (
    DETECTORS,
    detect_warehouse_auto_stop_disabled,
)
from starboard_core.domain.rules.evaluator import build_review
from starboard_core.domain.rules.registry import RuleRegistry

_RULE = "warehouse_auto_stop_disabled"


def _wh(wid: str, waste: object = 80.0, **extra: object) -> dict:
    return {
        "warehouse_id": wid,
        "auto_stop_waste_pct": waste,
        "idle_running_hours": 12.5,
        **extra,
    }


@pytest.fixture
def registry() -> RuleRegistry:
    return RuleRegistry.from_seed()


@pytest.mark.unit
class TestDetector:
    def test_registered(self) -> None:
        assert DETECTORS[_RULE] is detect_warehouse_auto_stop_disabled

    def test_serverless_with_short_auto_stop_does_not_fire(self) -> None:
        rows = [_wh("s1", warehouse_type="SERVERLESS", auto_stop_minutes=10)]
        assert detect_warehouse_auto_stop_disabled(rows) == []

    def test_serverless_type_is_case_insensitive(self) -> None:
        rows = [_wh("s1", warehouse_type="serverless", auto_stop_minutes=5)]
        assert detect_warehouse_auto_stop_disabled(rows) == []

    def test_serverless_with_unknown_config_is_low_idle_tail(self) -> None:
        [m] = detect_warehouse_auto_stop_disabled(
            [_wh("s1", warehouse_type="SERVERLESS", auto_stop_minutes=None)]
        )
        assert m.severity == Severity.LOW
        assert "serverless idle tail" in m.current_state
        assert "disabled" not in m.current_state

    @pytest.mark.parametrize("wtype", ["SERVERLESS", "PRO", "CLASSIC", None])
    def test_auto_stop_off_fires_at_rule_severity(self, wtype: str | None) -> None:
        [m] = detect_warehouse_auto_stop_disabled(
            [_wh("w", warehouse_type=wtype, auto_stop_minutes=0)]
        )
        assert m.severity is None  # rule default (high)
        assert "auto-stop is off" in m.current_state

    @pytest.mark.parametrize("wtype", ["SERVERLESS", "PRO"])
    def test_auto_stop_too_long_fires_at_rule_severity(self, wtype: str) -> None:
        [m] = detect_warehouse_auto_stop_disabled(
            [_wh("w", warehouse_type=wtype, auto_stop_minutes=120)]
        )
        assert m.severity is None
        assert "auto-stop is set to 120 min (longer than 10)" in m.current_state

    def test_classic_short_auto_stop_reworded_not_disabled(self) -> None:
        [m] = detect_warehouse_auto_stop_disabled(
            [_wh("p1", warehouse_type="PRO", auto_stop_minutes=10)]
        )
        assert m.severity is None
        assert "idle time between queries with a 10-min auto-stop" in m.current_state
        assert "disabled" not in m.current_state

    def test_unknown_type_and_config_keeps_original_wording(self) -> None:
        [m] = detect_warehouse_auto_stop_disabled([_wh("wh-idle")])
        assert m.severity is None
        assert m.current_state == (
            "Warehouse wh-idle spent 80% of its running time (12.5h idle) with "
            "zero queries — auto-stop is effectively disabled or set too long."
        )

    def test_below_waste_threshold_never_fires(self) -> None:
        rows = [_wh("w", waste=40.0, warehouse_type="PRO", auto_stop_minutes=0)]
        assert detect_warehouse_auto_stop_disabled(rows) == []

    def test_params_override_thresholds(self) -> None:
        rows = [_wh("w", waste=40.0, warehouse_type="PRO", auto_stop_minutes=30)]
        params = {"waste_pct": 30, "max_auto_stop_minutes": 60}
        [m] = detect_warehouse_auto_stop_disabled(rows, params)
        assert "30-min auto-stop" in m.current_state
        assert (
            detect_warehouse_auto_stop_disabled(
                [_wh("s", warehouse_type="SERVERLESS", auto_stop_minutes=30)], params
            )
            == []
        )


@pytest.mark.unit
class TestSeedAndReview:
    def test_seed_rule_declares_params(self, registry: RuleRegistry) -> None:
        rule = {r.id: r for r in registry.rules_for("warehouse")}[_RULE]
        assert rule.params["waste_pct"] == 50.0
        assert rule.params["max_auto_stop_minutes"] == 10
        assert rule.evidence_query == "W-W02"

    def test_review_drops_serverless_tail_keeps_real_gaps(
        self, registry: RuleRegistry
    ) -> None:
        """The run-4 shape: many serverless warehouses with a 10-min auto-stop
        produced 20 ``high`` findings; now only real gaps are reported."""
        rows = [
            _wh(f"s{i}", warehouse_type="SERVERLESS", auto_stop_minutes=10)
            for i in range(20)
        ]
        rows += [
            _wh("off", warehouse_type="SERVERLESS", auto_stop_minutes=0),
            _wh("unk", warehouse_type="SERVERLESS"),
        ]
        review = build_review(
            registry=registry,
            domains=["warehouse"],
            rows_by_query_id={"W-W02": rows},
        )
        found = {
            f.finding.location.entity: f.finding.severity
            for f in review.findings
            if f.finding.rule_id == _RULE
        }
        assert found == {"off": Severity.HIGH, "unk": Severity.LOW}
