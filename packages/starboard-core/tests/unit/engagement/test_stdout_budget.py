# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the stdout envelope budget (P2-G12, D-29)."""

from __future__ import annotations

import json
from typing import Any

from starboard_core.engagement.stdout_budget import (
    DEFAULT_MAX_BYTES,
    MAX_LIST_ITEMS,
    bound,
    encoded_size,
)


def envelope(data: dict[str, Any], **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ok": True,
        "domain": "engagement",
        "command": "history",
        "data": data,
        "warnings": [],
        "errors": [],
    }
    base.update(over)
    return base


def test_constants() -> None:
    assert MAX_LIST_ITEMS == 50
    assert DEFAULT_MAX_BYTES == 24_000


def test_small_payload_is_unchanged() -> None:
    p = envelope({"run_id": "r", "counts": {"a": 1}, "items": list(range(10))})
    out = bound(p)
    assert out == p
    assert "truncated" not in out
    assert out is not p


def test_encoded_size_is_compact_json() -> None:
    p = {"a": [1, 2], "b": "x"}
    assert encoded_size(p) == len(json.dumps(p, default=str).encode("utf-8"))


def test_row_arrays_are_dropped() -> None:
    rows = [{"x": i} for i in range(3)]
    p = envelope(
        {"run_id": "r", "rows": rows, "packs": [{"id": "W", "sample_rows": rows}]}
    )
    out = bound(p)
    assert "rows" not in out["data"]
    assert "sample_rows" not in out["data"]["packs"][0]
    assert out["truncated"] is True
    assert out["omitted"] == {"data.rows": 3, "data.packs[].sample_rows": 3}


def test_lists_capped_at_fifty() -> None:
    p = envelope({"items": list(range(120)), "nested": [{"xs": list(range(60))}] * 2})
    out = bound(p)
    assert out["data"]["items"] == list(range(50))
    assert all(len(n["xs"]) == 50 for n in out["data"]["nested"])
    assert out["truncated"] is True
    assert out["omitted"] == {"data.items": 70, "data.nested[].xs": 20}


def test_oversized_envelope_fits_budget_and_keeps_ids() -> None:
    big = [{"id": i, "text": "y" * 2000} for i in range(50)]
    p = envelope(
        {
            "run_id": "R1",
            "run_folder_id": "F1",
            "refs": [{"path": "a"}],
            "counts": {"n": 50},
            "summary": "short",
            "results": big,
            "blob": "z" * 50_000,
        },
    )
    out = bound(p)
    assert encoded_size(out) <= DEFAULT_MAX_BYTES
    assert (
        out["ok"] is True
        and out["domain"] == "engagement"
        and out["command"] == "history"
    )
    d = out["data"]
    assert (d["run_id"], d["run_folder_id"], d["counts"], d["summary"]) == (
        "R1",
        "F1",
        {"n": 50},
        "short",
    )
    assert d["refs"] == [{"path": "a"}]
    assert out["truncated"] is True
    assert out["omitted"]


def test_tiny_budget_still_bounded() -> None:
    p = envelope(
        {"run_id": "R1", "results": [{"t": "x" * 500}] * 200, "note": "n" * 5000}
    )
    out = bound(p, max_bytes=600)
    assert encoded_size(out) <= 600
    assert out["ok"] is True
    assert out["truncated"] is True


def test_protected_keys_at_top_level_are_kept() -> None:
    p = {
        "ok": False,
        "domain": "engagement",
        "command": "deliver",
        "run_id": "R",
        "errors": [{"code": "STORAGE_UNAVAILABLE"}],
        "junk": "j" * 40_000,
    }
    out = bound(p)
    assert encoded_size(out) <= DEFAULT_MAX_BYTES
    assert out["run_id"] == "R" and out["ok"] is False
    assert out["errors"] == [{"code": "STORAGE_UNAVAILABLE"}]


def test_non_json_values_are_stringified() -> None:
    class Thing:
        def __str__(self) -> str:
            return "thing"

    out = bound({"ok": True, "v": Thing(), "t": (1, 2)})
    assert out["v"] == "thing"
    assert out["t"] == [1, 2]


def test_input_is_not_mutated() -> None:
    p = envelope({"items": list(range(100))})
    bound(p)
    assert len(p["data"]["items"]) == 100


def test_short_scalar_lists_survive_the_recaps() -> None:
    """A definition list like ``failed_states`` cut to one item reads as a different
    definition (``["FAILED"]`` hid ERROR, most of the failures) and saves almost
    nothing, so the re-caps keep short scalar lists whole."""
    states = ["FAILED", "ERROR", "TIMED_OUT", "TIMEDOUT"]
    p = envelope(
        {
            "run_id": "r",
            "summary": {"facts": {"job_reliability": {"failed_states": states}}},
            "big": [{"name": f"item-{i}", "pad": "x" * 1000} for i in range(200)],
        }
    )
    out = bound(p, max_bytes=4_000)
    assert encoded_size(out) <= 4_000
    assert out["data"]["summary"]["facts"]["job_reliability"]["failed_states"] == states
    assert "data.summary.facts.job_reliability.failed_states" not in out["omitted"]
