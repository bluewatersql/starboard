# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 7: the run-folder discovery summary sheds pack refs before the facts."""

from __future__ import annotations

import pytest
from starboard_core.engagement.stdout_budget import bound, encoded_size
from starboard_x.discovery.serialize import SUMMARY_PACK_KEYS, fit_summary

pytestmark = pytest.mark.unit

_BUDGET = 3_500


def _payload(packs: int) -> dict:
    manifest = [
        {
            "pack": f"p{i}",
            "domain": f"d{i}",
            "queries": 3,
            "succeeded": 3,
            "rows_total": 9,
            "truncated": False,
            "limit_reached": False,
            "path": f"raw/p{i}.json",
        }
        for i in range(packs)
    ]
    return {
        "run_id": "r",
        "summary": {
            "layout_prefix": "",
            "facts": {
                "product_mix": [{"product": f"P{i}", "dbus": i} for i in range(8)]
            },
            "packs": manifest,
        },
        "refs": [
            {"path": m["path"], "object_id": "o" * 33, "size": 1} for m in manifest
        ]
        + [{"path": "facts.json", "object_id": "f" * 33, "size": 1}],
    }


def test_bound_alone_cuts_the_facts_lists() -> None:
    # The run-7 failure, for the record: the facts' lists are re-capped too.
    assert (
        len(bound(_payload(24), max_bytes=_BUDGET)["summary"]["facts"]["product_mix"])
        < 8
    )


def test_fit_summary_keeps_the_facts_and_names_every_pack() -> None:
    payload = _payload(24)
    out = bound(fit_summary(payload, max_bytes=_BUDGET), max_bytes=_BUDGET)
    assert encoded_size(out) <= _BUDGET and "truncated" not in out
    assert out["summary"]["facts"] == payload["summary"]["facts"]
    assert [p["pack"] for p in out["summary"]["packs"]] == [f"p{i}" for i in range(24)]
    assert set(out["summary"]["packs"][0]) == set(SUMMARY_PACK_KEYS)
    assert out["refs"] == [payload["refs"][-1]] and out["pack_refs_omitted"] == 24


def test_fit_summary_leaves_a_fitting_payload_alone() -> None:
    payload = _payload(2)
    assert fit_summary(payload, max_bytes=_BUDGET) == payload
