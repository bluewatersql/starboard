"""E1: ``query fetch`` uses the SDK query-history list; identity is scrubbed (D3-21, D3-24)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from ._support import autospec_client, helper, identity_keys

#: A public install (no overlay): the acquisition verbs print to stdout.
pytestmark = pytest.mark.usefixtures("public")

QID = "01f0-stmt-e1"


def _query(qid: str = QID, *, duration: int = 20_000) -> object:
    from databricks.sdk.service.sql import QueryInfo, QueryMetrics, QueryStatus

    return QueryInfo(
        query_id=qid,
        status=QueryStatus.FINISHED,
        query_text="SELECT * FROM t WHERE owner = 'jo.analyst@acme.example'",
        duration=duration,
        warehouse_id="wh-1",
        user_id=11,
        user_name="jo.analyst@acme.example",
        executed_as_user_id=12,
        executed_as_user_name="svc.etl@acme.example",
        error_message=None,
        rows_produced=3,
        metrics=QueryMetrics(read_bytes=4096, total_time_ms=900, spill_to_disk_bytes=0),
    )


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> object:
    w = autospec_client("query_history")
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def test_fetch_lists_by_statement_id_with_metrics(sdk, capsys) -> None:
    from databricks.sdk.service.sql import ListQueriesResponse, QueryFilter

    sdk.query_history.list.return_value = ListQueriesResponse(res=[_query()])
    code, env, raw = helper(capsys, "query", "fetch", "--query-id", QID)
    assert code == 0, raw
    sdk.query_history.list.assert_called_once_with(
        filter_by=QueryFilter(statement_ids=[QID]),
        include_metrics=True,
        max_results=1,
    )
    data = env["data"]
    assert data["metrics"]["read_bytes"] == 4096
    assert data["query_text"] == "SELECT * FROM t WHERE owner = '<email>'"
    assert identity_keys(data) == []
    assert "@" not in raw


def test_get_query_is_not_an_sdk_method(sdk) -> None:
    with pytest.raises(AttributeError):
        sdk.query_history.get_query  # noqa: B018 - the old (broken) call


def test_fetch_empty_result_is_not_found(sdk, capsys) -> None:
    from databricks.sdk.service.sql import ListQueriesResponse

    sdk.query_history.list.return_value = ListQueriesResponse(res=[])
    code, env, raw = helper(capsys, "query", "fetch", "--query-id", QID)
    assert code == 2, raw
    assert env["ok"] is False


def test_history_and_slow_drop_identity(sdk, capsys) -> None:
    from databricks.sdk.service.sql import ListQueriesResponse

    sdk.query_history.list.return_value = ListQueriesResponse(
        res=[_query(duration=50_000), _query("q2", duration=10)]
    )
    code, env, raw = helper(capsys, "query", "history", "--limit", "5")
    assert code == 0, raw
    assert identity_keys(env["data"]) == [] and "@" not in raw
    assert env["data"]["queries"][0]["query_text"].endswith("'<email>'")

    code, env, raw = helper(capsys, "query", "slow", "--min-duration-ms", "1000")
    assert code == 0, raw
    assert [q["query_id"] for q in env["data"]["slow_queries"]] == [QID]
    assert identity_keys(env["data"]) == [] and "@" not in raw


def test_sql_service_get_query_uses_the_same_sdk_call() -> None:
    from databricks.sdk.service.sql import ListQueriesResponse, QueryFilter
    from starboard.adapters.databricks.services.sql import SQLService

    w = autospec_client("query_history")
    w.query_history.list.return_value = ListQueriesResponse(res=[_query()])
    with patch("httpx.AsyncClient") as http:
        result = asyncio.run(SQLService(w, warehouse_id="wh").get_query(QID))
    http.assert_not_called()
    w.query_history.list.assert_called_once_with(
        filter_by=QueryFilter(statement_ids=[QID]),
        include_metrics=True,
        max_results=1,
    )
    assert result["metrics"]["read_bytes"] == 4096
    assert json.dumps(result)
