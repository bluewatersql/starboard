# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""The stdlib-only query-profile parser (``starboard_x.diagnostic.query_profile``, D3-22).

``parse_profile`` reads a Databricks query profile (Liquid ``graphs[].nodes[]`` or the
standard ``operatorID``/``children`` tree) into a :class:`QueryProfileSummary`:
operators, top operators by time/rows/bytes, spill, scan stats and deterministic
warning codes. The module imports nothing outside the standard library.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from starboard_x.diagnostic import query_profile
from starboard_x.diagnostic.query_profile import (
    QueryProfileSummary,
    parse_profile,
)

_CORE_DIR = Path(__file__).parents[3]

LIQUID: dict = {
    "query": {
        "id": "q-1",
        "status": "FINISHED",
        "queryText": "SELECT * FROM orders o JOIN items i ON o.ts >= i.start -- alice@example.com",
        "statementType": "SELECT",
        "metrics": {
            "totalTimeMs": 12000,
            "compilationTimeMs": 500,
            "executionTimeMs": 11000,
            "readBytes": 1073741824,
            "readRemoteBytes": 1073741824,
            "readCacheBytes": 0,
            "networkSentBytes": 4096,
            "spillToDiskBytes": 2048,
            "rowsReadCount": 1000000,
            "rowsProducedCount": 10,
            "readFilesCount": 40,
            "prunedFilesCount": 60,
            "prunedBytes": 5000,
            "photonTotalTimeMs": 9000,
            "taskTotalTimeMs": 20000,
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
                        {"key": "SIZE_OF_FILES_READ", "value": 800000000},
                    ],
                    "metadata": [],
                },
                {
                    "id": "2",
                    "name": "Scan main.sales.items",
                    "tag": "UNKNOWN_DATA_SOURCE_SCAN_EXEC",
                    "metrics": [
                        {"key": "NUMBER_OUTPUT_ROWS", "value": 100000},
                        {"key": "wallClockTimeNanos", "value": 1_000_000_000},
                        {"key": "SIZE_OF_FILES_READ", "value": "273741824"},
                    ],
                },
                {
                    "id": "3",
                    "name": "PhotonBroadcastNestedLoopJoin",
                    "tag": "PHOTON_BROADCAST_NESTED_LOOP_JOIN_EXEC",
                    "metrics": [
                        {"key": "NUMBER_OUTPUT_ROWS", "value": 10},
                        {"key": "wallClockTimeNanos", "value": 6_000_000_000},
                        {"key": "SPILL_SIZE", "value": 2048},
                    ],
                    "metadata": [
                        {"key": "CONDITION", "values": ["ts >= start"]},
                        {"key": "JOIN_TYPE", "value": "Inner"},
                    ],
                },
                {
                    "id": "4",
                    "name": "PhotonShuffleExchangeSink",
                    "tag": "PHOTON_SHUFFLE_EXCHANGE_SINK_EXEC",
                    "metrics": [{"key": "NUMBER_OUTPUT_ROWS", "value": 100000}],
                },
                # An UNKNOWN tag without Scan/Join in the name is not an operator.
                {"id": "5", "name": "Project", "tag": "UNKNOWN_PROJECT", "metrics": []},
            ],
            "edges": [{"fromId": "1", "toId": "3"}],
            "stageData": [
                {
                    "stageId": "1",
                    "status": "COMPLETE",
                    "numTasks": 10,
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

STANDARD: dict = {
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


@pytest.mark.unit
class TestLiquidProfile:
    @pytest.fixture
    def summary(self) -> QueryProfileSummary:
        return parse_profile(json.dumps(LIQUID))

    def test_format_and_operators(self, summary: QueryProfileSummary) -> None:
        assert summary.format == "liquid"
        assert summary.operator_count == 4
        assert [op.id for op in summary.operators] == ["1", "2", "3", "4"]
        assert summary.truncated is False
        assert dict(summary.tag_counts) == {
            "UNKNOWN_DATA_SOURCE_SCAN_EXEC": 2,
            "PHOTON_BROADCAST_NESTED_LOOP_JOIN_EXEC": 1,
            "PHOTON_SHUFFLE_EXCHANGE_SINK_EXEC": 1,
        }
        assert dict(summary.join_algorithms) == {"Broadcast Nested Loop": 1}

    def test_top_operators(self, summary: QueryProfileSummary) -> None:
        assert [(s.id, s.value) for s in summary.top_by_time] == [
            ("3", 6000.0),
            ("1", 4000.0),
            ("2", 1000.0),
        ]
        # Ties break on operator id, so the order is deterministic.
        assert [(s.id, s.value) for s in summary.top_by_rows] == [
            ("1", 900000.0),
            ("2", 100000.0),
            ("4", 100000.0),
            ("3", 10.0),
        ]
        # A numeric string metric value is read as a number.
        assert [(s.id, s.value) for s in summary.top_by_bytes] == [
            ("1", 800000000.0),
            ("2", 273741824.0),
        ]

    def test_spill_and_scan_stats(self, summary: QueryProfileSummary) -> None:
        assert summary.spill.spill_to_disk_bytes == 2048
        assert summary.spill.operators_with_spill == 1
        scans = summary.scans
        assert scans.scan_count == 2
        assert scans.tables == (("main.sales.items", 1), ("main.sales.orders", 1))
        assert scans.read_bytes == 1073741824
        assert scans.rows_read == 1000000
        assert scans.files_read == 40
        assert scans.files_pruned == 60
        assert scans.bytes_pruned == 5000

    def test_query_meta_and_stages(self, summary: QueryProfileSummary) -> None:
        assert summary.query["id"] == "q-1"
        assert summary.query["totalTimeMs"] == 12000
        assert summary.query["querySource"]["jobId"] == "123"
        assert len(summary.stages) == 2

    def test_query_text_emails_are_redacted(self, summary: QueryProfileSummary) -> None:
        assert "alice@example.com" not in summary.query["queryText"]
        assert "<email>" in summary.query["queryText"]
        assert "alice@example.com" not in json.dumps(summary.to_dict())

    def test_warnings_are_sorted_codes(self, summary: QueryProfileSummary) -> None:
        assert summary.warnings == (
            "failed_stages",
            "nested_loop_join",
            "range_join_candidate",
            "spill_to_disk",
        )

    def test_to_dict_is_json_and_deterministic(
        self, summary: QueryProfileSummary
    ) -> None:
        data = summary.to_dict()
        assert json.loads(json.dumps(data)) == data
        assert parse_profile(json.dumps(LIQUID)).to_dict() == data
        assert data["stages"] == {
            "count": 2,
            "completed": 1,
            "failed": 1,
            "total_tasks": 14,
            "failed_stage_ids": ["2"],
        }
        assert data["scans"]["tables"] == [
            {"table": "main.sales.items", "scans": 1},
            {"table": "main.sales.orders", "scans": 1},
        ]
        assert data["operators"][2]["metadata"]["CONDITION"] == ["ts >= start"]
        assert data["top_by_time"][0] == {
            "id": "3",
            "name": "PhotonBroadcastNestedLoopJoin",
            "tag": "PHOTON_BROADCAST_NESTED_LOOP_JOIN_EXEC",
            "value": 6000.0,
        }

    def test_max_operators_truncates(self) -> None:
        summary = parse_profile(json.dumps(LIQUID), max_operators=2)
        assert summary.operator_count == 4
        assert [op.id for op in summary.operators] == ["1", "2"]
        assert summary.truncated is True
        # Aggregates still cover every operator.
        assert len(summary.top_by_rows) == 4

    def test_bytes_input(self) -> None:
        summary = parse_profile(json.dumps(LIQUID).encode())
        assert summary.operator_count == 4


@pytest.mark.unit
class TestStandardProfile:
    def test_tree_is_flattened_and_tags_inferred(self) -> None:
        summary = parse_profile(json.dumps(STANDARD))
        assert summary.format == "standard"
        assert [(op.id, op.tag) for op in summary.operators] == [
            ("0", "PHOTON_SORT_MERGE_JOIN_EXEC"),
            ("1", "DATA_SOURCE_SCAN_EXEC"),
            ("2", "SHUFFLE_EXCHANGE_EXEC"),
        ]
        assert dict(summary.join_algorithms) == {"Sort Merge": 1}
        assert [(s.id, s.value) for s in summary.top_by_time] == [("0", 300.0)]
        assert summary.query == {}
        assert summary.stages == ()
        assert summary.scans.tables == (("parquet", 1),)
        assert summary.warnings == ()

    def test_array_of_standard_operators(self) -> None:
        summary = parse_profile(
            json.dumps([STANDARD, {"operatorID": "9", "operatorName": "Filter"}])
        )
        assert summary.format == "standard_array"
        assert summary.operator_count == 4

    def test_array_of_liquid_nodes(self) -> None:
        nodes = LIQUID["graphs"][0]["nodes"]
        summary = parse_profile(json.dumps(nodes))
        assert summary.format == "liquid_nodes"
        # A bare node list keeps every node (no tag filter), as before.
        assert summary.operator_count == 5

    def test_nested_unknown_shape_is_scanned(self) -> None:
        doc = {"plan": {"root": {"operatorID": "7", "operatorName": "HashAggregate"}}}
        summary = parse_profile(json.dumps(doc))
        assert summary.format == "nested"
        assert [op.id for op in summary.operators] == ["7"]

    def test_empty_profile(self) -> None:
        summary = parse_profile("{}")
        assert summary.operator_count == 0
        assert summary.operators == ()
        assert summary.warnings == ()

    def test_non_object_json_is_empty_not_a_crash(self) -> None:
        assert parse_profile('"graphs"').operator_count == 0
        assert parse_profile("[1, 2]").operator_count == 0

    def test_invalid_json_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_profile("{not json")


@pytest.mark.unit
def test_module_imports_only_the_standard_library() -> None:
    body = """
import sys
before = set(sys.modules)
import starboard_x.diagnostic.query_profile  # noqa: F401
new = {m.split(".")[0] for m in set(sys.modules) - before}
foreign = sorted(
    m for m in new
    if m not in sys.stdlib_module_names and m != "starboard_x" and not m.startswith("_")
)
assert not foreign, f"non-stdlib imports: {foreign}"
loaded = sorted(m for m in set(sys.modules) - before if m.startswith("starboard_x"))
assert loaded == [
    "starboard_x",
    "starboard_x.contract",
    "starboard_x.diagnostic",
    "starboard_x.diagnostic.query_profile",
], loaded
print("OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", body], capture_output=True, text=True, cwd=str(_CORE_DIR)
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout


_LOCAL, _DOMAIN = "alice", "example.com"
_EMAIL_FORMS = {
    "plain": f"x={_LOCAL}@{_DOMAIN}",
    "single_quoted": f"'{_LOCAL}@{_DOMAIN}'",
    "double_quoted": f'"{_LOCAL}@{_DOMAIN}"',
    "percent_encoded": f"ref={_LOCAL}%40{_DOMAIN}",
    "fullwidth": f"owner={_LOCAL}\uff20{_DOMAIN}",
}


def test_no_local_email_redactor() -> None:
    assert not hasattr(query_profile, "_EMAIL")
    assert not hasattr(query_profile, "redact_emails")
    assert "redact_emails" not in query_profile.__all__


@pytest.mark.parametrize("form", sorted(_EMAIL_FORMS))
def test_query_text_email_forms_are_redacted(form: str) -> None:
    doc = json.loads(json.dumps(LIQUID))
    doc["query"]["queryText"] = f"SELECT 1 WHERE {_EMAIL_FORMS[form]}"
    out = parse_profile(json.dumps(doc))
    text = out.query["queryText"]
    assert "<email>" in text, text
    assert _LOCAL not in text, text
    assert _LOCAL not in json.dumps(out.to_dict())
