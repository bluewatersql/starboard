"""Run-6b fixes to ``engagement history`` and ``engagement read``.

* ``history`` before ``analyze`` (the QBR order of the health review): with no
  observations yet the reporting interval is the captured discovery facts window,
  and the envelope names the source (``reporting_interval_source``).
* ``read --jsonpath`` lists are capped at 50 items: a ``[a:b]`` slice pages past
  them, and ``next_paths`` names the slice that reads the next items.
"""

from __future__ import annotations

from typing import Any

from starboard_skills.helpers import engagement

from . import test_engagement_helper_phase2 as phase2
from .test_engagement_helper_phase2 import (
    observation,
    ok,
    record_json,
    routed,
    run,
    run_sink,
)

store, ws, sandbox = phase2.store, phase2.ws, phase2.sandbox

FACTS = {"window": {"start": "2026-07-01", "end": "2026-09-28"}}


class TestHistoryBeforeAnalyze:
    def test_interval_comes_from_the_facts_window(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_json("discovery/facts.json", FACTS)
        out = ok(capsys, "history", "--run-folder", rf)
        assert out["reporting_interval"] == ["2026-07-01", "2026-09-28"]
        assert out["reporting_interval_source"] == "facts"
        assert out["current_observations"] == 0

    def test_observations_win_over_the_facts_window(self, capsys, store):
        pre, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_json("discovery/facts.json", FACTS)
        record_json(
            run_sink(store, rf),
            engagement.OBSERVATIONS_PATH,
            [observation(pre["run_id"]).to_dict()],
        )
        out = ok(capsys, "history", "--run-folder", rf)
        assert out["reporting_interval"] == ["2026-10-01", "2026-10-31"]
        assert out["reporting_interval_source"] == "observations"

    def test_flags_are_named_as_the_source(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        out = ok(
            capsys,
            "history",
            "--run-folder",
            rf,
            "--interval-start",
            "2026-10-01",
            "--interval-end",
            "2026-10-31",
        )
        assert out["reporting_interval_source"] == "flags"

    def test_no_observations_and_no_facts_is_usage_naming_capture(self, capsys, store):
        _, data = routed(capsys)
        code, env, _ = run(capsys, "history", "--run-folder", data["run_folder_id"])
        assert code == 2
        message = env["errors"][0]["message"]
        assert "--interval-start" in message and "discovery/facts.json" in message


DOC = [{"play_id": f"p{i:03d}", "rank": i} for i in range(148)]


def _doc_run(store: Any, capsys: Any) -> str:
    _, data = routed(capsys)
    rf = data["run_folder_id"]
    record_json(run_sink(store, rf), "analysis/plays.json", DOC)
    return rf


def _read(capsys: Any, rf: str, *exprs: str) -> dict[str, Any]:
    flags = [f for e in exprs for f in ("--jsonpath", e)]
    return ok(
        capsys, "read", "--run-folder", rf, "--path", "analysis/plays.json", *flags
    )


class TestReadPaging:
    def test_star_names_the_next_slice(self, capsys, store):
        rf = _doc_run(store, capsys)
        out = _read(capsys, rf, "$[*].play_id")
        assert out["excerpt"]["$[*].play_id"] == [d["play_id"] for d in DOC[:50]]
        assert out["truncated_paths"] == ["$[*].play_id"]
        assert out["next_paths"] == {"$[*].play_id": "$[50:100].play_id"}

    def test_slices_page_to_the_end(self, capsys, store):
        rf = _doc_run(store, capsys)
        second = _read(capsys, rf, "$[50:100].play_id")
        assert second["excerpt"]["$[50:100].play_id"] == [
            d["play_id"] for d in DOC[50:100]
        ]
        assert second["next_paths"] == {"$[50:100].play_id": "$[100:150].play_id"}
        last = _read(capsys, rf, "$[100:150].play_id")
        assert last["excerpt"]["$[100:150].play_id"] == [
            d["play_id"] for d in DOC[100:]
        ]
        assert last["truncated"] is False and last["next_paths"] == {}

    def test_open_ended_and_negative_slices(self, capsys, store):
        rf = _doc_run(store, capsys)
        out = _read(capsys, rf, "$[140:].rank", "$[-2:].rank")
        assert out["excerpt"] == {
            "$[140:].rank": list(range(140, 148)),
            "$[-2:].rank": [146, 147],
        }

    def test_byte_cut_names_the_next_slice_after_the_kept_items(self, capsys, store):
        rf = _doc_run(store, capsys)
        out = ok(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "analysis/plays.json",
            "--jsonpath",
            "$[*]",
            "--max-bytes",
            "400",
        )
        kept = len(out["excerpt"]["$[*]"])
        assert 0 < kept < 50
        assert out["next_paths"] == {"$[*]": f"$[{kept}:{kept + 50}]"}

    def test_filters_are_still_refused_with_the_paging_hint(self, capsys, store):
        rf = _doc_run(store, capsys)
        code, env, _ = run(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "analysis/plays.json",
            "--jsonpath",
            "$[?(@.rank==1)]",
        )
        assert code == 2 and "[50:100]" in env["errors"][0]["message"]

    def test_a_stepped_slice_is_usage(self, capsys, store):
        rf = _doc_run(store, capsys)
        code, env, _ = run(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "analysis/plays.json",
            "--jsonpath",
            "$[0:10:2]",
        )
        assert code == 2 and "a[50:100]" in env["errors"][0]["message"]
