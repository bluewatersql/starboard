"""Run-5 group D7: ``review --since`` speaks with run recur's voice on overlapping windows."""

from __future__ import annotations

import io

from rich.console import Console
from starboard.cli.cli.review_command import _render_cost_delta
from starboard_core.domain.rules.action_rate import FindingsManifest, compute_cost_delta


def _m(run_date: str, *keys: str) -> FindingsManifest:
    return FindingsManifest.model_validate({
        "run_date": run_date,
        "lookback_days": 30,
        "findings": [
            {"id": k, "composite_key": k, "rule_id": k.split("::")[0],
             "entity_id": k.split("::")[1], "severity": "high", "score": 1.0}
            for k in keys
        ],
    })


def _render(delta) -> str:
    buf = io.StringIO()
    _render_cost_delta(delta, Console(file=buf, width=300, no_color=True))
    return buf.getvalue()


def test_overlapping_since_manifest_is_capture_repeatability():
    delta = compute_cost_delta(_m("2026-10-01", "A::1", "B::2"), _m("2026-10-01", "A::1", "C::3"))
    assert delta.comparable is False and delta.not_comparable_reason == "interval_overlap"
    text = _render(delta)
    assert "not comparable" in text and "interval_overlap" in text
    assert "Capture repeatability, not a change: 1 finding(s) present in both captures" in text
    assert "1 only in this capture, 1 only in the prior" in text
    assert "improved" not in text.lower() and "regressed" not in text.lower()


def test_abutting_since_manifest_still_reports_a_change():
    delta = compute_cost_delta(_m("2026-09-01", "A::1"), _m("2026-10-01", "A::1"))
    assert delta.comparable is True
    assert "Capture repeatability" not in _render(delta)
