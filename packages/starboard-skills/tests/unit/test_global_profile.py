"""The global ``--profile`` of every ``starboard-helper`` fetch domain.

* ``--profile NAME`` is accepted before or after the subcommand for every fetch
  domain, and every client the command builds uses it (ambient
  ``DATABRICKS_HOST`` / ``DATABRICKS_TOKEN`` env auth is masked, never wins).
* ``query sql`` takes the same global flag (no domain-local one).
* On a ``--run-folder`` run whose identity was verified, an omitted ``--profile``
  defaults to the verified one and a different one is refused (exit 2,
  ``PROFILE_MISMATCH``) before any client is built.
* ``query history --warehouse-id`` filters server-side without ``--status``;
  ``query slow --warehouse-id`` filters server-side and before the limit.
"""

from __future__ import annotations

import argparse
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starboard_skills.helpers import __main__ as cli
from starboard_skills.helpers import query as q

from .conftest import make_drive_run, profile_kw, run_main

PROFILE = "acme-ws"

#: One representative workspace-reading command per fetch domain.
WORKSPACE_COMMANDS: dict[str, list[str]] = {
    "job": ["job", "list"],
    "pipeline": ["pipeline", "fetch", "--pipeline-id", "p1"],
    "query": ["query", "history"],
    "warehouse": ["warehouse", "list"],
    "uc": ["uc", "catalogs"],
    "cluster": ["cluster", "list"],
    "finops": [
        "finops", "usage", "--start-date", "2026-10-01", "--end-date", "2026-10-02",
        "--warehouse-id", "wh-1",
    ],
    "diagnostic": ["diagnostic", "workspace"],
    "analyze": ["analyze", "snapshot"],
    "database": ["database", "instances"],
    "serving": ["serving", "fetch", "--endpoint-name", "e1"],
}
#: Fetch domains that build no client (the self-describing catalog).
NO_CLIENT_COMMANDS: dict[str, list[str]] = {"discovery": ["discovery", "list"]}


class _Recorder:
    """Fake SDK client class: records each construction's kwargs and the auth env."""

    def __init__(self) -> None:
        self.built: list[dict] = []

    def __call__(self, **kw):
        self.built.append(
            {
                "kw": profile_kw(kw),
                "host": os.environ.get("DATABRICKS_HOST"),
                "token": os.environ.get("DATABRICKS_TOKEN"),
            }
        )
        client = MagicMock()
        client.statement_execution.execute_statement.return_value = SimpleNamespace(
            statement_id="st-1",
            status=SimpleNamespace(state=SimpleNamespace(value="SUCCEEDED"), error=None),
            manifest=SimpleNamespace(schema=SimpleNamespace(columns=[])),
            result=SimpleNamespace(data_array=[]),
        )
        return client


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Fake ``WorkspaceClient`` / ``AccountClient``; ambient env auth is set."""
    ws, acct = _Recorder(), _Recorder()
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", ws)
    monkeypatch.setattr("databricks.sdk.AccountClient", acct)
    monkeypatch.setenv("DATABRICKS_HOST", "https://ambient.example.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "ambient-token")
    monkeypatch.setattr(q, "_preflight", lambda profile: None)
    return SimpleNamespace(ws=ws, acct=acct)


def _error(out: str) -> str:
    return json.loads(out)["error"]


@pytest.mark.unit
class TestEveryFetchDomain:
    def test_commands_cover_every_fetch_domain(self):
        assert set(WORKSPACE_COMMANDS) | set(NO_CLIENT_COMMANDS) == set(cli._FETCH_DOMAINS)

    @pytest.mark.parametrize("domain", sorted(WORKSPACE_COMMANDS))
    @pytest.mark.parametrize("position", ["before", "after"])
    def test_profile_reaches_every_client(self, domain, position, sdk, capsys):
        cmd = WORKSPACE_COMMANDS[domain]
        argv = (
            ["--profile", PROFILE, *cmd] if position == "before" else [*cmd, "--profile", PROFILE]
        )
        code, out = run_main(argv, capsys)
        assert code == 0, out
        assert sdk.ws.built, "the command built no workspace client"
        for built in sdk.ws.built:
            assert built["kw"] == {"profile": PROFILE}
            # Ambient env auth is masked while the profile's client is built.
            assert built["host"] is None and built["token"] is None
        # ...and restored afterwards.
        assert os.environ["DATABRICKS_HOST"] == "https://ambient.example.com"

    def test_equals_form_is_accepted(self, sdk, capsys):
        code, out = run_main(["job", "list", f"--profile={PROFILE}"], capsys)
        assert code == 0, out
        assert [b["kw"] for b in sdk.ws.built] == [{"profile": PROFILE}]

    @pytest.mark.parametrize("position", ["before", "after"])
    def test_catalog_domain_accepts_profile(self, position, sdk, capsys):
        cmd = NO_CLIENT_COMMANDS["discovery"]
        argv = (
            ["--profile", PROFILE, *cmd] if position == "before" else [*cmd, "--profile", PROFILE]
        )
        code, out = run_main(argv, capsys)
        assert code == 0, out
        assert sdk.ws.built == []

    def test_without_profile_the_ambient_chain_applies(self, sdk, capsys):
        code, out = run_main(["job", "list"], capsys)
        assert code == 0, out
        assert sdk.ws.built == [
            {"kw": {}, "host": "https://ambient.example.com", "token": "ambient-token"}
        ]

    def test_dangling_profile_is_an_argument_error(self, sdk, capsys):
        code, _ = run_main(["job", "list", "--profile"], capsys)
        assert code == 4
        assert sdk.ws.built == []

    def test_every_fetch_command_documents_profile(self):
        parser = cli.build_parser()
        domains = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        for domain in cli._FETCH_DOMAINS:
            commands = next(
                a
                for a in domains.choices[domain]._actions
                if isinstance(a, argparse._SubParsersAction)
            )
            for name, leaf in commands.choices.items():
                assert any(
                    "--profile" in a.option_strings for a in leaf._actions
                ), f"{domain} {name} --help does not list --profile"

    def test_other_domains_keep_their_own_profile(self):
        # verify run owns --profile on its subcommand: argv passes through untouched.
        argv = ["verify", "run", "vt", "--profile", "p", "--out", "d"]
        assert cli._extract_run_flags(argv) == (None, False, None, argv)

    def test_leading_domain_skips_the_profile_value(self):
        assert cli._leading_domain(["--profile", "job", "query", "history"]) == "query"
        assert cli._leading_domain(["--profile=x", "job", "list"]) == "job"


@pytest.mark.unit
class TestQuerySql:
    def test_global_profile_selects_the_client_and_the_preflight_host(
        self, sdk, monkeypatch, capsys
    ):
        preflighted: list[str | None] = []
        monkeypatch.setattr(q, "_preflight", preflighted.append)
        code, out = run_main(
            ["query", "sql", "--sql", "SELECT 1", "--warehouse-id", "wh-1", "--profile", PROFILE],
            capsys,
        )
        assert code == 0, out
        assert preflighted == [PROFILE]
        assert [b["kw"] for b in sdk.ws.built] == [{"profile": PROFILE}]

    def test_profile_before_the_domain(self, sdk, capsys):
        code, out = run_main(
            ["--profile", PROFILE, "query", "sql", "--sql", "SELECT 1", "--warehouse-id", "w"],
            capsys,
        )
        assert code == 0, out
        assert [b["kw"] for b in sdk.ws.built] == [{"profile": PROFILE}]

    def test_internal_source_still_refuses_profile(self, sdk, capsys):
        code, out = run_main(
            ["query", "sql", "--sql", "SELECT 1", "--internal-workspace-id", "123",
             "--profile", PROFILE],
            capsys,
        )
        assert code == 4
        assert "--internal-workspace-id cannot be combined" in _error(out)
        assert sdk.ws.built == []


@pytest.mark.unit
class TestFinopsAccountCommands:
    def test_profile_selects_an_account_profile(self, sdk, capsys):
        code, out = run_main(["finops", "budgets", "--profile", "acme-account"], capsys)
        assert code == 0, out
        assert [b["kw"] for b in sdk.acct.built] == [{"profile": "acme-account"}]
        assert sdk.acct.built[0]["host"] is None

    def test_without_profile_the_ambient_account_chain_applies(self, sdk, capsys):
        code, out = run_main(["finops", "log-delivery"], capsys)
        assert code == 0, out
        assert [b["kw"] for b in sdk.acct.built] == [{}]


# --------------------------------------------------------------------------- #
# --run-folder: the run's verified profile
# --------------------------------------------------------------------------- #
def _verified_run(monkeypatch, *, basis="verified", workspace_profile=PROFILE):
    from starboard_skills.helpers import contract

    run = make_drive_run(basis=basis, workspace_profile=workspace_profile)
    monkeypatch.setattr(contract, "_load_storage", lambda: run.store)
    return run


@pytest.mark.unit
class TestRunFolderProfile:
    def test_omitted_profile_defaults_to_the_verified_one(self, sdk, monkeypatch, capsys):
        run = _verified_run(monkeypatch)
        code, out = run_main(["job", "list", "--run-folder", run.folder_id], capsys)
        assert code == 0, out
        assert [b["kw"] for b in sdk.ws.built] == [{"profile": PROFILE}]
        assert sdk.ws.built[0]["host"] is None  # ambient env did not win

    def test_the_verified_profile_is_accepted(self, sdk, monkeypatch, capsys):
        run = _verified_run(monkeypatch)
        code, out = run_main(
            ["--profile", PROFILE, "job", "list", "--run-folder", run.folder_id], capsys
        )
        assert code == 0, out
        assert [b["kw"] for b in sdk.ws.built] == [{"profile": PROFILE}]

    @pytest.mark.parametrize("domain", sorted(WORKSPACE_COMMANDS))
    def test_another_profile_is_refused_before_any_read(
        self, domain, sdk, monkeypatch, capsys
    ):
        run = _verified_run(monkeypatch)
        before = run.store.object_count
        code, out = run_main(
            [*WORKSPACE_COMMANDS[domain], "--run-folder", run.folder_id,
             "--profile", "someone-else", "--out", "raw/x.json"],
            capsys,
        )
        assert code == 2, out
        error = _error(out)
        assert error.startswith("PROFILE_MISMATCH")
        assert PROFILE in error and "someone-else" in error
        assert sdk.ws.built == []
        assert run.store.object_count == before

    def test_host_verified_run_refuses_any_profile(self, sdk, monkeypatch, capsys):
        run = _verified_run(monkeypatch, workspace_profile=None)
        code, out = run_main(
            ["job", "list", "--run-folder", run.folder_id, "--profile", PROFILE], capsys
        )
        assert code == 2
        assert _error(out).startswith("PROFILE_MISMATCH")
        assert "--host" in _error(out)
        assert sdk.ws.built == []

    def test_host_verified_run_reads_with_the_ambient_chain(self, sdk, monkeypatch, capsys):
        run = _verified_run(monkeypatch, workspace_profile=None)
        code, out = run_main(["job", "list", "--run-folder", run.folder_id], capsys)
        assert code == 0, out
        assert [b["kw"] for b in sdk.ws.built] == [{}]

    def test_declared_run_uses_the_given_profile(self, sdk, monkeypatch, capsys):
        run = _verified_run(monkeypatch, basis=None, workspace_profile=None)
        code, out = run_main(
            ["job", "list", "--run-folder", run.folder_id, "--profile", "other"], capsys
        )
        assert code == 0, out
        assert [b["kw"] for b in sdk.ws.built] == [{"profile": "other"}]

    def test_account_commands_never_inherit_the_workspace_profile(
        self, sdk, monkeypatch, capsys
    ):
        run = _verified_run(monkeypatch)
        code, out = run_main(["finops", "budgets", "--run-folder", run.folder_id], capsys)
        assert code == 0, out
        assert [b["kw"] for b in sdk.acct.built] == [{}]
        code, out = run_main(
            ["finops", "budgets", "--run-folder", run.folder_id, "--profile", "acct"], capsys
        )
        assert code == 0, out
        assert [b["kw"] for b in sdk.acct.built[1:]] == [{"profile": "acct"}]

    def test_query_sql_defaults_to_the_verified_profile(self, sdk, monkeypatch, capsys):
        run = _verified_run(monkeypatch)
        preflighted: list[str | None] = []
        monkeypatch.setattr(q, "_preflight", preflighted.append)
        code, out = run_main(
            ["query", "sql", "--sql", "SELECT 1", "--warehouse-id", "wh-1",
             "--run-folder", run.folder_id],
            capsys,
        )
        assert code == 0, out
        assert preflighted == [PROFILE]
        assert [b["kw"] for b in sdk.ws.built] == [{"profile": PROFILE}]


# --------------------------------------------------------------------------- #
# query history / slow: server-side warehouse filter
# --------------------------------------------------------------------------- #
def _history_client(rows):
    client = MagicMock()
    client.query_history.list.return_value = SimpleNamespace(res=rows)
    return client


def _q(qid, warehouse, duration):
    return SimpleNamespace(query_id=qid, warehouse_id=warehouse, duration=duration, status="FINISHED")


@pytest.mark.unit
class TestQueryHistoryFilter:
    def _filter(self, monkeypatch, **kw):
        client = _history_client([])
        monkeypatch.setattr(q, "_client", lambda: client)
        args = SimpleNamespace(**{"warehouse_id": None, "status": None, "limit": 25, **kw})
        q.cmd_history(args)
        return client.query_history.list.call_args.kwargs["filter_by"]

    def test_warehouse_filter_without_status(self, monkeypatch):
        f = self._filter(monkeypatch, warehouse_id="wh-1")
        assert f is not None
        assert f.warehouse_ids == ["wh-1"] and not f.statuses

    def test_status_filter_without_warehouse(self, monkeypatch):
        from databricks.sdk.service.sql import QueryStatus

        f = self._filter(monkeypatch, status="failed")
        assert f.statuses == [QueryStatus.FAILED] and not f.warehouse_ids

    def test_both_filters(self, monkeypatch):
        from databricks.sdk.service.sql import QueryStatus

        f = self._filter(monkeypatch, status="FINISHED", warehouse_id="wh-1")
        assert f.statuses == [QueryStatus.FINISHED] and f.warehouse_ids == ["wh-1"]

    def test_no_filter(self, monkeypatch):
        assert self._filter(monkeypatch) is None

    def test_no_time_range_filter_is_sent(self, monkeypatch):
        f = self._filter(monkeypatch, warehouse_id="wh-1")
        assert f.query_start_time_range is None


@pytest.mark.unit
class TestQuerySlowFilter:
    def test_warehouse_filters_server_side_and_before_the_limit(self, monkeypatch):
        # The slowest queries are on another warehouse: filtering after the limit
        # used to return none of wh-1's slow queries.
        rows = [_q(f"other-{i}", "wh-2", 90_000 + i) for i in range(5)] + [
            _q("mine-1", "wh-1", 20_000),
            _q("mine-2", "wh-1", 30_000),
            _q("fast", "wh-1", 10),
        ]
        client = _history_client(rows)
        monkeypatch.setattr(q, "_client", lambda: client)
        data = q.cmd_slow(
            SimpleNamespace(warehouse_id="wh-1", min_duration_ms=10_000, limit=2)
        )
        f = client.query_history.list.call_args.kwargs["filter_by"]
        assert f.warehouse_ids == ["wh-1"]
        assert [r["query_id"] for r in data["slow_queries"]] == ["mine-2", "mine-1"]
        assert data["count"] == 2

    def test_no_warehouse_sends_no_filter(self, monkeypatch):
        client = _history_client([_q("a", "wh-1", 50_000), _q("b", "wh-2", 60_000)])
        monkeypatch.setattr(q, "_client", lambda: client)
        data = q.cmd_slow(SimpleNamespace(warehouse_id=None, min_duration_ms=10_000, limit=1))
        assert client.query_history.list.call_args.kwargs["filter_by"] is None
        assert [r["query_id"] for r in data["slow_queries"]] == ["b"]
        assert data["scanned"] == 2
        assert data["window"] == {
            "lookback_days": None, "start": None, "end": None,
            "scanned_first_start": None, "scanned_last_start": None, "scan_capped": False,
        }

    def test_status_is_the_enum_value_not_its_repr(self, monkeypatch):
        from databricks.sdk.service.sql import QueryStatus

        row = SimpleNamespace(
            query_id="a", warehouse_id="wh-1", duration=50_000, status=QueryStatus.FINISHED
        )
        monkeypatch.setattr(q, "_client", lambda: _history_client([row]))
        data = q.cmd_slow(SimpleNamespace(warehouse_id=None, min_duration_ms=10_000, limit=5))
        assert data["slow_queries"][0]["status"] == "FINISHED"

    def test_lookback_days_sends_a_time_range_and_echoes_the_window(self, monkeypatch):
        client = _history_client([_q("a", "wh-1", 50_000)])
        monkeypatch.setattr(q, "_client", lambda: client)
        data = q.cmd_slow(
            SimpleNamespace(
                warehouse_id="wh-1", min_duration_ms=10_000, limit=5, lookback_days=7
            )
        )
        f = client.query_history.list.call_args.kwargs["filter_by"]
        span = f.query_start_time_range.end_time_ms - f.query_start_time_range.start_time_ms
        assert span == 7 * 86_400_000
        assert f.warehouse_ids == ["wh-1"]
        assert data["window"]["lookback_days"] == 7
        assert data["window"]["start"] and data["window"]["end"]

    def test_lookback_days_below_one_is_an_argument_error(self, monkeypatch):
        monkeypatch.setattr(q, "_client", lambda: _history_client([]))
        with pytest.raises(q.ArgError):
            q.cmd_slow(
                SimpleNamespace(
                    warehouse_id=None, min_duration_ms=10_000, limit=5, lookback_days=0
                )
            )

    def test_help_states_the_defaults(self):
        parser = argparse.ArgumentParser()
        q.register(parser.add_subparsers())
        slow = parser._subparsers._group_actions[0].choices["query"]
        text = slow._subparsers._group_actions[0].choices["slow"].format_help()
        assert "10000 ms" in text and "--lookback-days" in text
