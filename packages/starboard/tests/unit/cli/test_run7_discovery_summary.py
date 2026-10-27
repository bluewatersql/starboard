"""Live run 7: a Drive discovery summary keeps its facts whole.

The 8 KB ``--run-folder`` summary carried every pack's ref and full manifest entry
beside the facts, so on a 28-pack run :func:`bound` re-capped every list, the
facts' included, to zero: ``product_mix``, ``top_jobs`` and ``packs`` printed as
``[]`` while ``facts.json`` was populated. The pack refs and manifest detail
(both re-readable from the run folder) now give way before the facts.
"""

from __future__ import annotations

from typing import Any

import pytest
from starboard.cli.cli import main as cli_main
from starboard_core.engagement.stdout_budget import encoded_size
from starboard_x.discovery.serialize import SUMMARY_PACK_KEYS

pytestmark = pytest.mark.unit

_PACKS = 28


def _payload() -> dict[str, Any]:
    packs = [
        {
            "pack": f"pack_{i:02d}",
            "domain": f"domain_{i:02d}",
            "queries": 4,
            "succeeded": 4,
            "rows_total": 50,
            "truncated": False,
            "limit_reached": False,
            "path": f"raw/pack_{i:02d}.json",
        }
        for i in range(_PACKS)
    ]
    refs = [
        {
            "path": f"discovery/{p['path']}",
            "object_id": f"obj-{i:02d}-" + "x" * 28,
            "size": 12345,
        }
        for i, p in enumerate(packs)
    ] + [
        {"path": f"discovery/{name}", "object_id": "obj-" + "y" * 30, "size": 999}
        for name in ("facts.json", "manifest.json", "discovery.json")
    ]
    facts = {
        "window": {"start": "2026-10-08", "end": "2026-10-14", "days": 7},
        "product_mix": [
            {"product": f"PRODUCT_{i}", "dbus": 1000.0 - i, "share_pct": 4.0}
            for i in range(12)
        ],
        "top_jobs": [
            {"job_id": str(10_000 + i), "dbus": 500.0 - i, "runs": 30}
            for i in range(10)
        ],
        "job_reliability": {"failed_states": ["FAILED", "ERROR", "TIMED_OUT"]},
    }
    return {
        "ok": True,
        "status": "ok",
        "domain": "discovery",
        "command": "discover",
        "counts": {"total": 96, "succeeded": 96, "skipped": 0, "failed": 0},
        "errors": [],
        "run_id": "20261015_run",
        "run_folder_id": "folder",
        "summary": {
            "layout_prefix": "discovery",
            "envelope_path": "discovery/discovery.json",
            "facts": facts,
            "packs": packs,
            "failed": [],
            "packs_with_gaps": {},
        },
        "refs": refs,
        "note": "Rows are in the run folder (refs).",
    }


def test_the_facts_survive_a_many_pack_summary() -> None:
    payload = _payload()
    assert encoded_size(payload) > cli_main._DISCOVERY_SUMMARY_MAX_BYTES
    out = cli_main._fit_discovery_summary(payload)
    assert encoded_size(out) <= cli_main._DISCOVERY_SUMMARY_MAX_BYTES
    assert out["summary"]["facts"] == payload["summary"]["facts"]
    # Every pack is still named, with where its rows are.
    packs = out["summary"]["packs"]
    assert [p["pack"] for p in packs] == [f"pack_{i:02d}" for i in range(_PACKS)]
    assert all(p["path"] and "rows_total" in p for p in packs)
    # The layout files' refs stay; pack refs are counted, not listed.
    assert {r["path"] for r in out["refs"]} == {
        "discovery/facts.json",
        "discovery/manifest.json",
        "discovery/discovery.json",
    }
    assert out["pack_refs_omitted"] == _PACKS


def test_a_small_summary_is_untouched() -> None:
    payload = _payload()
    payload["summary"]["packs"] = payload["summary"]["packs"][:2]
    payload["refs"] = payload["refs"][:2] + payload["refs"][-3:]
    assert cli_main._fit_discovery_summary(payload) == payload


def test_large_facts_compact_the_manifest_and_keep_every_pack() -> None:
    # Run 7's facts were ~3 KB: dropping the pack refs alone was not enough.
    payload = _payload()
    payload["summary"]["facts"]["product_mix"] = [
        {"product": f"PRODUCT_{i}", "dbus": 1000.0 - i, "share_pct": 4.0, "dsu": 12.5}
        for i in range(24)
    ]
    payload["summary"]["facts"]["top_pipelines"] = [
        {"pipeline_id": f"pipe-{i:04d}", "dbus": 90.0 - i} for i in range(10)
    ]
    out = cli_main._fit_discovery_summary(payload)
    assert encoded_size(out) <= cli_main._DISCOVERY_SUMMARY_MAX_BYTES
    assert "truncated" not in out
    assert out["summary"]["facts"] == payload["summary"]["facts"]
    packs = out["summary"]["packs"]
    assert len(packs) == _PACKS
    assert set(packs[0]) == set(SUMMARY_PACK_KEYS)
