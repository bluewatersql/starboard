"""P2-G14 exit test 1 - policy instrumentation over the full writer loop.

gather (``starboard --discover``) -> discovery -> review score -> verify run -> notebook render -> charts render ->
run recur -> run check -> engagement commit -> report -> approve -> receipt ->
deliver (host artifacts via ``engagement put``), all in-process through each CLI's ``main(argv)``:

* covered: every step leaves an empty sandbox diff, the write guard records zero
  refused writes, stdout is one compact JSON line <= 24 000 B, and every artifact
  lands in the fake Drive with a verified md5; a second run selects the first as
  its baseline.
* public (no overlay): the same writers keep their local outputs.
* internal-only local: the ``analysis/run-authorization.json`` exemption writes
  locally with no refusal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.write_guard import refused_events, sandbox_diff

from ..test_notebook_helper import _backlog
from ..test_run_check import _make_run
from ..test_verify_helper import _TEMPLATES
from ._support import (
    CHART_ROWS,
    PREFLIGHT,
    REVIEW_ROWS,
    WS,
    GatherEngine,
    assert_refs_verified,
    discovery,
    drive_tree,
    eng,
    error_code,
    helper,
    manifest,
    ok,
    put,
    review,
    run_sink,
    starboard,
)

VERIFY_ARGS = ("--ws", WS, "--start", "2026-09-01", "--end", "2026-09-30",
               "--warehouse-id", "wh-1")
SEP = {"start": "2026-09-01", "end": "2026-09-30"}
OCT = {"start": "2026-10-01", "end": "2026-10-31"}


@dataclass
class Loop:
    """The record of one covered run through every writer."""

    rf: str
    run_id: str
    steps: list[tuple[str, int, str]] = field(default_factory=list)
    diffs: list[tuple[str, list]] = field(default_factory=list)
    refused: list[tuple[str, tuple]] = field(default_factory=list)

    def code(self, name: str) -> int:
        return next(c for n, c, _ in self.steps if n == name)

    def data(self, name: str) -> dict[str, Any]:
        raw = next(r for n, _, r in self.steps if n == name)
        return json.loads(raw.splitlines()[-1]).get("data") or {}


def _templates(tmp_path: Path) -> str:
    path = tmp_path / "verify-sql.md"
    path.write_text(_TEMPLATES, encoding="utf-8")
    return str(path)


def _seed_host_artifacts(capsys, monkeypatch, rf: str, nb_root: Path, window: dict) -> None:
    """Host-authored inputs, uploaded with ``engagement put`` (bytes on stdin)."""
    backlog = {**_backlog(), "facts_window": window}
    files: dict[str, Any] = {
        "raw/rows.json": REVIEW_ROWS,
        "charts/data/spend.json": CHART_ROWS,
        "analysis/backlog.json": backlog,
    }
    for p in sorted((nb_root / "analysis" / "verify").glob("*")):
        files[p.relative_to(nb_root).as_posix()] = p.read_bytes()
    put(capsys, monkeypatch, rf, files)


def _seed_checklist(capsys, monkeypatch, store, rf: str, tmp_path: Path, window: dict) -> None:
    """The host-authored rest of a conformant run tree (README, domain analyses, the
    final backlog) via ``engagement put``; writer outputs are never overwritten."""
    src = tmp_path / f"check-src-{rf}"
    src.mkdir()
    rd = _make_run(src)
    present = set(run_sink(store, rf).list(""))
    skip = {"analysis/run-authorization.json", "analysis/backlog.json", "discovery.json"}
    files: dict[str, Any] = {
        rel: p.read_bytes()
        for p in sorted(rd.rglob("*"))
        if p.is_file()
        and (rel := p.relative_to(rd).as_posix()) not in present
        and rel not in skip
    }
    if "README.md" in present:
        # run recur upserted README ``## Recur``; the host puts the whole README
        # back, keeping that section (as the skills say).
        sink = run_sink(store, rf)
        recur = sink.get_bytes("README.md").decode().split("## Recur", 1)[1]
        host = (rd / "README.md").read_text().split("## Recur", 1)[0].rstrip("\n")
        files["README.md"] = f"{host}\n\n## Recur{recur}".encode()
    final = json.loads((rd / "analysis" / "backlog.json").read_text())
    files["analysis/backlog.json"] = {**final, "facts_window": window}
    put(capsys, monkeypatch, rf, files)


def _routed_action_plan(capsys) -> tuple[dict, dict]:
    """``routed`` with an ``action_plan`` preflight: the loop writes the full
    action-plan checklist, so ``run check`` gates it on that profile."""
    argv = list(PREFLIGHT)
    argv[argv.index("--task") + 1] = "action_plan"
    pre = ok(capsys, *argv)
    ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
    return pre, ok(capsys, "route", "--run-id", pre["run_id"])


def run_loop(
    capsys, monkeypatch, store, sandbox, tmp_path: Path, nb_root: Path, *,
    window: dict = SEP, publish: bool = True,
) -> Loop:
    """One covered run: route, every writer, commit, publication."""
    before = sandbox.snapshot()
    pre, route = _routed_action_plan(capsys)
    loop = Loop(route["run_folder_id"], pre["run_id"])
    rf = loop.rf
    templates = _templates(tmp_path)

    def mark(name: str) -> None:
        loop.diffs.append((name, sandbox_diff(before, sandbox.snapshot())))
        loop.refused.append((name, refused_events()))

    def step(name: str, result: tuple[int, dict, str]) -> None:
        code, _env, raw = result
        loop.steps.append((name, code, raw))
        mark(name)

    mark("route")
    monkeypatch.setattr(GatherEngine, "window", window)  # the month this run measured
    _seed_host_artifacts(capsys, monkeypatch, rf, nb_root, window)
    mark("put_inputs")
    step("gather", starboard(capsys, "--discover", "--profile", "acme", "--run-folder", rf,
                             "--data-only", "--json", "--out-dir", "discovery"))
    step("discovery", discovery(capsys, "run", "--data-only", "--out-dir",
                                "helper-discovery", "--run-folder", rf))
    step("review", review(capsys, "score", "--run-folder", rf, "--rows", "raw/rows.json",
                          "--workspace", "acme"))
    step("verify", helper(capsys, "verify", "run", "vt-product-totals", "--templates",
                          templates, *VERIFY_ARGS, "--run-folder", rf))
    step("notebook", helper(capsys, "notebook", "render", "--all", "--source-templates",
                            str(nb_root / "source.md"), "--run-folder", rf))
    step("charts", helper(capsys, "charts", "render", "--kind", "spend-by-product",
                          "--data", "charts/data/spend.json", "--out",
                          "deliverables/charts/spend.png", "--run-folder", rf))
    step("recur", helper(capsys, "run", "recur", "--run-folder", rf))
    _seed_checklist(capsys, monkeypatch, store, rf, tmp_path, window)
    mark("put_checklist")
    step("run_check", helper(capsys, "run", "check", "--run-folder", rf))
    for stage in ("capture", "analysis", "check"):
        step(f"commit_{stage}", eng(capsys, "commit", "--run-folder", rf, "--stage", stage))
    if publish:
        _publish(capsys, monkeypatch, store, loop, step)
    return loop


def _publish(capsys, monkeypatch, store, loop: Loop, step) -> None:
    rf = loop.rf
    put(capsys, monkeypatch, rf, {"deliverables/report.md": "# Acme cost review\n"})
    # The skill commits the check stage before ``report`` (it binds committed bytes only).
    code, _env, raw = eng(capsys, "commit", "--run-folder", rf, "--stage", "check")
    assert code == 0, raw
    ev = json.loads(run_sink(store, rf).get_bytes("evidence/index.json"))
    customer = next(e["evidence_id"] for e in ev if e["source_kind"] == "customer_workspace")
    flags = ("--run-folder", rf, "--report-id", "cost-review", "--revision", "1")
    step("report", eng(capsys, "report", "--run-folder", rf, "--report-id", "cost-review",
                       "--audience", "customer", "--path", "deliverables/report.md",
                       "--cite-evidence", customer))
    step("approve", eng(capsys, "approve", *flags))
    step("receipt_slack", eng(capsys, "receipt", *flags, "--channel", "slack",
                              "--external-object-id", "p123", "--destination-id", "C0123"))
    dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
    step("deliver", eng(capsys, "deliver", *flags, "--destination-folder-id", dest))


WRITERS = ("gather", "discovery", "review", "verify", "notebook", "charts", "recur", "run_check",
           "commit_capture", "commit_analysis", "commit_check", "report", "approve",
           "receipt_slack", "deliver")


@pytest.fixture
def covered_loop(capsys, monkeypatch, store, sandbox, tmp_path, run_dir) -> Loop:
    return run_loop(capsys, monkeypatch, store, sandbox, tmp_path, run_dir)


@pytest.mark.unit
class TestCoveredLoop:
    """Spec P2-G14 item 1 (covered): Drive-only, nothing local, nothing refused."""

    def test_every_writer_exits_zero(self, covered_loop: Loop) -> None:
        assert [(n, c) for n, c, _ in covered_loop.steps] == [(n, 0) for n in WRITERS], [
            (n, r[:300]) for n, c, r in covered_loop.steps if c != 0
        ]

    def test_every_step_leaves_an_empty_sandbox_diff(self, covered_loop: Loop) -> None:
        assert [(n, d) for n, d in covered_loop.diffs if d] == []

    def test_the_write_guard_refuses_nothing(self, covered_loop: Loop) -> None:
        assert [(n, r) for n, r in covered_loop.refused if r] == []

    def test_every_stdout_is_one_compact_line_within_budget(self, covered_loop: Loop) -> None:
        for name, _code, raw in covered_loop.steps:
            assert len(raw.encode("utf-8")) <= 24_000, name
            assert raw.count("\n") == 1 and "\n  " not in raw, name

    def test_every_writer_output_is_in_drive(self, covered_loop: Loop, store) -> None:
        tree = drive_tree(store, covered_loop.rf)
        for rel in (
            "discovery/discovery.json", "discovery/raw/billing.json", "discovery/facts.json",
            "helper-discovery/raw/billing.json", "helper-discovery/facts.json",
            "evidence/index.json",
            "analysis/review.json", "findings-manifest.json",
            "analysis/verify/vt-product-totals.sql", "analysis/verify/vt-product-totals.json",
            "deliverables/charts/spend.png", "analysis/observations.json",
            "analysis/baseline-selection.json", "analysis/recur-result.json",
            "analysis/run-check.json",
        ):
            assert rel in tree, rel
        assert any(r.startswith("deliverables/notebooks/") for r in tree)

    def test_every_committed_ref_has_a_verified_md5(self, covered_loop: Loop, store) -> None:
        assert_refs_verified(store, covered_loop.rf)
        refs = {r.path for r in manifest(store, covered_loop.rf).refs}
        assert {"discovery/discovery.json", "helper-discovery/raw/billing.json",
                "analysis/review.json", "deliverables/charts/spend.png"} <= refs

    def test_receipt_completes_publication_and_slack_does_not(
        self, covered_loop: Loop, store
    ) -> None:
        assert covered_loop.data("receipt_slack")["verified"] is False
        assert covered_loop.data("receipt_slack")["state"] != "delivered"
        assert covered_loop.data("deliver")["state"] == "delivered"
        m = manifest(store, covered_loop.rf)
        assert m.states["publication"] == "complete"
        assert covered_loop.data("deliver")["receipt_id"] in m.receipts

    def test_run_two_selects_run_one_as_its_baseline(
        self, covered_loop: Loop, capsys, monkeypatch, store, sandbox, tmp_path, run_dir
    ) -> None:
        two = run_loop(capsys, monkeypatch, store, sandbox, tmp_path, run_dir, window=OCT,
                       publish=False)
        assert two.run_id != covered_loop.run_id
        recur = two.data("recur")
        assert recur["baseline"] is False and recur["candidates"] >= 1
        sel = json.loads(run_sink(store, two.rf).get_bytes("analysis/baseline-selection.json"))
        prior_ids = {
            o["observation_id"]
            for o in json.loads(
                run_sink(store, covered_loop.rf).get_bytes("analysis/observations.json")
            )
        }
        picked = [r["baseline_observation_id"] for r in sel["selected"]
                  if r.get("baseline_observation_id")]
        assert picked and set(picked) <= prior_ids
        history = ok(capsys, "history", "--run-folder", two.rf)
        assert history["candidates"] >= 1
        assert {r["baseline_observation_id"] for r in history["selected"]
                if r.get("baseline_observation_id")} <= prior_ids


@pytest.mark.unit
class TestPublicLoop:
    """Spec P2-G14 item 1 (public): no overlay - identical writers land locally."""

    def test_public_writers_keep_their_local_outputs(
        self, public, capsys, store, tmp_path, run_dir
    ) -> None:
        out = tmp_path / "pub"
        code, _, raw = discovery(capsys, "run", "--data-only", "--out-dir", str(out / "disc"))
        assert code == 0, raw
        assert (out / "disc" / "raw" / "billing.json").is_file()
        rows = tmp_path / "rows.json"
        rows.write_text(json.dumps(REVIEW_ROWS))
        code, env, raw = review(capsys, "score", "--rows", str(rows), "--workspace", "acme")
        assert code == 0, raw
        code, _, raw = helper(capsys, "verify", "run", "vt-product-totals", "--templates",
                              _templates(tmp_path), *VERIFY_ARGS, "--out",
                              str(out / "verify"))
        assert code == 0, raw
        assert (out / "verify" / "vt-product-totals.json").is_file()
        data = tmp_path / "spend.json"
        data.write_text(json.dumps(CHART_ROWS))
        code, _, raw = helper(capsys, "charts", "render", "--kind", "spend-by-product",
                              "--data", str(data), "--out", str(out / "spend.png"))
        assert code == 0, raw
        assert (out / "spend.png").read_bytes() == b"\x89PNG-fake"
        code, _, raw = helper(capsys, "notebook", "render", "--all", "--backlog",
                              str(run_dir / "analysis" / "backlog.json"), "--run-dir",
                              str(run_dir), "--source-templates", str(run_dir / "source.md"),
                              "--out", str(out / "nbs"))
        assert code == 0, raw
        assert any((out / "nbs").glob("*.py"))
        assert refused_events() == ()
        assert store.object_count == 1

    def test_public_preflight_is_local(self, public, capsys, store) -> None:
        from ._support import PREFLIGHT

        pre = ok(capsys, *PREFLIGHT)
        assert pre["destination"] == "local" and pre["covered"] is False
        assert Path(pre["local_run_dir"]).is_dir()
        assert store.object_count == 1


@pytest.mark.unit
class TestInternalOnlyLocal:
    """Spec P2-G14 item 1 (internal-only local): the run-authorization exemption."""

    def _local_run(self, capsys) -> Path:
        pre = ok(capsys, "preflight", "--source-mode", "internal_only", "--task", "discovery",
                 "--task-name", "ws-123", "--account-key", "001ABC", "--account-name",
                 "Acme Corp", "--storage", "local", "--internal-workspace-id", "123")
        assert pre["storage_decision"] == "internal_only_local"
        run_dir = Path(pre["local_run_dir"])
        ok(capsys, "route", "--run-dir", str(run_dir))
        assert (run_dir / "analysis" / "run-authorization.json").is_file()
        return run_dir

    def test_internal_only_local_writers_write_locally_without_refusal(
        self, capsys, store, tmp_path
    ) -> None:
        local = self._local_run(capsys)
        rows = local / "raw" / "rows.json"
        rows.parent.mkdir(parents=True, exist_ok=True)
        rows.write_text(json.dumps(REVIEW_ROWS))
        code, _, raw = review(capsys, "score", "--rows", str(rows), "--workspace", "acme",
                              "--run-dir", str(local))
        assert code == 0, raw
        data = local / "charts" / "spend.json"
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text(json.dumps(CHART_ROWS))
        code, _, raw = helper(capsys, "charts", "render", "--kind", "spend-by-product",
                              "--data", str(data), "--out", str(local / "spend.png"))
        assert code == 0, raw
        assert (local / "spend.png").read_bytes() == b"\x89PNG-fake"
        assert refused_events() == ()
        assert store.object_count == 1

    def test_discovery_is_never_exempt_on_an_overlay_install(self, capsys, store) -> None:
        """Discovery acquires customer data, so the local descriptor does not exempt it."""
        local = self._local_run(capsys)
        code, env, _ = discovery(capsys, "run", "--data-only", "--authorization",
                                 str(local), "--out-dir", str(local / "discovery"))
        assert code == 2
        assert error_code(env) == "LOCAL_STORAGE_REFUSED"
        assert not (local / "discovery").exists()
        assert store.object_count == 1
