"""Run-4 group D1: fetch helpers, verify and exit-code mapping.

Not-found vs API error on the fetch verbs, ``CODE_NOT_IN_WORKSPACE``, retryable
``WORKSPACE_TIMEOUT``, ``STORAGE_TRANSIENT`` -> exit 8, ``query slow
--exclude-warehouse-id``, top-N ``limit_reached``, the ``--help`` epilog and the
bounded retry budget. No live calls: the SDK client is faked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import NotFound
from starboard_core.ports.engagement_storage import (
    StorageNotFoundError,
    StorageTransientError,
)
from starboard_skills.helpers import __main__ as cli
from starboard_skills.helpers import contract
from starboard_skills.helpers import query as q
from starboard_skills.helpers import verify as v

from .conftest import run_main


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    w = MagicMock()
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def _env(out: str) -> dict:
    return json.loads(out)


# --------------------------------------------------------------------------- #
# D1-2: a missing resource is exit 2 on every fetch verb
# --------------------------------------------------------------------------- #
@pytest.mark.unit
class TestNotFoundMapping:
    @pytest.mark.parametrize(
        "argv, api, method",
        [
            (["uc", "table", "--full-name", "c.s.t"], "tables", "get"),
            (["uc", "tables", "--catalog", "c", "--schema", "s"], "tables", "list"),
            (["uc", "schemas", "--catalog", "c"], "schemas", "list"),
            (["uc", "lineage", "--full-name", "c.s.t"], "lineage_tracking", "table_lineage"),
            (["job", "fetch", "--job-id", "9"], "jobs", "get"),
            (["job", "runs", "--job-id", "9"], "jobs", "list_runs"),
            (["warehouse", "fetch", "--warehouse-id", "w"], "warehouses", "get"),
            (["cluster", "fetch", "--cluster-id", "c"], "clusters", "get"),
            (["pipeline", "fetch", "--pipeline-id", "p"], "pipelines", "get"),
        ],
    )
    @pytest.mark.parametrize(
        "exc",
        [
            Exception("Table 'c.s.t' does not exist."),
            NotFound("anything"),
            Exception("RESOURCE_DOES_NOT_EXIST: gone"),
        ],
        ids=["does-not-exist", "sdk-notfound", "resource-code"],
    )
    def test_missing_is_exit_2(self, sdk, capsys, argv, api, method, exc):
        getattr(getattr(sdk, api), method).side_effect = exc
        code, out = run_main(argv, capsys)
        assert code == 2, out
        env = _env(out)
        assert env["ok"] is False and "not found" in env["error"]

    def test_other_failures_stay_exit_3(self, sdk, capsys):
        sdk.tables.get.side_effect = Exception("PERMISSION_DENIED: no access")
        code, out = run_main(["uc", "table", "--full-name", "c.s.t"], capsys)
        assert code == 3
        assert _env(out)["error"].startswith("API error:")
        assert "errors" not in _env(out)


# --------------------------------------------------------------------------- #
# D1-3: job code gap has its own errors[0].code
# --------------------------------------------------------------------------- #
@pytest.mark.unit
class TestCodeNotInWorkspace:
    def _job(self, task):
        return SimpleNamespace(
            job_id=42, settings=SimpleNamespace(tasks=[task], git_source=None)
        )

    def test_wheel_task_is_a_distinct_code_with_exit_2(self, sdk, capsys):
        task = SimpleNamespace(
            task_key="w", notebook_task=None, spark_python_task=None, attempt_number=0
        )
        sdk.jobs.get.return_value = self._job(task)
        code, out = run_main(["job", "code", "--job-id", "42"], capsys)
        assert code == 2
        env = _env(out)
        assert env["error"].startswith("code_not_in_workspace:")
        assert env["errors"][0]["code"] == "CODE_NOT_IN_WORKSPACE"
        assert env["errors"][0]["retryable"] is False

    def test_unknown_task_is_plain_not_found(self, sdk, capsys):
        task = SimpleNamespace(task_key="a", notebook_task=None, spark_python_task=None)
        sdk.jobs.get.return_value = self._job(task)
        code, out = run_main(["job", "code", "--job-id", "42", "--task-key", "zz"], capsys)
        assert code == 2
        assert "errors" not in _env(out)  # no machine code: a genuinely missing task


# --------------------------------------------------------------------------- #
# D1-4: STORAGE_TRANSIENT is exit 8 + retryable on the helper surface
# --------------------------------------------------------------------------- #
@pytest.mark.unit
class TestStorageTransient:
    def test_storage_failure_codes(self):
        transient = contract.storage_failure(StorageTransientError("rate limited"))
        assert transient is not None
        assert transient.exit_code == contract.EXIT_STORAGE_TRANSIENT == 8
        assert transient.code == "STORAGE_TRANSIENT" and transient.retryable is True
        assert transient.message.startswith("STORAGE_TRANSIENT:")
        definite = contract.storage_failure(StorageNotFoundError("gone"))
        assert definite is not None
        assert definite.exit_code == contract.EXIT_STORAGE_FAILURE == 7
        assert definite.code == "NOT_FOUND" and definite.retryable is False

    def test_main_emits_errors_for_a_storage_error_escaping_a_command(
        self, monkeypatch, capsys
    ):
        def func(args):
            raise StorageTransientError("rate limited")

        # Force the command function: parse as usual, then swap `func` before dispatch.
        real_parse = cli._HelperArgumentParser.parse_args

        def parse(self, argv=None, namespace=None):
            ns = real_parse(self, argv, namespace)
            ns.func = func
            return ns

        monkeypatch.setattr(cli._HelperArgumentParser, "parse_args", parse)
        code, out = run_main(["uc", "catalogs"], capsys)
        assert code == 8
        env = _env(out)
        assert env["ok"] is False
        assert env["errors"] == [
            {"code": "STORAGE_TRANSIENT", "message": env["error"], "retryable": True}
        ]

    def test_raise_api_error_keeps_a_storage_failure(self):
        # A Drive failure inside an SDK try block is a storage failure, not an API
        # error, and a Drive 404 is not the workspace resource being missing.
        with pytest.raises(contract.StorageFailureError) as transient:
            contract.raise_api_error(StorageTransientError("Drive get failed: ReadError"))
        assert transient.value.exit_code == 8 and transient.value.retryable is True
        with pytest.raises(contract.StorageFailureError) as gone:
            contract.raise_api_error(
                StorageNotFoundError("Drive get failed: HTTP 404 notFound"),
                not_found_message="Job 9 not found",
            )
        assert gone.value.exit_code == 7 and gone.value.code == "NOT_FOUND"

    def test_storage_exit_code_table(self):
        from starboard_core.engagement.sink import (
            EXIT_STORAGE_FAILURE,
            EXIT_STORAGE_TRANSIENT,
            storage_exit_code,
        )

        assert storage_exit_code("STORAGE_TRANSIENT") == EXIT_STORAGE_TRANSIENT == 8
        for code in ("BLOCKED_ACCESS", "STORAGE_INTEGRITY", "NOT_FOUND", "STORAGE_ERROR"):
            assert storage_exit_code(code) == EXIT_STORAGE_FAILURE == 7


# --------------------------------------------------------------------------- #
# D1-5: timeouts are retryable WORKSPACE_TIMEOUT (exit 3); bounded retry budget
# --------------------------------------------------------------------------- #
@pytest.mark.unit
class TestWorkspaceTimeout:
    def test_sdk_retry_timeout_is_retryable(self, sdk, capsys):
        sdk.query_history.list.side_effect = TimeoutError("Timed out after 0:05:00")
        code, out = run_main(["query", "slow", "--warehouse-id", "wh-1"], capsys)
        assert code == 3
        env = _env(out)
        assert env["error"] == "API error: Timed out after 0:05:00"
        assert env["errors"] == [
            {"code": "WORKSPACE_TIMEOUT", "message": env["error"], "retryable": True}
        ]

    def test_message_only_timeout_is_also_retryable(self, sdk, capsys):
        sdk.jobs.get.side_effect = Exception("Timed out after 0:05:00")
        code, out = run_main(["job", "fetch", "--job-id", "1"], capsys)
        assert code == 3 and _env(out)["errors"][0]["code"] == "WORKSPACE_TIMEOUT"

    def test_client_is_built_with_a_bounded_retry_budget(self, monkeypatch):
        seen: list[object] = []
        monkeypatch.setattr(
            "databricks.sdk.WorkspaceClient", lambda *a, **k: seen.append(k) or MagicMock()
        )
        monkeypatch.delenv("DATABRICKS_RETRY_TIMEOUT_SECONDS", raising=False)
        contract.make_client()
        contract.make_client("p")
        assert [k["config"] for k in seen] == [
            {"profile": None, "retry_timeout_seconds": contract.FETCH_RETRY_TIMEOUT_S},
            {"profile": "p", "retry_timeout_seconds": contract.FETCH_RETRY_TIMEOUT_S},
        ]
        assert contract.FETCH_RETRY_TIMEOUT_S <= 240

    def test_an_operator_set_budget_wins(self, monkeypatch):
        monkeypatch.setenv("DATABRICKS_RETRY_TIMEOUT_SECONDS", "30")
        assert contract.retry_budget_s() == 30
        monkeypatch.setenv("DATABRICKS_RETRY_TIMEOUT_SECONDS", "junk")
        assert contract.retry_budget_s() == contract.FETCH_RETRY_TIMEOUT_S

    def test_the_real_sdk_config_carries_the_budget(self, monkeypatch):
        """The SDK reads no env var for the budget: it must be on the Config itself."""
        from databricks.sdk.config import Config

        monkeypatch.undo()  # drop the suite stub: build a real Config
        for k in ("DATABRICKS_RETRY_TIMEOUT_SECONDS", "DATABRICKS_CONFIG_PROFILE"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("DATABRICKS_HOST", "https://example.cloud.databricks.com")
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
        cfg = contract._sdk_config(None)
        assert isinstance(cfg, Config)
        assert cfg.retry_timeout_seconds == contract.FETCH_RETRY_TIMEOUT_S

    def test_verify_default_timeout_is_below_the_tool_limit(self):
        assert v._DEFAULT_TIMEOUT_S <= 240
        run = cli.build_parser().parse_args(
            ["verify", "run", "vt-x", "--out", "o", "--ws", "1", "--warehouse-id", "w"]
        )
        assert run.timeout == v._DEFAULT_TIMEOUT_S


# --------------------------------------------------------------------------- #
# D1-6: query slow --exclude-warehouse-id pages past excluded rows
# --------------------------------------------------------------------------- #
def _stmt(qid: str, wh: str, duration: int = 20_000, start_ms: int | None = 1_760_000_000_000):
    return SimpleNamespace(
        query_id=qid, status=None, query_text="select 1", duration=duration,
        warehouse_id=wh, query_start_time_ms=start_ms, error_message=None,
        rows_produced=1, bytes_produced=1,
    )


def _page(rows, token=None):
    return SimpleNamespace(res=rows, next_page_token=token)


def _slow_args(**kw):
    base = {
        "warehouse_id": None, "min_duration_ms": 10_000, "limit": 25, "lookback_days": None,
        "exclude_warehouse_id": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.unit
class TestQuerySlowExclude:
    def test_excluded_rows_do_not_eat_the_scan_cap(self, monkeypatch):
        busy = [_stmt(f"b{i}", "busy") for i in range(200)]
        rest = [_stmt(f"r{i}", "wh-2", 30_000 + i) for i in range(5)]
        w = MagicMock()
        w.query_history.list.side_effect = [_page(busy, "t1"), _page(rest, None)]
        monkeypatch.setattr(q, "_client", lambda: w)
        out = q.cmd_slow(_slow_args(exclude_warehouse_id=["busy"]))
        assert [s["query_id"] for s in out["slow_queries"]][0] == "r4"
        assert out["count"] == 5 and out["scanned"] == 5
        assert out["excluded"] == 200 and out["excluded_warehouse_ids"] == ["busy"]
        assert out["pages"] == 2
        assert w.query_history.list.call_args_list[1].kwargs["page_token"] == "t1"
        assert "window" in out

    def test_stops_at_200_kept_statements(self, monkeypatch):
        page = [_stmt(f"k{i}", "wh-2") for i in range(200)]
        w = MagicMock()
        w.query_history.list.return_value = _page(page, "more")
        monkeypatch.setattr(q, "_client", lambda: w)
        out = q.cmd_slow(_slow_args(exclude_warehouse_id=["busy"]))
        assert out["scanned"] == 200 and out["pages"] == 1
        assert w.query_history.list.call_count == 1

    def test_paging_is_bounded(self, monkeypatch):
        w = MagicMock()
        w.query_history.list.side_effect = lambda **k: _page(
            [_stmt("x", "busy")], "again"
        )
        monkeypatch.setattr(q, "_client", lambda: w)
        out = q.cmd_slow(_slow_args(exclude_warehouse_id=["busy"]))
        assert out["pages"] == q._EXCLUDE_MAX_PAGES and out["scanned"] == 0

    def test_repeatable_flag_and_no_exclusion_is_single_page(self, monkeypatch):
        w = MagicMock()
        rows = [_stmt("a", "w1"), _stmt("b", "w2"), _stmt("c", "w3")]
        w.query_history.list.return_value = _page(rows, None)
        monkeypatch.setattr(q, "_client", lambda: w)
        out = q.cmd_slow(_slow_args(exclude_warehouse_id=["w1", "w2", "w1"]))
        assert [s["query_id"] for s in out["slow_queries"]] == ["c"]
        assert out["excluded_warehouse_ids"] == ["w1", "w2"] and out["excluded"] == 2
        # without an exclusion the scan is one page, whatever the next-page token says
        w.query_history.list.reset_mock()
        w.query_history.list.return_value = _page(rows, "more")
        out = q.cmd_slow(_slow_args())
        assert out["count"] == 3 and "excluded" not in out
        assert w.query_history.list.call_count == 1

    def test_including_and_excluding_one_warehouse_is_an_arg_error(self, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: MagicMock())
        with pytest.raises(contract.ArgError, match="also in --exclude-warehouse-id"):
            q.cmd_slow(_slow_args(warehouse_id="w1", exclude_warehouse_id=["w1"]))

    def test_rows_carry_an_iso_start_time(self, monkeypatch):
        w = MagicMock()
        w.query_history.list.return_value = _page(
            [_stmt("a", "w1", start_ms=1_760_000_000_000), _stmt("b", "w1", start_ms=None)]
        )
        monkeypatch.setattr(q, "_client", lambda: w)
        rows = {s["query_id"]: s for s in q.cmd_slow(_slow_args())["slow_queries"]}
        assert rows["a"]["start_time"] == 1_760_000_000_000
        assert rows["a"]["start_time_iso"] == "2025-10-09T08:53:20+00:00"
        assert rows["b"]["start_time_iso"] is None

    def test_flag_parses_repeated_through_the_cli(self, sdk, capsys):
        sdk.query_history.list.return_value = _page([_stmt("a", "w9")])
        code, out = run_main(
            ["query", "slow", "--exclude-warehouse-id", "w1", "--exclude-warehouse-id", "w2"],
            capsys,
        )
        assert code == 0, out
        assert _env(out)["data"]["excluded_warehouse_ids"] == ["w1", "w2"]


# --------------------------------------------------------------------------- #
# D1-7: limit_reached is about the row cap, not a top-N's own LIMIT
# --------------------------------------------------------------------------- #
@pytest.mark.unit
class TestTopN:
    @pytest.mark.parametrize(
        "rows, effective, sql_limit, cli, expected",
        [
            (15, 15, 15, 1000, {"limit_reached": False, "top_n": 15}),
            (3, 15, 15, 1000, {"limit_reached": False, "top_n": 15}),
            (1000, 1000, None, 1000, {"limit_reached": True}),
            (999, 1000, None, 1000, {"limit_reached": False}),
            # the CLI cap is the smaller one: a real truncation
            (20, 20, 50, 20, {"limit_reached": True}),
        ],
    )
    def test_limit_flags(self, rows, effective, sql_limit, cli, expected):
        assert q._limit_flags(rows, effective, sql_limit, cli) == expected

    def test_verify_summary_reports_top_n(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            q, "cmd_sql",
            lambda a: {"columns": ["a"], "rows": [["1"]], "row_count": 15,
                       "limit_reached": False, "top_n": 15, "state": "SUCCEEDED",
                       "read_only": True},
        )
        args = SimpleNamespace(
            vt_id="vt-step-change", templates=None, ws="123", start=None, end=None,
            job_ids=None, warehouse_ids=None, pipeline_ids=None, endpoint_ids=None, split_date="2026-10-03",
            suffix=None, sets=None, internal_workspace_id=None, profile=None,
            warehouse_id="wh-1", limit=1000, timeout=240.0, rows="objects",
            out=str(tmp_path),
        )
        out = v.cmd_run(args)
        assert out["limit_reached"] is False and out["top_n"] == 15


# --------------------------------------------------------------------------- #
# D1-1: verify run works without --templates (bundled verify-sql.md)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_verify_run_defaults_to_the_bundled_templates(monkeypatch, tmp_path):
    calls: list = []

    def fake(args):
        calls.append(args.sql)
        return {"columns": ["a"], "rows": [["1"]], "row_count": 1, "limit_reached": False,
                "state": "SUCCEEDED", "read_only": True}

    monkeypatch.setattr(q, "cmd_sql", fake)
    args = SimpleNamespace(
        vt_id="vt-product-totals", templates=None, ws="123", start="2026-09-01",
        end="2026-09-30", job_ids=None, warehouse_ids=None, pipeline_ids=None, endpoint_ids=None,
        split_date=None, suffix=None, sets=None, internal_workspace_id=None, profile=None,
        warehouse_id="wh-1", limit=1000, timeout=240.0, rows="objects", out=str(tmp_path),
    )
    out = v.cmd_run(args)
    assert out["vt_id"] == "vt-product-totals" and calls
    meta = json.loads((tmp_path / "vt-product-totals.json").read_text())["data"]["verify"]
    assert meta["templates"].endswith("references/verify-sql.md")


@pytest.mark.unit
def test_verify_run_does_not_require_templates_on_the_cli():
    parsed = cli.build_parser().parse_args(
        ["verify", "run", "vt-product-totals", "--out", "o", "--ws", "1", "--warehouse-id", "w"]
    )
    assert parsed.templates is None


# --------------------------------------------------------------------------- #
# D1-8: vt-pipeline-updates exposes first/last update start/end
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_pipeline_updates_template_has_first_and_last_update_times():
    _, templates = v.load_templates(None)
    sql = templates["vt-pipeline-updates"].sql
    for col in ("first_update_start", "last_update_start", "first_update_end", "last_update_end"):
        assert f"AS {col}" in sql


# --------------------------------------------------------------------------- #
# D1-9: every fetch leaf's --help names the global flags
# --------------------------------------------------------------------------- #
@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [["query", "slow"], ["uc", "table"], ["job", "code"], ["pipeline", "events"], ["warehouse", "list"]],
)
def test_subcommand_help_names_the_global_flags(argv, capsys):
    with pytest.raises(SystemExit):
        cli.main([*argv, "--help"])
    text = " ".join(capsys.readouterr().out.split())
    for flag in ("--profile", "--out", "--run-folder", "--stdout"):
        assert flag in text
    assert "global flags" in text


@pytest.mark.unit
def test_verify_run_help_is_not_given_the_fetch_epilog(capsys):
    with pytest.raises(SystemExit):
        cli.main(["verify", "run", "--help"])
    assert "global flags (accepted before or after the subcommand)" not in capsys.readouterr().out
