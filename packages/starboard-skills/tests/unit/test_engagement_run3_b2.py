"""Run-3 fixes to the ``engagement`` verbs (B2-1, B2-2, B2-7, B2-8).

* ``read``: the default excerpt is the cap (no warning); ``--offset`` pages a
  text artifact; ``--jsonpath`` repeats (one download, every slice).
* A folder name owned by another account key is ``ACCOUNT_NAME_TAKEN`` (exit 2)
  naming that key, with no merge advice; a name-like ``--account-key`` warns.
* ``--task-name workspace-<id>`` is USAGE with the ``ws-<id>`` hint.
* A transient Drive failure is ``STORAGE_TRANSIENT`` (exit 8, ``retryable``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from starboard_core.engagement import stdout_budget
from starboard_core.ports.engagement_storage import StorageTransientError
from starboard_skills.helpers import engagement
from starboard_skills.helpers.contract import ApiError, ArgError
from starboard_skills.helpers.engagement import _envelope

from . import test_engagement_helper_phase2 as phase2
from .test_engagement_helper_phase2 import PREFLIGHT, ok, routed, run, run_sink

# The phase-2 autouse fixtures (fake Drive store, workspace, write sandbox).
store, ws, sandbox = phase2.store, phase2.ws, phase2.sandbox

BIG = "capture/big.txt"


def _preflight(**over: str) -> tuple[str, ...]:
    flags = list(PREFLIGHT)
    for flag, value in over.items():
        flags[flags.index(f"--{flag.replace('_', '-')}") + 1] = value
    return tuple(flags)


def _put(store: Any, capsys: Any, rel: str, text: str) -> str:
    _, data = routed(capsys)
    rf = data["run_folder_id"]
    run_sink(store, rf).put_text(rel, text)
    return rf


# --------------------------------------------------------------------------- #
# B2-1: read
# --------------------------------------------------------------------------- #
class TestReadDefaults:
    def test_default_is_the_cap(self):
        assert engagement.DEFAULT_READ_BYTES == (
            stdout_budget.DEFAULT_MAX_BYTES - _envelope._ENVELOPE_RESERVE
        )

    def test_plain_read_does_not_warn(self, capsys, store):
        rf = _put(store, capsys, BIG, "x" * 100_000)
        code, env, raw = run(capsys, "read", "--run-folder", rf, "--path", BIG)
        assert code == 0 and env["warnings"] == [] and env["data"]["warnings"] == []
        assert len(env["data"]["excerpt"]) <= engagement.DEFAULT_READ_BYTES
        assert len(raw.encode()) <= stdout_budget.DEFAULT_MAX_BYTES

    def test_explicit_larger_max_bytes_warns(self, capsys, store):
        rf = _put(store, capsys, BIG, "x" * 100_000)
        out = ok(
            capsys, "read", "--run-folder", rf, "--path", BIG, "--max-bytes", "100000"
        )
        assert out["warnings"] and "read cap" in out["warnings"][0]


class TestReadOffset:
    def _pages(self, capsys, rf: str, *extra: str) -> list[dict[str, Any]]:
        pages, offset = [], 0
        while True:
            code, env, raw = run(
                capsys,
                "read", "--run-folder", rf, "--path", BIG, "--offset", str(offset),
                *extra,
            )
            assert code == 0, raw
            assert len(raw.encode()) <= stdout_budget.DEFAULT_MAX_BYTES
            page = env["data"]
            assert page["offset"] == offset
            pages.append(page)
            if page["next_offset"] is None:
                assert page["truncated"] is False
                return pages
            assert page["truncated"] is True and page["next_offset"] > offset
            offset = page["next_offset"]

    def test_pages_cover_the_file_exactly(self, capsys, store):
        text = "".join(f"line {i}\n" for i in range(8_000))
        rf = _put(store, capsys, BIG, text)
        pages = self._pages(capsys, rf)
        assert len(pages) > 1
        assert "".join(p["excerpt"] for p in pages) == text

    def test_pages_never_split_a_character(self, capsys, store):
        text = "é€😀a" * 400
        rf = _put(store, capsys, BIG, text)
        pages = self._pages(capsys, rf, "--max-bytes", "64")
        assert len(pages) > 10
        assert "".join(p["excerpt"] for p in pages) == text
        assert all("�" not in p["excerpt"] for p in pages)

    def test_offset_past_the_end_is_usage(self, capsys, store):
        rf = _put(store, capsys, BIG, "short")
        code, env, _ = run(
            capsys, "read", "--run-folder", rf, "--path", BIG, "--offset", "5"
        )
        assert code == 2 and env["errors"][0]["code"] == "USAGE"
        assert "past the end" in env["errors"][0]["message"]

    def test_negative_offset_is_usage(self, capsys, store):
        rf = _put(store, capsys, BIG, "short")
        code, env, _ = run(
            capsys, "read", "--run-folder", rf, "--path", BIG, "--offset", "-1"
        )
        assert code == 2 and env["errors"][0]["code"] == "USAGE"

    def test_offset_with_jsonpath_is_usage(self, capsys, store):
        rf = _put(store, capsys, "capture/rows.json", json.dumps({"a": 1}))
        code, env, _ = run(
            capsys,
            "read", "--run-folder", rf, "--path", "capture/rows.json",
            "--jsonpath", "a", "--offset", "3",
        )
        assert code == 2 and "--offset" in env["errors"][0]["message"]


class TestReadManyJsonpaths:
    DOC = {"rows": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}], "meta": {"n": 2}}

    def _streams(self, store, monkeypatch, object_id: str) -> list[str]:
        seen: list[str] = []
        real = store.get_stream

        def spy(oid: str, *a: Any, **kw: Any):
            if oid == object_id:
                seen.append(oid)
            return real(oid, *a, **kw)

        monkeypatch.setattr(store, "get_stream", spy)
        return seen

    def test_one_download_every_slice(self, capsys, store, monkeypatch):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        ref = run_sink(store, rf).put_json("capture/rows.json", self.DOC)
        seen = self._streams(store, monkeypatch, ref.object_id)
        out = ok(
            capsys,
            "read", "--run-folder", rf, "--path", "capture/rows.json",
            "--jsonpath", "rows[*].a", "--jsonpath", "meta.n",
            "--jsonpath", "rows[*].a",  # a repeat is read once
        )
        assert len(seen) == 1
        assert out["jsonpaths"] == ["rows[*].a", "meta.n"]
        assert out["excerpt"] == {"rows[*].a": [1, 2], "meta.n": 2}
        assert out["next_offset"] is None and out["offset"] == 0

    def test_single_jsonpath_is_keyed_like_many(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_json("capture/rows.json", self.DOC)
        out = ok(
            capsys,
            "read", "--run-folder", rf, "--path", "capture/rows.json",
            "--jsonpath", "rows.1.b",
        )
        assert out["excerpt"] == {"rows.1.b": "y"}
        assert out["jsonpaths"] == ["rows.1.b"] and out["missing_paths"] == []

    def test_missing_slice_is_null_and_named(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_json("capture/rows.json", self.DOC)
        code, env, raw = run(
            capsys,
            "read", "--run-folder", rf, "--path", "capture/rows.json",
            "--jsonpath", "meta.n", "--jsonpath", "meta.missing",
        )
        assert code == 0, raw
        out = env["data"]
        assert out["excerpt"] == {"meta.n": 2, "meta.missing": None}
        assert out["missing_paths"] == ["meta.missing"]
        assert any("'meta.missing'" in w for w in out["warnings"])

    def test_bad_expression_fails_before_the_download(
        self, capsys, store, monkeypatch
    ):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        ref = run_sink(store, rf).put_json("capture/rows.json", self.DOC)
        seen = self._streams(store, monkeypatch, ref.object_id)
        code, env, _ = run(
            capsys,
            "read", "--run-folder", rf, "--path", "capture/rows.json",
            "--jsonpath", "meta.n", "--jsonpath", "rows[",
        )
        assert code == 2 and env["errors"][0]["code"] == "USAGE" and seen == []


# --------------------------------------------------------------------------- #
# B2-2: a name another account key owns
# --------------------------------------------------------------------------- #
class TestAccountNameTaken:
    def test_route_names_the_owning_key_without_merge_advice(self, capsys, store):
        first = ok(capsys, *_preflight(account_key="1444828305810485"))
        ok(capsys, "verify-identity", "--run-id", first["run_id"], "--profile", "acme")
        ok(capsys, "route", "--run-id", first["run_id"])
        pre = ok(capsys, *PREFLIGHT)  # same --account-name, another key
        ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
        code, env, raw = run(capsys, "route", "--run-id", pre["run_id"])
        assert code == engagement.EXIT_USAGE, raw
        (error,) = env["errors"]
        assert error["code"] == "ACCOUNT_NAME_TAKEN" and error["retryable"] is False
        assert "belongs to account key '1444828305810485'" in error["message"]
        assert "--account-key 1444828305810485" in error["message"]
        assert "--account-name" in error["message"]
        assert "Reconcile" not in error["message"]
        assert "rebuild-index" not in error["message"]


class TestAccountKeyWarning:
    @pytest.mark.parametrize("key", ["Acme Corp", "acme", "ACME CORP"])
    def test_name_like_key_warns(self, capsys, key):
        out = ok(capsys, *_preflight(account_key=key))
        assert any(w.startswith("account_key_looks_like_name:") for w in out["warnings"])

    def test_stable_key_does_not_warn(self, capsys):
        out = ok(capsys, *PREFLIGHT)
        assert not any("account_key_looks_like_name" in w for w in out["warnings"])


# --------------------------------------------------------------------------- #
# B2-7: task names
# --------------------------------------------------------------------------- #
def test_workspace_task_name_hints_ws(capsys):
    code, env, _ = run(capsys, *_preflight(task_name="workspace-1444828305810485"))
    assert code == 2 and env["errors"][0]["code"] == "USAGE"
    assert "--task-name ws-1444828305810485" in env["errors"][0]["message"]


# --------------------------------------------------------------------------- #
# B2-8: transient Drive failures
# --------------------------------------------------------------------------- #
class TestStorageTransient:
    def test_exit_code_is_distinct(self):
        codes = [
            engagement.EXIT_OK,
            engagement.EXIT_INTERNAL,
            engagement.EXIT_USAGE,
            engagement.EXIT_AUTH_PROMPT,
            engagement.EXIT_STORAGE,
            engagement.EXIT_IDENTITY,
            engagement.EXIT_WORKSPACE,
            engagement.EXIT_STORAGE_TRANSIENT,
        ]
        assert engagement.EXIT_STORAGE_TRANSIENT == 8 and len(set(codes)) == len(codes)

    def test_classify(self):
        assert _envelope._classify(StorageTransientError("503")) == (
            8,
            "STORAGE_TRANSIENT",
        )
        wrapped = ApiError("Drive error: 503")
        wrapped.__cause__ = StorageTransientError("503")
        assert _envelope._classify(wrapped) == (8, "STORAGE_TRANSIENT")
        assert _envelope._classify(ApiError("Drive error: x")) == (4, "STORAGE_ERROR")

    def test_storage_errors_maps_it(self):
        with pytest.raises(_envelope.StorageTransient) as exc, _envelope._storage_errors():
            raise StorageTransientError("HTTP 500 after 5 retries")
        assert "retry the same command" in exc.value.message

    def test_read_envelope_is_retryable(self, capsys, store, monkeypatch):
        rf = _put(store, capsys, BIG, "x" * 100)
        artifact = run_sink(store, rf).artifacts()[BIG].id
        real = store.get_stream

        def flaky(oid: str, *a: Any, **kw: Any):
            if oid == artifact:
                raise StorageTransientError("HTTP 503 after retries")
            return real(oid, *a, **kw)

        monkeypatch.setattr(store, "get_stream", flaky)
        code, env, _ = run(capsys, "read", "--run-folder", rf, "--path", BIG)
        assert code == engagement.EXIT_STORAGE_TRANSIENT
        (error,) = env["errors"]
        assert error == {
            "code": "STORAGE_TRANSIENT",
            "message": error["message"],
            "retryable": True,
        }
        assert "HTTP 503" in error["message"]

    def test_usage_errors_are_not_retryable(self, capsys):
        code, env, _ = run(capsys, *_preflight(task_name="bad name"))
        assert code == 2 and env["errors"][0]["retryable"] is False

    def test_usage_error_type(self):
        assert issubclass(_envelope.Refusal, ArgError)
