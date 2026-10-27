# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``QueryProfileExplorer`` is a thin wrapper over the stdlib parser (D3-22).

``explore()`` parses through ``starboard_x.diagnostic.query_profile.parse_profile`` and
maps the :class:`QueryProfileSummary` to the heavy ``ExplorationResult``. The golden
(``golden_query_profile_explorer.json``) was captured from the pre-wrapper explorer,
so every focus / detail-level combination keeps its output.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from starboard.tools.domain.diagnostic import query_profile_explorer as qpe
from starboard.tools.domain.diagnostic.models import ExplorationResult
from starboard.tools.domain.diagnostic.query_profile_explorer import (
    QueryProfileExplorer,
)

_GOLDEN = Path(__file__).with_name("golden_query_profile_explorer.json")

LIQUID: dict[str, Any] = {
    "query": {
        "id": "q-1",
        "status": "FINISHED",
        "queryText": "SELECT * FROM orders o JOIN items i ON o.ts >= i.start",
        "statementType": "SELECT",
        "metrics": {
            "totalTimeMs": 12000,
            "compilationTimeMs": 500,
            "executionTimeMs": 11000,
            "resultFetchTimeMs": 20,
            "planningTimeMs": 100,
            "readBytes": 1073741824,
            "readRemoteBytes": 1073741824,
            "readCacheBytes": 1024,
            "networkSentBytes": 4096,
            "spillToDiskBytes": 2048,
            "rowsReadCount": 1000000,
            "rowsProducedCount": 10,
            "readFilesCount": 40,
            "prunedFilesCount": 60,
            "prunedBytes": 5000,
            "photonTotalTimeMs": 9000,
            "taskTotalTimeMs": 20000,
            "bytesReadFromCachePercentage": 3,
        },
        "internalQuerySource": {"jobId": "123"},
    },
    "graphs": [
        {
            "nodes": [
                {
                    "id": "1",
                    "name": "Scan main.sales.orders",
                    "tag": "UNKNOWN_DATA_SOURCE_SCAN_EXEC",
                    "metrics": [
                        {"key": "NUMBER_OUTPUT_ROWS", "value": 900000},
                        {"key": "wallClockTimeNanos", "value": 4_000_000_000},
                    ],
                    "metadata": [],
                },
                {
                    "id": "2",
                    "name": "Scan main.sales.items",
                    "tag": "UNKNOWN_DATA_SOURCE_SCAN_EXEC",
                    "metrics": [{"key": "wallClockTimeNanos", "value": 1_000_000_000}],
                },
                {
                    "id": "3",
                    "name": "PhotonBroadcastNestedLoopJoin",
                    "tag": "PHOTON_BROADCAST_NESTED_LOOP_JOIN_EXEC",
                    "metrics": [
                        {"key": "NUMBER_OUTPUT_ROWS", "value": 10},
                        {"key": "WALL_CLOCK_TIME", "value": 6000},
                    ],
                    "metadata": [
                        {"key": "CONDITION", "values": ["ts >= start"]},
                        {"key": "JOIN_TYPE", "value": "Inner"},
                        {"key": "LEFT_KEYS", "values": ["ts"]},
                        {"key": "RIGHT_KEYS", "values": ["start"]},
                        {"key": "JOIN_BUILD_SIDE", "value": "right"},
                    ],
                },
                {
                    "id": "4",
                    "name": "PhotonShuffleExchangeSink",
                    "tag": "PHOTON_SHUFFLE_EXCHANGE_SINK_EXEC",
                    "metrics": [],
                },
                {"id": "5", "name": "Project", "tag": "UNKNOWN_PROJECT", "metrics": []},
            ],
            "edges": [{"fromId": "1", "toId": "3"}],
            "stageData": [
                {
                    "stageId": "1",
                    "status": "COMPLETE",
                    "numTasks": 10,
                    "numCompleteTasks": 10,
                    "keyMetrics": {"durationMs": 4000},
                },
                {
                    "stageId": "2",
                    "status": "FAILED",
                    "numTasks": 4,
                    "failureReason": "OOM",
                },
            ],
        }
    ],
}

STANDARD: dict[str, Any] = {
    "operatorID": "0",
    "operatorName": "SortMergeJoin",
    "metrics": {"numOutputRows": 5, "totalTimeMs": 300},
    "children": [
        {
            "operatorID": "1",
            "operatorName": "Scan parquet db.t1",
            "metrics": {"numOutputRows": 50},
        },
        {"operatorID": "2", "operatorName": "Exchange hashpartitioning", "metrics": {}},
    ],
}

FIXTURES: dict[str, str] = {
    "liquid": json.dumps(LIQUID),
    "standard": json.dumps(STANDARD),
    "standard_array": json.dumps([STANDARD]),
    "empty": "{}",
    "invalid": "{not json",
}
FOCI = (
    "range join hints, join strategies",
    "shuffle exchange",
    "scan tables",
    "slow bottleneck",
    "skew",
    "spill memory",
    "stage failed",
    "overview",
    "cache io",
    "orders",
    "zzz",
)
LEVELS = ("summary", "detailed", "exhaustive")


def _cases() -> list[tuple[str, str, str]]:
    return [(f, focus, lvl) for f in FIXTURES for focus in FOCI for lvl in LEVELS]


def _key(fixture: str, focus: str, level: str) -> str:
    return f"{fixture}|{focus}|{level}"


def _explore(fixture: str, focus: str, level: str) -> dict[str, Any]:
    result = QueryProfileExplorer().explore(FIXTURES[fixture], focus, level)  # type: ignore[arg-type]
    return json.loads(json.dumps(asdict(result)))


@pytest.mark.unit
@pytest.mark.parametrize(("fixture", "focus", "level"), _cases())
def test_explore_matches_the_pre_wrapper_golden(
    fixture: str, focus: str, level: str
) -> None:
    golden = json.loads(_GOLDEN.read_text())
    assert _explore(fixture, focus, level) == golden[_key(fixture, focus, level)]


@pytest.mark.unit
def test_explore_delegates_to_the_stdlib_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    real = qpe.parse_profile

    def spy(content: Any, **kwargs: Any) -> Any:
        calls.append((content, kwargs))
        return real(content, **kwargs)

    monkeypatch.setattr(qpe, "parse_profile", spy)
    result = QueryProfileExplorer().explore(FIXTURES["liquid"], "joins")
    assert isinstance(result, ExplorationResult)
    assert calls == [(FIXTURES["liquid"], {"max_operators": None})]
    assert result.sections_found == ("joins",)


@pytest.mark.unit
def test_parse_is_cached_per_content(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = qpe.parse_profile

    def spy(content: Any, **kwargs: Any) -> Any:
        calls.append(content)
        return real(content, **kwargs)

    monkeypatch.setattr(qpe, "parse_profile", spy)
    explorer = QueryProfileExplorer()
    explorer.explore(FIXTURES["liquid"], "joins")
    explorer.explore(FIXTURES["liquid"], "scans")
    assert len(calls) == 1


@pytest.mark.unit
def test_query_text_emails_are_redacted_in_the_content() -> None:
    doc = json.loads(FIXTURES["liquid"])
    doc["query"]["queryText"] = "SELECT 1 -- owner bob@example.com"
    result = QueryProfileExplorer().explore(json.dumps(doc), "overview")
    assert "bob@example.com" not in result.content
    assert "<email>" in result.content


@pytest.mark.unit
@pytest.mark.parametrize(
    "form",
    ["{a}@{d}", "'{a}@{d}'", '"{a}@{d}"', "{a}%40{d}", "{a}\uff20{d}"],
)
def test_query_text_email_forms_never_reach_the_content(form: str) -> None:
    local, domain = "alice", "example.com"
    doc = json.loads(FIXTURES["liquid"])
    doc["query"]["queryText"] = "SELECT 1 -- " + form.format(a=local, d=domain)
    result = QueryProfileExplorer().explore(json.dumps(doc), "overview")
    assert local not in result.content
    assert "<email>" in result.content


@pytest.mark.unit
def test_public_names_are_kept() -> None:
    assert qpe.__all__ == ["QueryProfileExplorer", "ExplorationResult"]
    assert qpe.ExplorationResult is ExplorationResult
