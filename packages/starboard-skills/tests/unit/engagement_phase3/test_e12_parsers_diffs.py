"""E12: profile / sparklog / diff read ``drive:<id>``; local intake refused on overlay (D3-22)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ._support import error_code, module

PROFILE = {
    "graphs": [
        {
            "nodes": [
                {"id": "1", "name": "Scan parquet t", "tag": "FileScan", "metrics": []}
            ],
            "edges": [],
        }
    ],
    "query": {"id": "q-e12", "status": "FINISHED", "metrics": {"totalTimeMs": 1000}},
}
EVENT_LOG = [
    {"Event": "SparkListenerLogStart", "Spark Version": "3.5.0"},
    {
        "Event": "SparkListenerApplicationStart",
        "App Name": "j42",
        "App ID": "app-e12",
        "Timestamp": 1_700_000_000_000,
        "User": "svc",
    },
    {"Event": "SparkListenerApplicationEnd", "Timestamp": 1_700_000_060_000},
]
SETTINGS_A = {"settings": {"max_workers": 4, "node_type": "m5.xlarge", "spot": True}}
SETTINGS_B = {"settings": {"max_workers": 8, "node_type": "m5.xlarge", "photon": True}}
METRICS_A = {
    "metrics": {"failure_rate_pct": 1.0, "runs_count": 100, "p95_duration_ms": 900}
}
METRICS_B = {
    "metrics": {"failure_rate_pct": 8.0, "runs_count": 100, "p95_duration_ms": 1500}
}

SETTINGS_GOLDEN = {
    "counts": {"added": 1, "removed": 1, "changed": 1, "unchanged": 1},
    "added": [{"path": "$.settings.photon", "b": True}],
    "removed": [{"path": "$.settings.spot", "a": True}],
    "changed": [{"path": "$.settings.max_workers", "a": 4, "b": 8}],
}
METRICS_GOLDEN = {
    "counts": {"keys": 3, "changed": 2, "only_a": 0, "only_b": 0},
    "metrics": [
        {
            "key": "$.metrics.failure_rate_pct",
            "a": 1.0,
            "b": 8.0,
            "delta": 7.0,
            "unit": "pp",
        },
        {
            "key": "$.metrics.p95_duration_ms",
            "a": 900,
            "b": 1500,
            "delta": 600,
            "unit": "ms",
        },
        {
            "key": "$.metrics.runs_count",
            "a": 100,
            "b": 100,
            "delta": 0,
            "unit": "count",
        },
    ],
}


def _event_log() -> bytes:
    return "\n".join(json.dumps(e) for e in EVENT_LOG).encode()


def _put(store, name: str, content: bytes, mime: str = "application/json") -> str:
    return store.put_stream(
        store.root_folder_id(), name, mime, [content], properties={}
    ).id


def _file(tmp_path: Path, name: str, content: bytes) -> str:
    path = tmp_path / "intake" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path)


def test_profile_and_sparklog_read_drive_objects(capsys, store, sandbox) -> None:
    before = sandbox.snapshot()
    pid = _put(store, "profile.json", json.dumps(PROFILE).encode())
    code, env, raw = module("diagnostic", capsys, "profile", "--input", f"drive:{pid}")
    assert code == 0, raw
    assert env["data"]["query"]["id"] == "q-e12"

    lid = _put(store, "eventlog", _event_log(), "application/octet-stream")
    code, env, raw = module("sparklog", capsys, "parse", "--input", f"drive:{lid}")
    assert code == 0, raw
    assert env["data"]["input"] == f"drive:{lid}"
    assert sandbox.snapshot() == before


@pytest.mark.parametrize(
    ("name", "verb", "content"),
    [
        ("diagnostic", "profile", json.dumps(PROFILE).encode()),
        ("sparklog", "parse", b""),
    ],
    ids=["diagnostic-profile", "sparklog-parse"],
)
def test_local_intake_is_refused_on_overlay(
    name, verb, content, capsys, tmp_path
) -> None:
    from starboard_x._cli import EXIT_REFUSED

    path = _file(tmp_path, f"{verb}.json", content or _event_log())
    code, env, raw = module(name, capsys, verb, "--input", path)
    assert code == EXIT_REFUSED == 2, raw
    assert error_code(env) == "LOCAL_FILE_INTAKE_REFUSED"


def test_sparklog_source_local_is_removed(capsys, tmp_path) -> None:
    path = _file(tmp_path, "eventlog", _event_log())
    code, _env, raw = module(
        "sparklog", capsys, "parse", "--source", "local", "--path", path
    )
    assert code != 0, raw
    assert "local" not in _sparklog_sources()


def _sparklog_sources() -> tuple[str, ...]:
    from starboard_x.sparklog.__main__ import build_parser

    parse = build_parser()._subparsers._group_actions[0].choices["parse"]  # type: ignore[union-attr]
    source = next(a for a in parse._actions if a.dest == "source")
    return tuple(source.choices or ())


def _diff(capsys, verb: str, a: str, b: str) -> dict:
    code, env, raw = module("diff", capsys, verb, "--a", a, "--b", b)
    assert code == 0, raw
    return env["data"]


@pytest.mark.usefixtures("public")
def test_diff_settings_and_metrics_are_golden(capsys, tmp_path) -> None:
    a = _file(tmp_path, "a.json", json.dumps(SETTINGS_A).encode())
    b = _file(tmp_path, "b.json", json.dumps(SETTINGS_B).encode())
    first = _diff(capsys, "settings", a, b)
    assert {k: first[k] for k in SETTINGS_GOLDEN} == SETTINGS_GOLDEN
    assert _diff(capsys, "settings", a, b) == first

    a = _file(tmp_path, "ma.json", json.dumps(METRICS_A).encode())
    b = _file(tmp_path, "mb.json", json.dumps(METRICS_B).encode())
    data = _diff(capsys, "metrics", a, b)
    assert {k: data[k] for k in METRICS_GOLDEN} == METRICS_GOLDEN


def test_diff_reads_drive_refs(capsys, store, sandbox) -> None:
    before = sandbox.snapshot()
    a = _put(store, "a.json", json.dumps(SETTINGS_A).encode())
    b = _put(store, "b.json", json.dumps(SETTINGS_B).encode())
    data = _diff(capsys, "settings", f"drive:{a}", f"drive:{b}")
    assert {k: data[k] for k in SETTINGS_GOLDEN} == SETTINGS_GOLDEN
    assert sandbox.snapshot() == before


def test_diff_text_does_not_exist(capsys) -> None:
    from starboard_x.diff.__main__ import build_parser

    sub = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    assert set(sub) == {"settings", "metrics"}
    code, _env, raw = module("diff", capsys, "text", "--a", "x", "--b", "y")
    assert code != 0, raw
