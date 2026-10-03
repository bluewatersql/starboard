# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Contract for the read-only ``query sql`` helper verb (evidence re-check, G9).

It must run a single read-only statement (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN),
reject anything that could write, cap the row count, and return a rows/columns
payload. This is the validate-beat surface for independently re-checking a
finding's numbers — never a write path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starboard_skills.helpers import query as q
from starboard_skills.helpers.contract import ArgError, HelperError

_REAL_PREFLIGHT = q._preflight


@pytest.fixture(autouse=True)
def _no_network_preflight(monkeypatch):
    """Keep every cmd_sql test hermetic: the network preflight is a no-op here
    (TestPreflight exercises the real function via ``_REAL_PREFLIGHT``)."""
    monkeypatch.setattr(q, "_preflight", lambda profile: None)


def _args(sql: str, *, warehouse_id="wh-1", limit=100, param=None):
    return SimpleNamespace(sql=sql, warehouse_id=warehouse_id, limit=limit, param=param)


def _client_returning(columns, data_array, *, state="SUCCEEDED"):
    resp = SimpleNamespace(
        manifest=SimpleNamespace(
            schema=SimpleNamespace(columns=[SimpleNamespace(name=c) for c in columns])
        ),
        result=SimpleNamespace(data_array=data_array),
        status=SimpleNamespace(state=SimpleNamespace(value=state)),
    )
    client = MagicMock()
    client.statement_execution.execute_statement.return_value = resp
    return client


@pytest.mark.unit
class TestReadOnlyGuard:
    @pytest.mark.parametrize(
        "bad",
        [
            "DROP TABLE x",
            "DELETE FROM t WHERE 1=1",
            "UPDATE t SET a=1",
            "INSERT INTO t VALUES (1)",
            "MERGE INTO t ...",
            "CREATE TABLE t AS SELECT 1",
            "ALTER WAREHOUSE w SET AUTO_STOP_MINS = 10",
            "GRANT SELECT ON t TO u",
            # The bypass: a read-only WITH head prefixing a write must still be rejected.
            "WITH c AS (SELECT 1) INSERT INTO t SELECT * FROM c",
            "with c as (select 1) delete from t",
        ],
    )
    def test_rejects_writes(self, bad):
        with pytest.raises(ArgError):
            q.cmd_sql(_args(bad))

    def test_rejects_multi_statement(self):
        with pytest.raises(ArgError):
            q.cmd_sql(_args("SELECT 1; DROP TABLE x"))

    def test_rejects_empty(self):
        with pytest.raises(ArgError):
            q.cmd_sql(_args("   "))

    def test_rejects_bad_param(self, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: _client_returning([], []))
        with pytest.raises(ArgError):
            q.cmd_sql(_args("SELECT 1", param=["noequals"]))

    @pytest.mark.parametrize("head", [
        "SELECT a FROM t", "WITH c AS (SELECT 1) SELECT * FROM c",
        "SHOW TABLES", "DESCRIBE t", "EXPLAIN SELECT 1",
        # #3: a write word inside a string literal is NOT a write — must be allowed.
        "SELECT x FROM t WHERE action = 'DELETE'",
        "SELECT x FROM t WHERE name LIKE '%CREATE%'",
        # #3: a leading comment (the repo's own pack SQL starts with one) must be allowed.
        "-- pack header\nSELECT 1",
        "/* c */ WITH c AS (SELECT 1) SELECT * FROM c",
    ])
    def test_allows_read_only_heads(self, head, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: _client_returning(["x"], [["1"]]))
        out = q.cmd_sql(_args(head))
        assert out["read_only"] is True


@pytest.mark.unit
class TestExecution:
    def test_returns_rows_and_columns(self, monkeypatch):
        client = _client_returning(["endpoint", "dbus"], [["ep-a", "2928"], ["ep-b", "10"]])
        monkeypatch.setattr(q, "_client", lambda: client)
        out = q.cmd_sql(_args("SELECT endpoint, dbus FROM t"))
        assert out["columns"] == ["endpoint", "dbus"]
        assert out["rows"] == [["ep-a", "2928"], ["ep-b", "10"]]
        assert out["row_count"] == 2
        assert out["warehouse_id"] == "wh-1"
        assert out["state"] == "SUCCEEDED"

    def test_caps_row_limit(self, monkeypatch):
        client = _client_returning(["x"], [])
        monkeypatch.setattr(q, "_client", lambda: client)
        q.cmd_sql(_args("SELECT 1", limit=999999))
        _, kwargs = client.statement_execution.execute_statement.call_args
        assert kwargs["row_limit"] == q._MAX_ROW_LIMIT
        assert kwargs["warehouse_id"] == "wh-1"

    def test_passes_parameters(self, monkeypatch):
        client = _client_returning(["x"], [["1"]])
        monkeypatch.setattr(q, "_client", lambda: client)
        q.cmd_sql(_args("SELECT :n AS n", param=["n=5"]))
        _, kwargs = client.statement_execution.execute_statement.call_args
        assert kwargs["parameters"] is not None and len(kwargs["parameters"]) == 1

    def test_non_succeeded_state_errors_not_silent_zero_rows(self, monkeypatch):
        # #2: a timed-out/RUNNING statement returns result=None — must error, not report 0 rows.
        client = _client_returning(["x"], None, state="RUNNING")
        monkeypatch.setattr(q, "_client", lambda: client)
        with pytest.raises(HelperError):
            q.cmd_sql(_args("SELECT count(*) FROM huge"))


@pytest.mark.unit
class TestProfileAndTimeout:
    def test_profile_flag_selects_client_profile(self, monkeypatch):
        seen = {}
        client = _client_returning(["x"], [["1"]])

        def fake_client(profile=None):
            seen["profile"] = profile
            return client

        monkeypatch.setattr(q, "_client", fake_client)
        args = _args("SELECT 1")
        args.profile = "my-profile"
        q.cmd_sql(args)
        assert seen["profile"] == "my-profile"

    def test_no_profile_uses_ambient_client(self, monkeypatch):
        called = []
        monkeypatch.setattr(q, "_client", lambda *a: called.append(a) or _client_returning(["x"], []))
        q.cmd_sql(_args("SELECT 1"))
        assert called == [()]

    def test_make_client_profile_masks_env_auth_then_restores(self, monkeypatch):
        import os
        import sys
        import types

        from starboard_skills.helpers import contract

        monkeypatch.setenv("DATABRICKS_HOST", "https://env-host")
        monkeypatch.setenv("DATABRICKS_TOKEN", "env-token")
        seen = {}

        class FakeWC:
            def __init__(self, **kw):
                seen["kw"] = kw
                seen["host"] = os.environ.get("DATABRICKS_HOST")
                seen["token"] = os.environ.get("DATABRICKS_TOKEN")

        fake_sdk = types.ModuleType("databricks.sdk")
        fake_sdk.WorkspaceClient = FakeWC
        monkeypatch.setitem(sys.modules, "databricks.sdk", fake_sdk)

        contract.make_client("my-profile")

        assert seen["kw"] == {"profile": "my-profile"}
        assert seen["host"] is None and seen["token"] is None  # profile wins over env
        assert os.environ["DATABRICKS_HOST"] == "https://env-host"  # restored
        assert os.environ["DATABRICKS_TOKEN"] == "env-token"

    def test_timeout_polls_until_succeeded(self, monkeypatch):
        monkeypatch.setattr(q.time, "sleep", lambda _s: None)
        running = SimpleNamespace(
            statement_id="st-1", status=SimpleNamespace(state=SimpleNamespace(value="RUNNING"))
        )
        done = _client_returning(["x"], [["7"]]).statement_execution.execute_statement.return_value
        client = MagicMock()
        client.statement_execution.execute_statement.return_value = running
        client.statement_execution.get_statement.side_effect = [running, done]
        monkeypatch.setattr(q, "_client", lambda: client)
        args = _args("SELECT 1")
        args.timeout = 600
        out = q.cmd_sql(args)
        assert out["rows"] == [["7"]]
        assert client.statement_execution.get_statement.call_count == 2
        _, kwargs = client.statement_execution.execute_statement.call_args
        assert kwargs["wait_timeout"] == "50s"  # API max; the rest is polled
        client.statement_execution.cancel_execution.assert_not_called()

    def test_timeout_cancels_and_reports_value(self, monkeypatch):
        clock = {"t": 0.0}
        monkeypatch.setattr(q.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(q.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
        running = SimpleNamespace(
            statement_id="st-1", status=SimpleNamespace(state=SimpleNamespace(value="RUNNING"))
        )
        client = MagicMock()
        client.statement_execution.execute_statement.return_value = running
        client.statement_execution.get_statement.return_value = running
        monkeypatch.setattr(q, "_client", lambda: client)
        args = _args("SELECT 1")
        args.timeout = 7
        with pytest.raises(HelperError) as ei:
            q.cmd_sql(args)
        assert "did not complete" in ei.value.message
        assert "7s (--timeout)" in ei.value.message
        client.statement_execution.cancel_execution.assert_called_once_with("st-1")
        _, kwargs = client.statement_execution.execute_statement.call_args
        assert kwargs["wait_timeout"] == "7s"

    def test_default_keeps_single_wait_window_no_polling(self, monkeypatch):
        running = SimpleNamespace(
            statement_id="st-1", status=SimpleNamespace(state=SimpleNamespace(value="RUNNING"))
        )
        client = MagicMock()
        client.statement_execution.execute_statement.return_value = running
        monkeypatch.setattr(q, "_client", lambda: client)
        with pytest.raises(HelperError):
            q.cmd_sql(_args("SELECT 1"))
        client.statement_execution.get_statement.assert_not_called()
        _, kwargs = client.statement_execution.execute_statement.call_args
        assert kwargs["wait_timeout"] == "50s"

    def test_rejects_non_positive_timeout(self, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: _client_returning(["x"], []))
        args = _args("SELECT 1")
        args.timeout = 0
        with pytest.raises(ArgError):
            q.cmd_sql(args)

    def test_help_documents_profile_and_timeout(self, capsys):
        from starboard_skills.helpers.__main__ import build_parser

        with pytest.raises(SystemExit):
            build_parser().parse_args(["query", "sql", "--help"])
        out = capsys.readouterr().out
        assert "--profile" in out and "--timeout" in out


def _client_failing(error_message: str):
    """Return a mock client whose execute_statement immediately returns FAILED."""
    resp = SimpleNamespace(
        manifest=None,
        result=None,
        statement_id="st-fail",
        status=SimpleNamespace(
            state=SimpleNamespace(value="FAILED"),
            error=SimpleNamespace(message=error_message),
        ),
    )
    client = MagicMock()
    client.statement_execution.execute_statement.return_value = resp
    return client


@pytest.mark.unit
class TestCapacityHint:
    """D14: capacity hint must only appear on timeout / resource errors.

    SQL semantic/analysis errors (DATATYPE_MISMATCH, UNRESOLVED_COLUMN, …) mean
    the fix is the query text itself, not warehouse resources. The hint
    'Narrow the query or use a larger warehouse' is misleading in that context
    and must be suppressed.
    """

    @pytest.mark.parametrize(
        "error_msg",
        [
            "DATATYPE_MISMATCH: Cannot safely cast 'foo' to INT",
            "UNRESOLVED_COLUMN: column `bar` cannot be resolved",
            "TABLE_OR_VIEW_NOT_FOUND: Table or view 'missing_tbl' not found",
            "PARSE_SYNTAX_ERROR: extraneous input 'FROM' expecting",
            "INVALID_FIELD_NAME: No such field: nonexistent_col",
        ],
    )
    def test_sql_analysis_error_omits_capacity_hint(self, error_msg, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: _client_failing(error_msg))
        with pytest.raises(HelperError) as ei:
            q.cmd_sql(_args("SELECT 1"))
        msg = ei.value.message.lower()
        assert "larger warehouse" not in msg, (
            f"SQL analysis error should not suggest 'larger warehouse': {error_msg!r}"
        )
        assert "narrow the query" not in msg, (
            f"SQL analysis error should not suggest 'narrow the query': {error_msg!r}"
        )

    def test_timeout_includes_capacity_hint(self, monkeypatch):
        """A timed-out statement must still include the capacity hint."""
        clock = {"t": 0.0}
        monkeypatch.setattr(q.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(q.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
        running = SimpleNamespace(
            statement_id="st-1",
            status=SimpleNamespace(state=SimpleNamespace(value="RUNNING")),
        )
        client = MagicMock()
        client.statement_execution.execute_statement.return_value = running
        client.statement_execution.get_statement.return_value = running
        monkeypatch.setattr(q, "_client", lambda: client)
        args = _args("SELECT 1")
        args.timeout = 7
        with pytest.raises(HelperError) as ei:
            q.cmd_sql(args)
        msg = ei.value.message.lower()
        assert "larger warehouse" in msg, (
            "Timeout error must include 'larger warehouse' capacity hint"
        )

    def test_generic_failed_includes_capacity_hint(self, monkeypatch):
        """A generic FAILED error (not a SQL analysis error) must keep the capacity hint."""
        monkeypatch.setattr(
            q, "_client", lambda: _client_failing("Internal error: out of memory")
        )
        with pytest.raises(HelperError) as ei:
            q.cmd_sql(_args("SELECT 1"))
        assert "larger warehouse" in ei.value.message.lower()

    def test_sql_analysis_error_still_surfaces_original_message(self, monkeypatch):
        """The original error message must always appear even when hint is suppressed."""
        monkeypatch.setattr(
            q, "_client",
            lambda: _client_failing("UNRESOLVED_COLUMN: column `x` not found"),
        )
        with pytest.raises(HelperError) as ei:
            q.cmd_sql(_args("SELECT 1"))
        assert "UNRESOLVED_COLUMN" in ei.value.message


@pytest.mark.unit
class TestEffectiveLimit:
    """Round-3 D4: row_limit reports the cap the population is actually bounded by."""

    def test_sql_limit_smaller_than_cli_cap_is_reported(self, monkeypatch):
        rows = [[str(i)] for i in range(20)]
        monkeypatch.setattr(q, "_client", lambda: _client_returning(["x"], rows))
        out = q.cmd_sql(_args("SELECT x FROM t ORDER BY x DESC LIMIT 20", limit=1000))
        assert out["row_limit"] == 20
        assert out["sql_limit"] == 20
        assert out["cli_row_limit"] == 1000
        assert out["limit_source"] == "sql"
        assert out["limit_reached"] is True

    def test_sql_limit_not_filled(self, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: _client_returning(["x"], [["1"]] * 3))
        out = q.cmd_sql(_args("SELECT x FROM t LIMIT 25", limit=1000))
        assert out["row_limit"] == 25
        assert out["limit_reached"] is False

    def test_no_sql_limit_uses_cli_cap(self, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: _client_returning(["x"], [["1"]] * 5))
        out = q.cmd_sql(_args("SELECT x FROM t", limit=5))
        assert out["row_limit"] == 5
        assert out["sql_limit"] is None
        assert out["limit_source"] == "cli"
        assert out["limit_reached"] is True

    def test_cli_cap_smaller_than_sql_limit(self, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: _client_returning(["x"], [["1"]] * 10))
        out = q.cmd_sql(_args("SELECT x FROM t LIMIT 500", limit=10))
        assert out["row_limit"] == 10
        assert out["sql_limit"] == 500
        assert out["limit_source"] == "cli"
        assert out["limit_reached"] is True

    @pytest.mark.parametrize(
        ("sql", "expected"),
        [
            ("SELECT x FROM t LIMIT 20;", 20),
            ("SELECT x FROM t limit 20 -- top-N sample", 20),
            ("SELECT x FROM (SELECT * FROM t LIMIT 5) s", None),  # inner LIMIT only
            ("SELECT 'LIMIT 9' AS s FROM t", None),  # inside a string literal
        ],
    )
    def test_trailing_limit_parsing(self, sql, expected):
        _, sql_limit = q._effective_limit(sql, 1000)
        assert sql_limit == expected


@pytest.mark.unit
class TestPreflight:
    """Round-3 D4: fail fast on DNS/connect failures instead of slow SDK retries."""

    def test_unreachable_host_fails_fast_before_client(self, monkeypatch):
        import starboard

        def _boom():
            raise AssertionError("client must not be built when preflight fails")

        monkeypatch.setattr(q, "_preflight", _REAL_PREFLIGHT)
        monkeypatch.setattr(q, "_client", _boom)
        monkeypatch.setenv("DATABRICKS_HOST", "https://unreachable.invalid")
        monkeypatch.setattr(
            starboard,
            "check_connectivity",
            lambda host, token, timeout: SimpleNamespace(
                ok=False, kind="NETWORK", message=f"cannot reach {host}"
            ),
        )
        with pytest.raises(HelperError) as ei:
            q.cmd_sql(_args("SELECT 1"))
        assert "cannot reach https://unreachable.invalid" in ei.value.message
        assert ei.value.exit_code == 3

    def test_reachable_host_passes(self, monkeypatch):
        import starboard

        seen = {}
        monkeypatch.setenv("DATABRICKS_HOST", "https://ws.example.com")

        def _ok(host, token, timeout):
            seen.update(host=host, token=token, timeout=timeout)
            return SimpleNamespace(ok=True, kind="", message="")

        monkeypatch.setattr(starboard, "check_connectivity", _ok)
        _REAL_PREFLIGHT(None)
        assert seen["host"] == "https://ws.example.com"
        assert seen["token"] is None  # network-only probe; no credential sent
        assert seen["timeout"] <= 10

    def test_no_resolvable_host_is_noop(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABRICKS_HOST", raising=False)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
        monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(tmp_path / "missing.cfg"))
        _REAL_PREFLIGHT(None)  # must not raise or touch the network

    def test_profile_host_read_from_config_file(self, monkeypatch, tmp_path):
        cfg = tmp_path / "cfg"
        cfg.write_text("[DEFAULT]\nhost = https://default.example\n\n[p1]\nhost = https://p1.example\n")
        monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg))
        monkeypatch.setenv("DATABRICKS_HOST", "https://ambient.example")
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
        # An explicit profile wins over ambient env (make_client masks it).
        assert q._target_host("p1") == "https://p1.example"
        assert q._target_host(None) == "https://ambient.example"
        monkeypatch.delenv("DATABRICKS_HOST")
        assert q._target_host(None) == "https://default.example"


@pytest.mark.unit
class TestRowsObjects:
    """D3: ``--rows objects`` returns column-keyed dicts; the default is unchanged."""

    def test_default_rows_are_positional(self, monkeypatch):
        client = _client_returning(["a", "b"], [["1", "x"]])
        monkeypatch.setattr(q, "_client", lambda: client)
        out = q.cmd_sql(_args("SELECT a, b FROM t"))
        assert out["rows"] == [["1", "x"]]
        assert "rows_format" not in out

    def test_objects_rows_are_column_keyed(self, monkeypatch):
        client = _client_returning(["a", "b"], [["1", "x"], ["2", None]])
        monkeypatch.setattr(q, "_client", lambda: client)
        args = _args("SELECT a, b FROM t")
        args.rows = "objects"
        out = q.cmd_sql(args)
        assert out["rows"] == [{"a": "1", "b": "x"}, {"a": "2", "b": None}]
        assert out["columns"] == ["a", "b"] and out["row_count"] == 2
        assert out["rows_format"] == "objects"

    def test_cli_flag_parses(self):
        from starboard_skills.helpers.__main__ import build_parser

        ns = build_parser().parse_args(
            ["query", "sql", "--sql", "SELECT 1", "--warehouse-id", "w", "--rows", "objects"]
        )
        assert ns.rows == "objects"
        with pytest.raises(ArgError):
            build_parser().parse_args(["query", "sql", "--sql", "SELECT 1", "--rows", "dicts"])


class _FakeFrame:
    def __init__(self, columns, rows):
        self.columns = columns
        self._rows = rows

    def rows(self):
        return [tuple(r) for r in self._rows]


class _FakeExecutor:
    attempts = 2

    def __init__(self):
        self.sql = None

    async def execute_sql(self, sql):
        self.sql = sql
        return _FakeFrame(["n"], [[1], [2], [3]])


class _FakeSource:
    def __init__(self, ws):
        self.ws = ws
        self.executor = _FakeExecutor()

    def prepare(self, query, sql):
        return SimpleNamespace(sql=f"/*scoped {self.ws}*/ {sql}", executor=self.executor)


class _FakeBuilder:
    def __init__(self):
        self.built = []

    def build(self, workspace_ids=(), account=None):
        self.built.append(workspace_ids)
        return _FakeSource(workspace_ids)


@pytest.mark.unit
class TestInternalPath:
    def _args(self, **kw):
        base = {"sql": "SELECT n FROM system.billing.usage", "warehouse_id": None, "limit": 2, "param": None,
                    "profile": None, "timeout": None, "rows": None, "internal_workspace_id": "123"}
        base.update(kw)
        return SimpleNamespace(**base)

    def test_runs_scoped_through_internal_source(self, monkeypatch):
        builder = _FakeBuilder()
        monkeypatch.setattr(q, "_internal_source_builder", lambda: builder)
        out = q.cmd_sql(self._args(rows="objects"))
        assert builder.built == [("123",)]
        assert out["source"] == "internal" and out["workspace_scope"] == ["123"]
        assert out["rows"] == [{"n": 1}, {"n": 2}]  # capped at --limit
        assert out["limit_reached"] is True and out["attempts"] == 2

    def test_refused_statement_is_an_error(self, monkeypatch):
        class _Refusing(_FakeBuilder):
            def build(self, workspace_ids=(), account=None):
                return SimpleNamespace(prepare=lambda qy, s: SimpleNamespace(reason="unscoped table"))

        monkeypatch.setattr(q, "_internal_source_builder", lambda: _Refusing())
        with pytest.raises(HelperError, match="unscoped table"):
            q.cmd_sql(self._args())

    def test_read_only_guard_still_applies(self, monkeypatch):
        monkeypatch.setattr(q, "_internal_source_builder", lambda: pytest.fail("must not run"))
        with pytest.raises(ArgError):
            q.cmd_sql(self._args(sql="DROP TABLE t"))

    def test_cannot_mix_with_public_flags(self):
        with pytest.raises(ArgError, match="cannot be combined"):
            q.cmd_sql(self._args(warehouse_id="w"))

    def test_public_path_still_needs_warehouse(self):
        with pytest.raises(ArgError, match="--warehouse-id is required"):
            q.cmd_sql(self._args(internal_workspace_id=None))

    def test_missing_internal_package_is_clear(self, monkeypatch):
        monkeypatch.setattr(q.importlib_metadata, "entry_points", lambda group: [])
        with pytest.raises(HelperError, match="not installed"):
            q._internal_source_builder()


# --------------------------------------------------------------------------- #
# Round 8 (gpt-6 #5): numeric typing from the result manifest
# --------------------------------------------------------------------------- #


def _typed_client(cols, data_array):
    resp = SimpleNamespace(
        manifest=SimpleNamespace(schema=SimpleNamespace(columns=[
            SimpleNamespace(name=n, type_name=SimpleNamespace(value=t), type_scale=sc) for n, t, sc in cols
        ])),
        result=SimpleNamespace(data_array=data_array),
        status=SimpleNamespace(state=SimpleNamespace(value="SUCCEEDED")),
    )
    client = MagicMock()
    client.statement_execution.execute_statement.return_value = resp
    return client


@pytest.mark.unit
class TestNumericTyping:
    _COLS = [("job_id", "STRING", None), ("sku_name", "STRING", None), ("dbus", "DECIMAL", 4),
             ("runs", "LONG", None), ("n", "DECIMAL", 0), ("ratio", "DOUBLE", None), ("ok", "BOOLEAN", None),
             ("day", "DATE", None), ("missing", "INT", None)]

    def test_gpt6_classic_materiality_decimal_sum_is_numeric(self, monkeypatch):
        """The gpt-6 classic-jobs-materiality case: SUM(DECIMAL) came back as "2280.4682"."""
        rows = [["986258811852032", "PREMIUM_JOBS_COMPUTE", "2280.4682", "12", "7", "0.25", "true", "2026-09-01",
                 None]]
        monkeypatch.setattr(q, "_client", lambda: _typed_client(self._COLS, rows))
        out = q.cmd_sql(SimpleNamespace(sql="SELECT 1", warehouse_id="wh-1", limit=100, param=None,
                                        rows="objects"))
        row = out["rows"][0]
        assert row == {"job_id": "986258811852032", "sku_name": "PREMIUM_JOBS_COMPUTE", "dbus": 2280.4682,
                       "runs": 12, "n": 7, "ratio": 0.25, "ok": True, "day": "2026-09-01", "missing": None}
        assert isinstance(row["runs"], int) and isinstance(row["n"], int) and isinstance(row["dbus"], float)
        assert out["column_types"]["dbus"] == "DECIMAL" and out["column_types"]["job_id"] == "STRING"

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "not-a-number"])
    def test_non_finite_or_bad_values_stay_strings(self, value):
        assert q._to_number(value, "DOUBLE", None) == value

    def test_untyped_manifest_is_unchanged(self, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: _client_returning(["x"], [["1"]]))
        out = q.cmd_sql(_args("SELECT 1"))
        assert out["rows"] == [["1"]] and "column_types" not in out

    def test_internal_decimal_cells_are_numbers(self, monkeypatch):
        from decimal import Decimal

        class _DecExec(_FakeExecutor):
            async def execute_sql(self, sql):
                return _FakeFrame(["dbus", "n", "s"], [[Decimal("2280.4682"), Decimal("7"), "x"]])

        class _DecSource(_FakeSource):
            def __init__(self, ws):
                super().__init__(ws)
                self.executor = _DecExec()

        class _DecBuilder(_FakeBuilder):
            def build(self, workspace_ids=(), account=None):
                return _DecSource(workspace_ids)

        monkeypatch.setattr(q, "_internal_source_builder", lambda: _DecBuilder())
        out = q.cmd_sql(SimpleNamespace(sql="SELECT 1", warehouse_id=None, limit=10, param=None, profile=None,
                                        timeout=None, rows="objects", internal_workspace_id="123"))
        assert out["rows"] == [{"dbus": 2280.4682, "n": 7, "s": "x"}]
        assert isinstance(out["rows"][0]["n"], int)
