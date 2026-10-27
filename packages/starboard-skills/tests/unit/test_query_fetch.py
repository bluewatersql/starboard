"""``query fetch`` / ``history`` / ``slow`` against an autospec SDK client (spec E1, D3-21/24).

The client is ``create_autospec`` of the installed ``WorkspaceClient`` with each
sub-API autospecced from its property type, so touching a method the SDK does not
have (the old ``query_history.get_query``) raises instead of passing silently.
"""

from __future__ import annotations

import json
import typing
from unittest.mock import create_autospec

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    ListQueriesResponse,
    QueryFilter,
    QueryInfo,
    QueryMetrics,
    QueryStatus,
)

from .conftest import covered_ok, drive_files, evidence, run_main

QID = "01f0-stmt-abc"


def autospec_client(*apis: str):
    """An autospec ``WorkspaceClient`` whose named sub-APIs are autospecced too."""
    w = create_autospec(WorkspaceClient, instance=True)
    for name in apis:
        api_type = typing.get_type_hints(getattr(WorkspaceClient, name).fget)["return"]
        setattr(w, name, create_autospec(api_type, instance=True))
    return w


def _query(
    qid: str = QID, *, duration: int = 20_000, warehouse: str = "wh-1"
) -> QueryInfo:
    return QueryInfo(
        query_id=qid,
        status=QueryStatus.FINISHED,
        query_text="SELECT * FROM t WHERE owner = 'alice@corp.com'",
        duration=duration,
        warehouse_id=warehouse,
        user_id=11,
        user_name="alice@corp.com",
        executed_as_user_id=12,
        executed_as_user_name="svc@corp.com",
        error_message="denied for bob@corp.com",
        rows_produced=3,
        metrics=QueryMetrics(read_bytes=4096, total_time_ms=900, spill_to_disk_bytes=0),
    )


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch):
    w = autospec_client("query_history")
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def _identity_keys(obj) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.endswith("user_name") or k.endswith("user_id"):
                found.append(k)
            found += _identity_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            found += _identity_keys(v)
    return found


@pytest.mark.unit
class TestQueryFetch:
    def test_uses_list_with_statement_filter(self, sdk, capsys):
        sdk.query_history.list.return_value = ListQueriesResponse(res=[_query()])
        code, out = run_main(["query", "fetch", "--query-id", QID], capsys)
        assert code == 0, out
        sdk.query_history.list.assert_called_once_with(
            filter_by=QueryFilter(statement_ids=[QID]),
            include_metrics=True,
            max_results=1,
        )

    def test_get_query_does_not_exist_on_the_sdk(self, sdk):
        with pytest.raises(AttributeError):
            sdk.query_history.get_query  # noqa: B018 - the old (broken) call

    def test_output_keeps_metrics_and_scrubs_identity(self, sdk, capsys):
        sdk.query_history.list.return_value = ListQueriesResponse(res=[_query()])
        code, out = run_main(["query", "fetch", "--query-id", QID], capsys)
        assert code == 0
        data = json.loads(out)["data"]
        assert data["query_id"] == QID
        assert data["metrics"]["read_bytes"] == 4096
        assert data["query_text"] == "SELECT * FROM t WHERE owner = '<email>'"
        assert data["error_message"] == "denied for <email>"
        assert _identity_keys(data) == []
        assert "@" not in out

    def test_empty_result_is_not_found(self, sdk, capsys):
        sdk.query_history.list.return_value = ListQueriesResponse(res=[])
        code, out = run_main(["query", "fetch", "--query-id", QID], capsys)
        assert code == 2
        env = json.loads(out)
        assert env["ok"] is False
        assert (
            env["error"] == f"Query {QID} not found in query history (retention window)"
        )

    def test_none_result_is_not_found(self, sdk, capsys):
        sdk.query_history.list.return_value = ListQueriesResponse()
        code, _ = run_main(["query", "fetch", "--query-id", QID], capsys)
        assert code == 2

    def test_sdk_failure_is_api_error(self, sdk, capsys):
        sdk.query_history.list.side_effect = RuntimeError("boom")
        code, out = run_main(["query", "fetch", "--query-id", QID], capsys)
        assert code == 3 and "boom" in json.loads(out)["error"]

    def test_run_folder_writes_through_the_sink(
        self, covered_env, drive_run, sdk, capsys
    ):
        sdk.query_history.list.return_value = ListQueriesResponse(res=[_query()])
        before = covered_env.snapshot()
        code, out = run_main(
            [
                "query",
                "fetch",
                "--query-id",
                QID,
                "--run-folder",
                drive_run.folder_id,
                "--out",
                "raw/query.json",
            ],
            capsys,
        )
        assert code == 0, out
        covered_ok(covered_env, before, out)
        stored = json.loads(drive_files(drive_run)["raw/query.json"])
        assert stored["data"]["metrics"]["read_bytes"] == 4096
        assert _identity_keys(stored) == [] and "@" not in json.dumps(stored)
        (ev,) = evidence(drive_run)
        assert ev["producer"] == "starboard-helper query fetch"


@pytest.mark.unit
class TestHistoryAndSlowScrubbed:
    def test_history_has_no_identity(self, sdk, capsys):
        sdk.query_history.list.return_value = ListQueriesResponse(
            res=[_query(), _query("q2")]
        )
        code, out = run_main(["query", "history", "--limit", "5"], capsys)
        assert code == 0, out
        data = json.loads(out)["data"]
        assert data["count"] == 2
        assert _identity_keys(data) == []
        assert data["queries"][0]["query_text"].endswith("'<email>'")
        assert "@" not in out

    def test_slow_has_no_identity(self, sdk, capsys):
        sdk.query_history.list.return_value = ListQueriesResponse(
            res=[_query(duration=50_000), _query("q2", duration=10)]
        )
        code, out = run_main(["query", "slow", "--min-duration-ms", "1000"], capsys)
        assert code == 0, out
        data = json.loads(out)["data"]
        assert [q["query_id"] for q in data["slow_queries"]] == [QID]
        assert _identity_keys(data) == []
        assert "@" not in out
