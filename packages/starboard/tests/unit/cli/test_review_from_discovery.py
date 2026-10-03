# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ``starboard review --from-discovery`` (offline review on saved discovery).

The review evaluates its rules on a saved discovery run's results instead of
re-running the evidence queries: no client is built, no query runs, scope and
lookback are inherited from the discovery output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starboard.cli.cli.review_command import run_review
from starboard.tools.services.discovery_evidence import (
    DiscoveryEvidenceError,
    load_discovery_evidence,
)
from starboard_x.contract import EXIT_ARG, EXIT_NOT_FOUND, EXIT_OK

_WS = "1234567890"


@pytest.fixture(autouse=True)
def _restore_logging():
    """``run_review`` pins structlog/stdlib logging to the (captured) stderr."""
    import logging

    import structlog

    saved = structlog.get_config()
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    structlog.configure(**saved)
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture(autouse=True)
def _no_connection(monkeypatch):
    """Any client / internal-source construction fails the test (offline mode)."""

    def _boom(*_a, **_k):
        raise AssertionError("--from-discovery must not build a client or source")

    monkeypatch.setattr("starboard.bootstrap.AsyncDatabricksClient", _boom)
    monkeypatch.setattr("starboard.bootstrap.resolve_internal_source", _boom)
    monkeypatch.setattr("starboard.bootstrap.get_config", _boom)


def _result(
    qid, *, status="succeeded", rows=None, lookback=30, limit_reached=False, **extra
):
    return {
        **extra,
        "query_id": qid,
        "domain": "x",
        "succeeded": status == "succeeded",
        "status": status,
        "error": None if status == "succeeded" else "statement timed out",
        "row_count": len(rows or []),
        "columns": [],
        "rows": rows or [],
        "truncated": False,
        "row_limit": 50 if limit_reached else None,
        "limit_reached": limit_reached,
        "lookback_days": lookback,
    }


_F01_ROWS = [
    {"billing_origin_product": "JOBS", "usage_unit": "DBU", "usage_quantity": "100.5"},
    {"billing_origin_product": "SQL", "usage_unit": "DBU", "usage_quantity": "20"},
    {"billing_origin_product": "SQL", "usage_unit": "DSU", "usage_quantity": "9"},
]


def _write_run(
    root: Path,
    *,
    raw: bool = True,
    envelope: bool = True,
    workspace_ids=(_WS,),
    lookback: int = 30,
) -> Path:
    """Write a discovery run dir. W-W02 is deliberately absent; C-Q02 skipped."""
    disc = root / "discovery"
    disc.mkdir(parents=True)
    jobs = [
        _result("C-J03", limit_reached=True, rows=[{"job_id": "1"}]),
        _result("C-J04"),
        _result("C-J08"),
        _result("C-J09"),
        _result("C-J10", status="skipped"),  # skipped, but no review rule reads it
    ]
    sql = [_result("C-Q02", status="skipped", lookback=7)]
    wh = [_result("W-W01"), _result("W-W07")]
    facts = [_result("F-01", rows=_F01_ROWS), _result("F-03")]
    packs = {"jobs": jobs, "query_perf": sql, "warehouse": wh, "facts": facts}
    if raw:
        (disc / "raw").mkdir()
        for name, results in packs.items():
            (disc / "raw" / f"{name}.json").write_text(
                json.dumps({"pack": name, "domain": name, "results": results})
            )
    if envelope:
        data = {
            "packs": [
                {"pack": n, "queries": len(r), "results": r} for n, r in packs.items()
            ],
            "source": "internal",
            "scope": {"account": None, "workspace_ids": list(workspace_ids)},
            "lookback_days": lookback,
            "facts": {"window": {"start": "2026-09-01", "end": "2026-09-30"}},
        }
        (disc / "discovery.json").write_text(
            json.dumps({"ok": True, "domain": "discovery", "data": data})
        )
    return disc


def _run(argv, capsys):
    code = run_review(argv)
    captured = capsys.readouterr()
    return code, captured


def _payload(captured) -> dict:
    return json.loads(captured.out)


@pytest.mark.unit
class TestLoader:
    def test_loads_from_raw_with_envelope_provenance(self, tmp_path) -> None:
        ev = load_discovery_evidence(_write_run(tmp_path))
        assert {"C-J03", "C-J04", "C-Q02", "W-W01", "F-01"} <= set(ev.results)
        assert ev.workspace_ids == (_WS,)
        assert ev.lookback_days == 30
        assert ev.source == "internal"
        assert ev.window == {"start": "2026-09-01", "end": "2026-09-30"}
        assert ev.generated_at

    def test_falls_back_to_discovery_json(self, tmp_path) -> None:
        disc = _write_run(tmp_path, raw=False)
        ev = load_discovery_evidence(disc / "discovery.json")
        assert ev.results["C-J03"]["rows"] == [{"job_id": "1"}]
        assert ev.envelope_file == str(disc / "discovery.json")

    def test_raw_only_derives_lookback_from_results(self, tmp_path) -> None:
        ev = load_discovery_evidence(_write_run(tmp_path, envelope=False))
        assert ev.envelope_file is None
        assert ev.workspace_ids == ()
        assert ev.lookback_days == 30  # most common per-query lookback

    def test_accepts_run_dir(self, tmp_path) -> None:
        _write_run(tmp_path)
        assert "C-J03" in load_discovery_evidence(tmp_path).results

    def test_missing_path_errors(self, tmp_path) -> None:
        with pytest.raises(DiscoveryEvidenceError):
            load_discovery_evidence(tmp_path / "nope")

    def test_error_envelope_errors(self, tmp_path) -> None:
        f = tmp_path / "discovery.json"
        f.write_text(json.dumps({"ok": False, "error": "boom"}))
        with pytest.raises(DiscoveryEvidenceError, match="error envelope"):
            load_discovery_evidence(f)


@pytest.mark.unit
class TestFromDiscoveryReview:
    def test_offline_review_degrades_and_records_provenance(
        self, tmp_path, capsys
    ) -> None:
        disc = _write_run(tmp_path)
        manifest = tmp_path / "out" / "manifest.json"
        code, captured = _run(
            ["--from-discovery", str(disc), "--json", "--manifest-out", str(manifest)],
            capsys,
        )
        assert code == EXIT_OK, captured.err
        data = _payload(captured)["data"]

        assert data["workspace"] == f"ws-{_WS}"
        reports = {r["domain"]: r for r in data["domain_reports"]}
        # Skipped in discovery -> degraded exactly like a failed query.
        assert reports["sql"]["degraded"] is True
        assert "C-Q02" in reports["sql"]["degraded_reason"]
        # Absent from discovery output -> degraded with an explicit reason.
        assert reports["warehouse"]["degraded"] is True
        assert "W-W02" in reports["warehouse"]["degraded_reason"]
        assert reports["jobs"]["degraded"] is False

        src = data["evidence_source"]
        assert src["kind"] == "discovery"
        assert src["path"] == str(disc)
        assert src["lookback_days"] == 30
        assert src["discovery_generated_at"]
        rep = data["evidence_report"]
        assert rep["unavailable"]["W-W02"] == "not in discovery output"
        assert rep["unavailable"]["C-Q02"].startswith("skipped in discovery")
        assert rep["limit_reached_query_ids"] == ["C-J03"]
        assert rep["query_lookback_days"]["C-Q02"] == 7

        # A1: degraded + unavailable queries/domains on the review JSON.
        assert data["degraded"] is True
        assert {"C-Q02", "W-W02"} <= set(data["unavailable_queries"])
        assert set(data["unavailable_domains"]) == {"sql", "warehouse"}
        # #7: discovery_skipped lists EVERY skipped query (C-J10 is read by no
        # rule); unavailable_queries only the ones the rules consumed.
        assert data["discovery_skipped"] == ["C-J10", "C-Q02"]
        assert "C-J10" not in data["unavailable_queries"]
        assert data["coverage_note"] == (
            "2 discovery queries skipped; 1 used by review rules (C-Q02) — findings "
            "in those domains are partial; 1 review evidence query failed or missing "
            "in the discovery output (W-W02)."
        )
        # A5: an internal discovery source → workspace-telemetry cost basis.
        assert "workspace telemetry" in data["cost_basis"]

        # F-01 still feeds products_dbu (DBU only; DSU dropped).
        assert data["products_dbu"] == {"JOBS": 100.5, "SQL": 20.0}

        written = json.loads(manifest.read_text())
        assert written["evidence_source"]["kind"] == "discovery"
        assert written["degraded"] is True
        assert written["unavailable_queries"] == data["unavailable_queries"]
        assert written["unavailable_domains"] == data["unavailable_domains"]
        assert "workspace telemetry" in written["cost_basis"]
        assert written["workspace_id"] == _WS
        assert written["lookback_days"] == 30
        assert written["products_dbu"] == {"JOBS": 100.5, "SQL": 20.0}
        assert written["discovery_skipped"] == data["discovery_skipped"]
        assert written["coverage_note"] == data["coverage_note"]

    def test_manifest_with_evidence_source_round_trips_as_since(
        self, tmp_path, capsys
    ) -> None:
        disc = _write_run(tmp_path)
        manifest = tmp_path / "m.json"
        code, _ = _run(
            ["--from-discovery", str(disc), "--json", "--manifest-out", str(manifest)],
            capsys,
        )
        assert code == EXIT_OK
        code, captured = _run(
            ["--from-discovery", str(disc), "--json", "--since", str(manifest)],
            capsys,
        )
        assert code == EXIT_OK, captured.err
        assert "cost_delta" in _payload(captured)["data"]

    def test_workspace_mismatch_is_hard_error(self, tmp_path, capsys) -> None:
        disc = _write_run(tmp_path)
        code, captured = _run(
            [
                "--from-discovery",
                str(disc),
                "--internal-workspace-id",
                "999",
                "--json",
            ],
            capsys,
        )
        assert code == EXIT_ARG
        payload = _payload(captured)
        assert payload["ok"] is False
        assert "does not match" in payload["error"]

    def test_matching_workspace_id_is_accepted_offline(self, tmp_path, capsys) -> None:
        disc = _write_run(tmp_path)
        code, captured = _run(
            ["--from-discovery", str(disc), "--internal-workspace-id", _WS, "--json"],
            capsys,
        )
        assert code == EXIT_OK, captured.err

    def test_lookback_mismatch_warns_and_uses_discovery(
        self, tmp_path, capsys
    ) -> None:
        disc = _write_run(tmp_path)
        manifest = tmp_path / "m.json"
        code, captured = _run(
            [
                "--from-discovery",
                str(disc),
                "--lookback-days",
                "7",
                "--json",
                "--manifest-out",
                str(manifest),
            ],
            capsys,
        )
        assert code == EXIT_OK
        assert "differs from" in captured.err
        src = _payload(captured)["data"]["evidence_source"]
        assert src["lookback_days"] == 30
        assert src["requested_lookback_days"] == 7
        assert json.loads(manifest.read_text())["lookback_days"] == 30

    def test_missing_discovery_dir_is_not_found(self, tmp_path, capsys) -> None:
        code, captured = _run(
            ["--from-discovery", str(tmp_path / "nope"), "--json"], capsys
        )
        assert code == EXIT_NOT_FOUND
        assert _payload(captured)["ok"] is False

    def test_public_raw_only_uses_workspace_label(self, tmp_path, capsys) -> None:
        disc = _write_run(tmp_path, envelope=False)
        code, captured = _run(
            ["--from-discovery", str(disc), "--workspace", "my-prof", "--json"],
            capsys,
        )
        assert code == EXIT_OK, captured.err
        data = _payload(captured)["data"]
        assert data["workspace"] == "my-prof"
        assert data["evidence_source"]["envelope_file"] is None


_VARIANCE_ROWS = [
    {"job_id": f"j{i}", "total_runs": 10, "max_min_ratio": 10.0 + i} for i in range(3)
]


def _write_variance_run(root: Path, *, source: str | None = "internal") -> Path:
    """A minimal run: C-J03 capped (fires variance), C-J04 timed out + retried."""
    disc = root / "discovery"
    (disc / "raw").mkdir(parents=True)
    results = [
        _result("C-J03", rows=_VARIANCE_ROWS, limit_reached=True),
        _result("C-J04", status="failed", attempts=2),
        _result("C-J08"),
        _result("C-J09"),
        _result("F-03"),
    ]
    (disc / "raw" / "jobs.json").write_text(
        json.dumps({"pack": "jobs", "domain": "jobs", "results": results})
    )
    if source is not None:
        (disc / "discovery.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "data": {
                        "packs": [],
                        "source": source,
                        "scope": {"account": None, "workspace_ids": [_WS]},
                        "lookback_days": 30,
                    },
                }
            )
        )
    return disc


@pytest.mark.unit
class TestRound4ReviewContract:
    def test_capped_evidence_marks_findings_and_attempts_surface(
        self, tmp_path, capsys
    ) -> None:
        disc = _write_variance_run(tmp_path)
        manifest = tmp_path / "m.json"
        code, captured = _run(
            [
                "--from-discovery", str(disc), "--domains", "jobs", "--json",
                "--manifest-out", str(manifest),
            ],
            capsys,
        )
        assert code == EXIT_OK, captured.err
        data = _payload(captured)["data"]
        assert data["finding_count"] == 3
        assert all(f["metadata"]["evidence_capped"] for f in data["findings"])
        assert data["evidence_report"]["query_attempts"] == {"C-J04": 2}
        assert data["unavailable_queries"] == ["C-J04"]
        assert data["unavailable_domains"] == ["jobs"]
        records = json.loads(manifest.read_text())["findings"]
        assert all(r["evidence_capped"] for r in records)
        # review.json findings carry the manifest's entity_id / composite_key.
        by_key = {r["composite_key"]: r for r in records}
        for f in data["findings"]:
            assert f["entity_id"] == f["finding"]["location"]["entity"]
            assert by_key[f["composite_key"]]["entity_id"] == f["entity_id"]

    def test_public_source_keeps_public_cost_basis(self, tmp_path, capsys) -> None:
        from starboard_core.domain.models.review import COST_BASIS_LABEL

        disc = _write_variance_run(tmp_path, source=None)
        code, captured = _run(
            ["--from-discovery", str(disc), "--domains", "jobs", "--json"], capsys
        )
        assert code == EXIT_OK, captured.err
        assert _payload(captured)["data"]["cost_basis"] == COST_BASIS_LABEL

    def test_out_writes_envelope_and_prints_one_line_summary(
        self, tmp_path, capsys
    ) -> None:
        disc = _write_variance_run(tmp_path)
        out = tmp_path / "nested" / "review.json"
        code, captured = _run(
            ["--from-discovery", str(disc), "--domains", "jobs", "--out", str(out)],
            capsys,
        )
        assert code == EXIT_OK, captured.err
        lines = captured.out.strip().splitlines()
        assert len(lines) == 1
        summary = json.loads(lines[0])
        assert summary == {
            "ok": True,
            "out": str(out),
            "finding_count": 3,
            "degraded": True,
        }
        written = json.loads(out.read_text())
        assert written["ok"] is True
        assert written["data"]["finding_count"] == 3

    def test_out_on_error_writes_error_envelope(self, tmp_path, capsys) -> None:
        out = tmp_path / "review.json"
        code, captured = _run(
            ["--from-discovery", str(tmp_path / "nope"), "--out", str(out)], capsys
        )
        assert code == EXIT_NOT_FOUND
        summary = json.loads(captured.out.strip())
        assert summary["ok"] is False and summary["out"] == str(out)
        assert json.loads(out.read_text())["ok"] is False

    def test_workspace_id_label_mismatch_is_hard_error(
        self, tmp_path, capsys
    ) -> None:
        disc = _write_variance_run(tmp_path)
        code, captured = _run(
            ["--from-discovery", str(disc), "--workspace", "ws-42", "--json"], capsys
        )
        assert code == EXIT_ARG
        assert "does not match" in _payload(captured)["error"]
