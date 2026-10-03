"""Unit tests for FIX B — finops usage rewired to system.billing.usage SQL.

All Databricks SDK calls are mocked; no network access required.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from starboard_skills.helpers import finops
from starboard_skills.helpers.contract import ArgError

# ---------------------------------------------------------------------------
# Helpers to build a fake execute_statement response
# ---------------------------------------------------------------------------

def _make_succeeded_resp(columns: list[str], rows: list[list]) -> MagicMock:
    """Return a fake SUCCEEDED StatementResponse."""
    col_mocks = [SimpleNamespace(name=c) for c in columns]
    schema = SimpleNamespace(columns=col_mocks)
    manifest = SimpleNamespace(schema=schema)
    state = SimpleNamespace(value="SUCCEEDED")
    status = SimpleNamespace(state=state, error=None)
    result = SimpleNamespace(data_array=rows)
    return SimpleNamespace(status=status, manifest=manifest, result=result)


def _make_failed_resp(state_val: str = "FAILED", msg: str = "syntax error") -> MagicMock:
    error = SimpleNamespace(message=msg)
    state = SimpleNamespace(value=state_val)
    status = SimpleNamespace(state=state, error=error)
    return SimpleNamespace(status=status, manifest=None, result=None)


# ---------------------------------------------------------------------------
# FIX B tests
# ---------------------------------------------------------------------------

def test_usage_returns_summary_shape():
    """cmd_usage returns the expected envelope keys on a SUCCEEDED response."""
    cols = ["billing_origin_product", "workspace_id", "total_dbus", "records"]
    data_rows = [["JOBS", "123456789", "1200.50", "42"]]
    fake_resp = _make_succeeded_resp(cols, data_rows)

    fake_stmt_exec = MagicMock()
    fake_stmt_exec.execute_statement.return_value = fake_resp
    fake_ws = MagicMock()
    fake_ws.statement_execution = fake_stmt_exec

    with patch("starboard_skills.helpers.finops._client", return_value=fake_ws):
        result = finops.cmd_usage(SimpleNamespace(
            start_date="2025-01-01",
            end_date="2025-03-31",
            warehouse_id="abc123",
        ))

    assert result["columns"] == cols
    assert result["rows"] == [["JOBS", "123456789", "1200.50", "42"]]
    assert result["row_count"] == 1
    assert result["warehouse_id"] == "abc123"
    assert result["state"] == "SUCCEEDED"
    assert result["start_date"] == "2025-01-01"
    assert result["end_date"] == "2025-03-31"
    # Must not include any $ / dollar fields — DBU only
    assert "cost" not in result
    assert "dollars" not in result


def test_usage_rejects_bad_start_date():
    """Non-YYYY-MM-DD start date raises ArgError (no network call made)."""
    with pytest.raises(ArgError) as exc_info:
        finops.cmd_usage(SimpleNamespace(
            start_date="01/01/2025",
            end_date="2025-03-31",
            warehouse_id="wh1",
        ))
    assert "YYYY-MM-DD" in str(exc_info.value)


def test_usage_rejects_bad_end_date():
    """Non-YYYY-MM-DD end date raises ArgError."""
    with pytest.raises(ArgError) as exc_info:
        finops.cmd_usage(SimpleNamespace(
            start_date="2025-01-01",
            end_date="2025/03/31",
            warehouse_id="wh1",
        ))
    assert "YYYY-MM-DD" in str(exc_info.value)


def test_usage_rejects_calendar_invalid_date():
    """Dates matching YYYY-MM-DD format but invalid on the calendar raise ArgError."""
    with pytest.raises(ArgError) as exc_info:
        finops.cmd_usage(SimpleNamespace(
            start_date="2026-99-99",
            end_date="2026-03-31",
            warehouse_id="wh1",
        ))
    assert "2026-99-99" in str(exc_info.value)

    with pytest.raises(ArgError) as exc_info:
        finops.cmd_usage(SimpleNamespace(
            start_date="2026-01-01",
            end_date="2026-02-30",
            warehouse_id="wh1",
        ))
    assert "2026-02-30" in str(exc_info.value)


def test_usage_raises_on_non_succeeded_state():
    """A FAILED statement raises HelperError (not a silent empty result)."""
    from starboard_skills.helpers.contract import HelperError

    fake_resp = _make_failed_resp("FAILED", "Permission denied on system.billing.usage")
    fake_stmt_exec = MagicMock()
    fake_stmt_exec.execute_statement.return_value = fake_resp
    fake_ws = MagicMock()
    fake_ws.statement_execution = fake_stmt_exec

    with patch("starboard_skills.helpers.finops._client", return_value=fake_ws), pytest.raises(HelperError):
        finops.cmd_usage(SimpleNamespace(
            start_date="2025-01-01",
            end_date="2025-03-31",
            warehouse_id="wh1",
        ))


def test_usage_sql_uses_workspace_client_not_account_client():
    """cmd_usage must call _client() (workspace), not _account_client()."""
    cols = ["billing_origin_product", "workspace_id", "total_dbus", "records"]
    fake_resp = _make_succeeded_resp(cols, [])

    fake_ws = MagicMock()
    fake_ws.statement_execution.execute_statement.return_value = fake_resp

    with patch("starboard_skills.helpers.finops._client", return_value=fake_ws) as mock_ws_client, \
         patch("starboard_skills.helpers.finops._account_client") as mock_acct_client:
        finops.cmd_usage(SimpleNamespace(
            start_date="2025-01-01",
            end_date="2025-12-31",
            warehouse_id="wh-xyz",
        ))

    mock_ws_client.assert_called_once()
    mock_acct_client.assert_not_called()


def test_usage_workspace_id_filter_adds_param_and_where_clause():
    """--workspace-id appends a workspace_id param and switches to the filtered SQL."""
    cols = ["billing_origin_product", "workspace_id", "total_dbus", "records"]
    data_rows = [["SERVERLESS", "9876543210", "500.00", "10"]]
    fake_resp = _make_succeeded_resp(cols, data_rows)

    fake_stmt_exec = MagicMock()
    fake_stmt_exec.execute_statement.return_value = fake_resp
    fake_ws = MagicMock()
    fake_ws.statement_execution = fake_stmt_exec

    with patch("starboard_skills.helpers.finops._client", return_value=fake_ws):
        result = finops.cmd_usage(SimpleNamespace(
            start_date="2025-01-01",
            end_date="2025-03-31",
            warehouse_id="wh-filter",
            workspace_id="9876543210",
        ))

    # Return dict must carry the filter for auditability.
    assert result["workspace_id_filter"] == "9876543210"
    assert result["row_count"] == 1

    # The SQL sent to execute_statement must contain the workspace_id predicate.
    call_kwargs = fake_stmt_exec.execute_statement.call_args
    statement_used = call_kwargs.kwargs.get("statement") or call_kwargs.args[0] if call_kwargs.args else None
    if statement_used is None:
        # keyword-only call
        statement_used = call_kwargs[1].get("statement", "")
    assert "workspace_id = :workspace_id" in statement_used, (
        "Filtered SQL must contain AND workspace_id = :workspace_id"
    )

    # The parameter list must include workspace_id.
    params = call_kwargs.kwargs.get("parameters") or (call_kwargs.args[2] if len(call_kwargs.args) > 2 else [])
    param_names = [p.name for p in params]
    assert "workspace_id" in param_names, f"workspace_id not in params: {param_names}"


def test_usage_no_workspace_id_omits_filter_param():
    """Without --workspace-id the account-wide SQL is used and no filter in result."""
    cols = ["billing_origin_product", "workspace_id", "total_dbus", "records"]
    fake_resp = _make_succeeded_resp(cols, [])

    fake_stmt_exec = MagicMock()
    fake_stmt_exec.execute_statement.return_value = fake_resp
    fake_ws = MagicMock()
    fake_ws.statement_execution = fake_stmt_exec

    with patch("starboard_skills.helpers.finops._client", return_value=fake_ws):
        result = finops.cmd_usage(SimpleNamespace(
            start_date="2025-01-01",
            end_date="2025-03-31",
            warehouse_id="wh-all",
        ))

    assert "workspace_id_filter" not in result

    call_kwargs = fake_stmt_exec.execute_statement.call_args
    statement_used = call_kwargs.kwargs.get("statement", "")
    assert "workspace_id = :workspace_id" not in statement_used
