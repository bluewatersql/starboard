"""Run-5 Group B fixes to ``engagement read`` and engagement argument errors (B1, B2).

* B1: ``--jsonpath`` returns ``data.excerpt`` as a JSON *object* keyed by
  expression. Over the budget each expression's value is cut to a valid
  prefix (never mid-JSON) and named in ``truncated_paths``.
* B2: an engagement argument error (e.g. many ``--jsonpath`` flags passed as
  one shell word) is a USAGE envelope (exit 2) for the engagement domain, not
  the generic exit-4 envelope; more than 50 expressions is USAGE naming the cap.
"""

from __future__ import annotations

from typing import Any

from starboard_core.engagement.stdout_budget import encoded_size

from . import test_engagement_helper_phase2 as phase2
from .test_engagement_helper_phase2 import ok, routed, run, run_sink

store, ws, sandbox = phase2.store, phase2.ws, phase2.sandbox

DOC = {
    "items": [{"id": i, "name": f"job-{i:03d}", "note": "x" * 40} for i in range(200)],
    "meta": {"n": 200, "label": "small"},
    "text": "y" * 5000,
}


def _put(store: Any, capsys: Any) -> str:
    _, data = routed(capsys)
    rf = data["run_folder_id"]
    run_sink(store, rf).put_json("capture/doc.json", DOC)
    return rf


def _read(capsys: Any, rf: str, *flags: str) -> dict[str, Any]:
    return ok(capsys, "read", "--run-folder", rf, "--path", "capture/doc.json", *flags)


class TestExcerptIsAnObject:
    def test_keyed_object_not_a_string(self, capsys, store):
        rf = _put(store, capsys)
        out = _read(capsys, rf, "--jsonpath", "meta.n", "--jsonpath", "meta.label")
        assert out["excerpt"] == {"meta.n": 200, "meta.label": "small"}
        assert out["truncated"] is False and out["truncated_paths"] == []

    def test_plain_read_stays_text(self, capsys, store):
        rf = _put(store, capsys)
        out = _read(capsys, rf, "--max-bytes", "64")
        assert isinstance(out["excerpt"], str)
        assert out["truncated_paths"] == []

    def test_over_budget_cuts_per_expression(self, capsys, store):
        rf = _put(store, capsys)
        code, env, raw = run(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "capture/doc.json",
            "--jsonpath",
            "items",
            "--jsonpath",
            "meta",
            "--max-bytes",
            "3000",
        )
        assert code == 0, raw
        assert "omitted" not in env and "truncated" not in env  # envelope intact
        out = env["data"]
        excerpt = out["excerpt"]
        assert isinstance(excerpt, dict) and list(excerpt) == ["items", "meta"]
        assert excerpt["meta"] == DOC["meta"]  # the small slice is whole
        items = excerpt["items"]
        assert 0 < len(items) < 50 and items == DOC["items"][: len(items)]
        assert out["truncated"] is True and out["truncated_paths"] == ["items"]
        assert encoded_size(excerpt) <= 3000

    def test_long_string_is_a_string_prefix(self, capsys, store):
        rf = _put(store, capsys)
        out = _read(capsys, rf, "--jsonpath", "text", "--max-bytes", "500")
        text = out["excerpt"]["text"]
        assert isinstance(text, str) and 0 < len(text) < 5000
        assert DOC["text"].startswith(text)
        assert out["truncated_paths"] == ["text"]

    def test_list_over_fifty_is_capped_and_named(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_json("capture/doc.json", {"ids": list(range(80))})
        code, env, raw = run(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "capture/doc.json",
            "--jsonpath",
            "ids",
        )
        assert code == 0, raw
        assert "omitted" not in env
        assert env["data"]["excerpt"]["ids"] == list(range(50))
        assert env["data"]["truncated_paths"] == ["ids"]

    def test_tiny_budget_drops_the_slice_and_names_it(self, capsys, store):
        rf = _put(store, capsys)
        out = _read(capsys, rf, "--jsonpath", "meta", "--max-bytes", "8")
        assert out["excerpt"] == {} and out["truncated_paths"] == ["meta"]
        assert out["truncated"] is True

    def test_full_cap_envelope_is_never_rebounded(self, capsys, store):
        """At the default cap, the excerpt leaves room for the rest of the envelope."""
        rf = _put(store, capsys)
        flags = [f for i in range(40) for f in ("--jsonpath", f"items.{i}")]
        code, env, raw = run(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "capture/doc.json",
            "--jsonpath",
            "text",
            "--jsonpath",
            "items",
            *flags,
        )
        assert code == 0, raw
        assert "omitted" not in env and "truncated" not in env
        assert len(env["data"]["jsonpaths"]) == 42
        assert len(env["data"]["excerpt"]) == 42
        assert env["data"]["truncated"] is True
        assert len(raw.strip().encode("utf-8")) <= 24_000


class TestArgumentErrors:
    def test_one_word_jsonpath_list_is_usage(self, capsys, store):
        rf = _put(store, capsys)
        code, env, _ = run(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "capture/doc.json",
            "--jsonpath meta.n --jsonpath meta.label",  # zsh: unquoted $args
        )
        assert code == 2
        assert env["ok"] is False and env["domain"] == "engagement"
        assert env["command"] == "read"
        err = env["errors"][0]
        assert err["code"] == "USAGE" and err["retryable"] is False
        assert "unrecognized arguments" in err["message"]
        assert "one shell word" in err["message"]

    def test_missing_required_flag_is_usage(self, capsys, store):
        code, env, _ = run(capsys, "read", "--path", "capture/doc.json", "--bogus")
        assert code == 2 and env["errors"][0]["code"] == "USAGE"
        assert env["domain"] == "engagement"

    def test_nested_verb_error_is_usage(self, capsys, store):
        code, env, _ = run(capsys, "play", "rank", "--run-folder", "x")
        assert code == 2 and env["errors"][0]["code"] == "USAGE"
        assert env["command"] == "play rank"

    def test_more_than_fifty_jsonpaths_is_usage(self, capsys, store):
        rf = _put(store, capsys)
        flags = [f for i in range(51) for f in ("--jsonpath", f"items.{i}")]
        code, env, _ = run(
            capsys, "read", "--run-folder", rf, "--path", "capture/doc.json", *flags
        )
        assert code == 2 and env["errors"][0]["code"] == "USAGE"
        assert "50" in env["errors"][0]["message"]
