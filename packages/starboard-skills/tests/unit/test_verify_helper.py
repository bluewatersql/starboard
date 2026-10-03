"""Contract for ``starboard-helper verify`` (D1): fill + run vt-<id> templates.

``verify run`` parses the template markdown by ``### vt-<id>: title`` heading
plus its ```` ```sql ```` block, fills placeholders deterministically from the
flags, refuses unfilled placeholders / non-read-only SQL / a missing
``workspace_id`` filter, runs through the ``query sql`` path, and writes the
``<vt-id>[-suffix].sql`` + ``.json`` evidence pair.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starboard_skills.helpers import __main__ as cli
from starboard_skills.helpers import query as q
from starboard_skills.helpers import verify as v
from starboard_skills.helpers.contract import ArgError, NotFoundError

_TEMPLATES = """# Verify templates

Intro text with a {not_a_template} brace.

### vt-product-totals: product totals, full days

Prose before the block.

```sql
SELECT billing_origin_product, SUM(usage_quantity) AS quantity
FROM system.billing.usage
WHERE workspace_id = '{ws}'
  AND usage_date BETWEEN DATE'{start}' AND DATE'{end}'
GROUP BY 1
```

### vt-job-run-tail: longest runs of one job

```sql
SELECT run_id FROM system.lakeflow.job_run_timeline
WHERE workspace_id = '{ws}' AND job_id = '{job_id}'
  AND period_end_time >= DATE'{start}' AND period_end_time < DATE_ADD(DATE'{end}', 1)
```

### vt-step-change: before/after

```sql
SELECT 1 FROM system.billing.usage
WHERE workspace_id = '{ws}'
  AND usage_date BETWEEN DATE'{before_start}' AND DATE'{after_end}'
  AND usage_date <> DATE'{before_end}' AND usage_date >= DATE'{step_date}'
```

### vt-change-rate: needs change_time

```sql
SELECT 1 FROM system.billing.usage
WHERE workspace_id = '{ws}' AND usage_start_time >= TIMESTAMP'{change_time}'
  AND usage_metadata.warehouse_id = '{warehouse_id}'
```

### vt-unscoped: no workspace filter (must be refused)

```sql
SELECT COUNT(*) FROM system.billing.usage WHERE usage_date >= DATE'{start}' AND usage_date <= DATE'{end}'
```

### vt-no-sql: heading without a block

Just prose.

### Not a template heading

```sql
SELECT 'ignored'
```
"""


@pytest.fixture
def tpl_file(tmp_path: Path) -> Path:
    p = tmp_path / "verify-sql.md"
    p.write_text(_TEMPLATES, encoding="utf-8")
    return p


def _run_args(tpl: Path, out: Path, vt_id="vt-product-totals", **kw):
    base = {
        "vt_id": vt_id, "templates": str(tpl), "ws": "123", "start": "2026-09-01", "end": "2026-09-30",
        "job_ids": None, "warehouse_ids": None, "pipeline_ids": None, "split_date": None, "suffix": None,
        "sets": None, "internal_workspace_id": None, "profile": None, "warehouse_id": "wh-1",
        "limit": 1000, "timeout": 600.0, "rows": "arrays", "out": str(out),
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def fake_sql(monkeypatch):
    """Capture what ``verify run`` hands to ``query sql`` (no warehouse touched)."""
    calls: list = []

    def _fake(args):
        calls.append(args)
        return {"columns": ["a"], "rows": [["1"]], "row_count": 1, "limit_reached": False,
                "state": "SUCCEEDED", "read_only": True}

    monkeypatch.setattr(q, "cmd_sql", _fake)
    return calls


@pytest.mark.unit
class TestParse:
    def test_parses_ids_titles_sql_and_placeholders(self):
        t = v.parse_templates(_TEMPLATES)
        assert list(t) == [
            "vt-product-totals", "vt-job-run-tail", "vt-step-change", "vt-change-rate", "vt-unscoped",
        ]
        assert t["vt-product-totals"].title == "product totals, full days"
        assert t["vt-product-totals"].placeholders == ["ws", "start", "end"]
        assert t["vt-product-totals"].sql.startswith("SELECT billing_origin_product")
        assert "not_a_template" not in t["vt-product-totals"].sql

    def test_duplicate_id_is_an_error(self):
        dup = _TEMPLATES + "\n### vt-product-totals: again\n\n```sql\nSELECT 1\n```\n"
        with pytest.raises(ArgError, match="defined twice"):
            v.parse_templates(dup)

    def test_real_public_and_internal_templates_parse(self):
        public = v.default_templates_path()
        assert public.name == "verify-sql.md"
        _, templates = v.load_templates(public)
        assert "vt-product-totals" in templates
        for tpl in templates.values():
            assert "ws" in tpl.placeholders, f"{tpl.vt_id} must be workspace-scoped"
        repo = Path(__file__).resolve().parents[4]
        mirror = repo / "packages/starboard-internal/skills/starboard-internal-overlay/mirror-verify.md"
        if mirror.is_file():
            _, internal = v.load_templates(mirror)
            assert set(internal) >= {"vt-product-totals"}


@pytest.mark.unit
class TestDeriveParams:
    def test_window_and_query_history_bounds(self):
        p = v.derive_params(ws="123", start="2026-09-01", end="2026-09-30")
        assert p["window_days"] == "30"
        assert (p["qh_start"], p["qh_end"]) == ("2026-09-24", "2026-09-30")
        assert p["split_date"] == "2026-09-01"  # no split → start
        assert p["lookback_days"] == "30"  # = window_days
        assert "job_id" not in p and "step_date" not in p and "change_time" not in p

    def test_short_window_qh_clamped_to_start(self):
        p = v.derive_params(ws="1", start="2026-09-28", end="2026-09-30")
        assert p["qh_start"] == "2026-09-28"

    def test_ids_quoted_and_singular_only_for_one(self):
        p = v.derive_params(ws="1", start="2026-09-01", end="2026-09-02", job_ids="11, 22",
                            warehouse_ids="abc", pipeline_ids="p-1")
        assert p["job_ids"] == "'11', '22'"
        assert "job_id" not in p
        assert (p["warehouse_id"], p["warehouse_ids"]) == ("abc", "'abc'")
        assert p["pipeline_id"] == "p-1"

    def test_split_date_bounds(self):
        p = v.derive_params(ws="1", start="2026-09-01", end="2026-09-30", split_date="2026-09-14")
        assert p["step_date"] == p["split_date"] == "2026-09-14"
        assert (p["before_start"], p["before_end"], p["after_end"]) == (
            "2026-09-07", "2026-09-13", "2026-09-20",
        )
        assert p["change_time"] == "2026-09-14 00:00:00"

    def test_set_overrides_derived(self):
        p = v.derive_params(ws="1", start="2026-09-02", end="2026-10-01", split_date="2026-09-30",
                            sets=["qh_start=2026-09-20", "window_days=3",
                                  "change_time=2026-09-30 15:18:38"])
        assert (p["qh_start"], p["qh_end"]) == ("2026-09-20", "2026-10-01")
        assert p["window_days"] == "3" and p["lookback_days"] == "30"
        assert p["change_time"] == "2026-09-30 15:18:38"

    def test_set_overrides(self):
        p = v.derive_params(ws="1", start="2026-09-01", end="2026-09-30",
                            sets=["change_time='2026-09-30 23:53:39'", "lookback_days=30"])
        assert p["change_time"] == "2026-09-30 23:53:39"
        assert p["lookback_days"] == "30"

    @pytest.mark.parametrize(
        "kw",
        [
            {"ws": "1' OR '1'='1"},
            {"start": "2026/09/01"},
            {"start": "2026-02-30"},
            {"start": "2026-09-30", "end": "2026-09-01"},
            {"job_ids": "1,2'; DROP TABLE x"},
            {"sets": ["change_time=2026-09-30'--"]},
            {"sets": ["no-equals"]},
        ],
    )
    def test_rejects_unsafe_or_bad_values(self, kw):
        base = {"ws": "1", "start": "2026-09-01", "end": "2026-09-30"}
        base.update(kw)
        with pytest.raises(ArgError):
            v.derive_params(**base)


@pytest.mark.unit
class TestRun:
    def test_writes_sql_and_json_pair_with_metadata(self, tpl_file, tmp_path, fake_sql):
        out = tmp_path / "analysis" / "verify"
        res = v.cmd_run(_run_args(tpl_file, out))
        sql = (out / "vt-product-totals.sql").read_text()
        assert "workspace_id = '123'" in sql and "DATE'2026-09-01'" in sql and "{" not in sql
        env = json.loads((out / "vt-product-totals.json").read_text())
        assert env["ok"] is True and (env["domain"], env["command"]) == ("query", "sql")
        assert env["data"]["rows"] == [["1"]]
        meta = env["data"]["verify"]
        assert meta["vt_id"] == "vt-product-totals"
        assert meta["params"] == {"ws": "123", "start": "2026-09-01", "end": "2026-09-30"}
        assert meta["source"] == "public"
        assert res["row_count"] == 1 and res["json_path"].endswith("vt-product-totals.json")
        # Same path as `query sql`: the filled SQL + public warehouse flags.
        call = fake_sql[0]
        assert call.sql == sql.strip() and call.warehouse_id == "wh-1" and call.internal_workspace_id is None

    def test_suffix_names_the_pair(self, tpl_file, tmp_path, fake_sql):
        v.cmd_run(_run_args(tpl_file, tmp_path, vt_id="vt-job-run-tail", job_ids="42", suffix="42"))
        assert (tmp_path / "vt-job-run-tail-42.sql").is_file()
        assert (tmp_path / "vt-job-run-tail-42.json").is_file()

    def test_unfilled_placeholders_listed_and_nothing_runs(self, tpl_file, tmp_path, fake_sql):
        with pytest.raises(ArgError) as exc:
            v.cmd_run(_run_args(tpl_file, tmp_path, vt_id="vt-change-rate"))
        assert "{change_time}" in exc.value.message and "{warehouse_id}" in exc.value.message
        assert not fake_sql and not list(tmp_path.glob("*.sql"))

    def test_job_id_needs_exactly_one(self, tpl_file, tmp_path, fake_sql):
        with pytest.raises(ArgError, match=r"\{job_id\}"):
            v.cmd_run(_run_args(tpl_file, tmp_path, vt_id="vt-job-run-tail", job_ids="1,2"))

    def test_missing_workspace_filter_refused(self, tpl_file, tmp_path, fake_sql):
        with pytest.raises(ArgError, match="workspace_id"):
            v.cmd_run(_run_args(tpl_file, tmp_path, vt_id="vt-unscoped"))
        assert not fake_sql

    def test_non_read_only_template_refused(self, tmp_path, fake_sql):
        bad = tmp_path / "bad.md"
        bad.write_text("### vt-bad: x\n\n```sql\nDELETE FROM t WHERE workspace_id = '{ws}'\n```\n")
        with pytest.raises(ArgError):
            v.cmd_run(_run_args(bad, tmp_path, vt_id="vt-bad"))
        assert not fake_sql

    def test_unknown_id(self, tpl_file, tmp_path, fake_sql):
        with pytest.raises(NotFoundError, match="vt-product-totals"):
            v.cmd_run(_run_args(tpl_file, tmp_path, vt_id="vt-nope"))

    def test_internal_path_scope_must_match_ws(self, tpl_file, tmp_path, fake_sql):
        with pytest.raises(ArgError, match="must equal --ws"):
            v.cmd_run(_run_args(tpl_file, tmp_path, warehouse_id=None, internal_workspace_id="999"))
        v.cmd_run(_run_args(tpl_file, tmp_path, warehouse_id=None, internal_workspace_id="123"))
        assert fake_sql[-1].internal_workspace_id == "123" and fake_sql[-1].warehouse_id is None
        env = json.loads((tmp_path / "vt-product-totals.json").read_text())
        assert env["data"]["verify"]["source"] == "internal"

    def test_needs_an_execution_target(self, tpl_file, tmp_path, fake_sql):
        with pytest.raises(ArgError, match="--internal-workspace-id"):
            v.cmd_run(_run_args(tpl_file, tmp_path, warehouse_id=None))

    def test_unused_id_flag_is_reported_not_silently_ignored(self, tpl_file, tmp_path, fake_sql, capsys):
        # vt-product-totals has no {pipeline_ids}: the flag must not look like a scope.
        out = v.cmd_run(_run_args(tpl_file, tmp_path, pipeline_ids="p-1"))
        assert out["ignored_flags"] == ["--pipeline-ids"]
        assert "--pipeline-ids ignored" in capsys.readouterr().err

    def test_used_id_flag_is_not_reported(self, tpl_file, tmp_path, fake_sql):
        out = v.cmd_run(_run_args(tpl_file, tmp_path, vt_id="vt-change-rate", warehouse_ids="abc",
                                  split_date="2026-09-30"))
        assert "ignored_flags" not in out

    def test_attempts_surfaced(self, tpl_file, tmp_path, monkeypatch):
        monkeypatch.setattr(q, "cmd_sql", lambda a: {"columns": [], "rows": [], "row_count": 0, "attempts": 2})
        assert v.cmd_run(_run_args(tpl_file, tmp_path))["attempts"] == 2

    def test_change_time_derived_from_split_date(self, tpl_file, tmp_path, fake_sql):
        v.cmd_run(_run_args(tpl_file, tmp_path, vt_id="vt-change-rate", warehouse_ids="abc",
                            split_date="2026-09-30"))
        assert "TIMESTAMP'2026-09-30 00:00:00'" in fake_sql[0].sql

    @pytest.mark.parametrize(
        "exc, expected_type",
        [
            (q.ApiError("read-only query did not complete: timed out"), q.ApiError),
            (RuntimeError("connection reset"), q.ApiError),
        ],
    )
    def test_failed_run_writes_explicit_failure_json(
        self, tpl_file, tmp_path, monkeypatch, capsys, exc, expected_type
    ):
        (tmp_path / "vt-product-totals.json").write_text('{"stale": true}')

        def _boom(args):
            raise exc

        monkeypatch.setattr(q, "cmd_sql", _boom)
        with pytest.raises(expected_type) as raised:
            v.cmd_run(_run_args(tpl_file, tmp_path, warehouse_id=None, internal_workspace_id="123"))
        env = json.loads((tmp_path / "vt-product-totals.json").read_text())
        assert env["ok"] is False and (env["domain"], env["command"]) == ("query", "sql")
        assert str(exc) in env["error"] and env["error"] == raised.value.message
        meta = env["data"]["verify"]
        assert meta["vt_id"] == "vt-product-totals" and meta["source"] == "internal"
        assert meta["sql_file"] == "vt-product-totals.sql"
        assert meta["params"] == {"ws": "123", "start": "2026-09-01", "end": "2026-09-30"}
        assert (tmp_path / "vt-product-totals.sql").is_file()
        err = capsys.readouterr().err.strip().splitlines()
        assert len(err) == 1 and "vt-product-totals: FAILED" in err[0] and str(exc) in err[0]
        assert not list(tmp_path.glob(".*.tmp"))  # atomic writes leave no temp files

    def test_interrupt_still_writes_failure_json(self, tpl_file, tmp_path, monkeypatch):
        def _interrupt(args):
            raise KeyboardInterrupt

        monkeypatch.setattr(q, "cmd_sql", _interrupt)
        with pytest.raises(KeyboardInterrupt):
            v.cmd_run(_run_args(tpl_file, tmp_path))
        env = json.loads((tmp_path / "vt-product-totals.json").read_text())
        assert env["ok"] is False and "interrupted" in env["error"]


@pytest.mark.unit
class TestCli:
    def _main(self, argv, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        return exc.value.code, json.loads(capsys.readouterr().out)

    def test_list(self, tpl_file, capsys):
        code, env = self._main(["verify", "list", "--templates", str(tpl_file)], capsys)
        assert code == 0 and env["data"]["count"] == 5
        assert env["data"]["items"][1] == {
            "id": "vt-job-run-tail", "title": "longest runs of one job",
            "placeholders": ["ws", "job_id", "start", "end"],
            "derived": ["ws", "start", "end"],
            "required": {"job_id": "--job-ids (exactly one id)", "start": "--start", "end": "--end"},
            "required_flags": ["--job-ids", "--start", "--end"],
        }
        change_rate = env["data"]["items"][3]
        assert change_rate["derived"] == ["ws"]
        assert set(change_rate["required"]) == {"change_time", "warehouse_id"}
        assert "--split-date" in change_rate["required"]["change_time"]

    def test_run_help_documents_derivation_and_parallelism(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["verify", "run", "--help"])
        out = capsys.readouterr().out
        assert "qh_start" in out and "lookback_days" in out and "change_time" in out
        assert "at most 3 verifies concurrently" in out

    def test_failed_run_exits_api_error_with_stderr_and_json(self, tpl_file, tmp_path, capsys, monkeypatch):
        def _boom(args):
            raise q.ApiError("API error: read-only query did not complete: timeout")

        monkeypatch.setattr(q, "cmd_sql", _boom)
        with pytest.raises(SystemExit) as exc:
            cli.main(["verify", "run", "vt-product-totals", "--templates", str(tpl_file), "--ws", "123",
                      "--start", "2026-09-01", "--end", "2026-09-30", "--warehouse-id", "wh-1",
                      "--out", str(tmp_path)])
        captured = capsys.readouterr()
        assert exc.value.code == 3
        assert json.loads(captured.out)["ok"] is False
        assert "FAILED" in captured.err and "timeout" in captured.err
        assert json.loads((tmp_path / "vt-product-totals.json").read_text())["ok"] is False

    def test_run_owns_out_dir(self, tpl_file, tmp_path, capsys, fake_sql):
        out = tmp_path / "verify"
        code, env = self._main(
            ["verify", "run", "vt-product-totals", "--templates", str(tpl_file), "--ws", "123",
             "--start", "2026-09-01", "--end", "2026-09-30", "--warehouse-id", "wh-1", "--out", str(out)],
            capsys,
        )
        assert code == 0 and env["ok"] is True
        assert (out / "vt-product-totals.json").is_file()

    def test_unfilled_is_arg_error_exit_4(self, tpl_file, tmp_path, capsys, fake_sql):
        code, env = self._main(
            ["verify", "run", "vt-change-rate", "--templates", str(tpl_file), "--ws", "123",
             "--start", "2026-09-01", "--end", "2026-09-30", "--warehouse-id", "wh-1", "--out", str(tmp_path)],
            capsys,
        )
        assert code == 4 and "unfilled placeholder" in env["error"]


@pytest.mark.unit
class TestIdListsAndWorkspace:
    """Round 6: id lists in every form (kimi #1); --ws defaults to the internal id (sonnet #4)."""

    _BASE = ["verify", "run", "vt-job-run-tail", "--start", "2026-09-01", "--end", "2026-09-30"]

    def _main(self, argv, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        return exc.value.code, json.loads(capsys.readouterr().out)

    def test_ids_accept_comma_space_and_list_forms(self):
        for raw in ("1,2,3", "1 2 3", ["1", "2", "3"], ["1,2", "3"], ["1", "2,3", "1"]):
            p = v.derive_params(ws="9", start="2026-09-01", end="2026-09-02", job_ids=raw)
            assert p["job_ids"] == "'1', '2', '3'", raw
            assert "job_id" not in p

    def test_invalid_id_error_names_accepted_forms(self):
        with pytest.raises(ArgError) as exc:
            v.derive_params(ws="9", start="2026-09-01", end="2026-09-02", job_ids=["1;"])
        assert "--job-ids 1,2" in exc.value.message and "--job-ids 1 2" in exc.value.message
        assert "--job-ids 1 --job-ids 2" in exc.value.message

    @pytest.mark.parametrize(
        "flags",
        [
            ["--job-ids", "11,22", "--job-ids", "33"],
            ["--job-ids", "11", "22", "33"],
            ["--job-ids", "11", "--job-ids", "22", "--job-ids", "33"],
        ],
    )
    def test_cli_id_forms_fill_the_same_list(self, flags, tpl_file, tmp_path, capsys, fake_sql):
        code, env = self._main(
            ["verify", "run", "vt-product-totals", "--templates", str(tpl_file), "--ws", "123",
             "--start", "2026-09-01", "--end", "2026-09-30", "--warehouse-id", "wh-1",
             "--out", str(tmp_path), *flags],
            capsys,
        )
        assert code == 0 and env["ok"] is True
        args = cli.build_parser().parse_args(
            ["verify", "run", "vt-x", "--start", "a", "--end", "b", "--out", "o", *flags]
        )
        p = v.derive_params(ws="1", start="2026-09-01", end="2026-09-02", job_ids=args.job_ids)
        assert p["job_ids"] == "'11', '22', '33'"

    def test_ws_defaults_to_internal_workspace_id(self, tpl_file, tmp_path, fake_sql):
        res = v.cmd_run(_run_args(tpl_file, tmp_path, ws=None, warehouse_id=None,
                                  internal_workspace_id="856932841753731"))
        assert res["params"]["ws"] == "856932841753731" and res["source"] == "internal"
        assert "workspace_id = '856932841753731'" in fake_sql[0].sql

    def test_ws_must_match_internal_when_both_given(self, tpl_file, tmp_path, fake_sql):
        with pytest.raises(ArgError, match="must equal --ws"):
            v.cmd_run(_run_args(tpl_file, tmp_path, ws="1", warehouse_id=None, internal_workspace_id="2"))
        assert not fake_sql

    def test_ws_required_on_public_path(self, tpl_file, tmp_path, fake_sql):
        with pytest.raises(ArgError, match="--ws is required"):
            v.cmd_run(_run_args(tpl_file, tmp_path, ws=None))
        assert not fake_sql

    def test_cli_internal_without_ws_runs(self, tpl_file, tmp_path, capsys, fake_sql):
        code, env = self._main(
            ["verify", "run", "vt-product-totals", "--templates", str(tpl_file),
             "--internal-workspace-id", "777", "--start", "2026-09-01", "--end", "2026-09-30",
             "--out", str(tmp_path)],
            capsys,
        )
        assert code == 0 and env["data"]["params"]["ws"] == "777"

    @pytest.mark.parametrize(
        "argv",
        [
            ["--ws", "1", "--bogus-flag", "x"],  # unrecognized argument
            ["--ws", "1", "--job-ids"],  # flag without a value
            ["--ws", "1", "--job-ids", "1;2"],  # unsafe id
            ["--ws", "1"],  # public path without --warehouse-id
            [],  # no --ws and no --internal-workspace-id
        ],
    )
    def test_bad_args_exit_non_zero_with_ok_false(self, argv, tpl_file, tmp_path, capsys, fake_sql):
        code, env = self._main([*self._BASE, "--templates", str(tpl_file), "--out", str(tmp_path), *argv], capsys)
        assert code == 4 and env["ok"] is False
        assert not fake_sql

    def test_failed_query_exits_non_zero(self, tpl_file, tmp_path, capsys, monkeypatch):
        def _boom(args):
            raise RuntimeError("warehouse went away")

        monkeypatch.setattr(q, "cmd_sql", _boom)
        code, env = self._main(
            ["verify", "run", "vt-product-totals", "--templates", str(tpl_file), "--ws", "123",
             "--start", "2026-09-01", "--end", "2026-09-30", "--warehouse-id", "wh-1", "--out", str(tmp_path)],
            capsys,
        )
        assert code != 0 and env["ok"] is False and "warehouse went away" in env["error"]

    @pytest.mark.parametrize("extra, expected", [([], "objects"), (["--rows", "arrays"], "arrays")])
    def test_rows_default_objects_arrays_still_available(self, extra, expected, tpl_file, tmp_path, capsys, fake_sql):
        code, _ = self._main(
            ["verify", "run", "vt-product-totals", "--templates", str(tpl_file), "--ws", "123",
             "--start", "2026-09-01", "--end", "2026-09-30", "--warehouse-id", "wh-1", "--out", str(tmp_path),
             *extra],
            capsys,
        )
        assert code == 0 and fake_sql[-1].rows == expected


# --------------------------------------------------------------------------- #
# Round 8 (glm #1): --start/--end only when the template needs them; arg errors write json
# --------------------------------------------------------------------------- #

_NO_WINDOW = _TEMPLATES + """
### vt-settings: settings history (no window)

```sql
SELECT job_id FROM system.lakeflow.jobs WHERE workspace_id = '{ws}' AND job_id IN ({job_ids})
```

### vt-split-only: uses split_date

```sql
SELECT 1 FROM system.billing.usage WHERE workspace_id = '{ws}' AND usage_date >= DATE'{split_date}'
```
"""


@pytest.fixture
def tpl_nowin(tmp_path: Path) -> Path:
    p = tmp_path / "verify-nowin.md"
    p.write_text(_NO_WINDOW, encoding="utf-8")
    return p


@pytest.mark.unit
class TestOptionalWindow:
    def _main(self, argv, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        return exc.value.code, json.loads(capsys.readouterr().out)

    def test_no_window_template_runs_without_start_end(self, tpl_nowin, tmp_path, capsys, fake_sql):
        code, env = self._main(
            ["verify", "run", "vt-settings", "--templates", str(tpl_nowin), "--internal-workspace-id", "777",
             "--job-ids", "348089368173138", "--out", str(tmp_path)], capsys,
        )
        assert code == 0 and env["ok"] is True
        assert env["data"]["params"] == {"ws": "777", "job_ids": "'348089368173138'"}
        assert "job_id IN ('348089368173138')" in fake_sql[0].sql

    def test_window_template_without_start_end_writes_arg_error_json(self, tpl_nowin, tmp_path, capsys, fake_sql):
        code, env = self._main(
            ["verify", "run", "vt-product-totals", "--templates", str(tpl_nowin), "--internal-workspace-id", "777",
             "--out", str(tmp_path / "v")], capsys,
        )
        assert code == 4 and env["ok"] is False and "--start and --end" in env["error"]
        assert not fake_sql
        saved = json.loads((tmp_path / "v" / "vt-product-totals.json").read_text())
        assert saved["ok"] is False and saved["error"] == env["error"]
        meta = saved["data"]["verify"]
        assert meta["arg_error"] is True and meta["source"] == "internal" and meta["sql_file"] is None
        assert meta["required_flags"] == ["--start", "--end"]
        assert not (tmp_path / "v" / "vt-product-totals.sql").exists()

    def test_one_of_start_end_is_an_error(self, tpl_nowin, tmp_path):
        with pytest.raises(ArgError, match="both --start and --end"):
            v.cmd_run(_run_args(tpl_nowin, tmp_path, end=None))
        assert json.loads((tmp_path / "vt-product-totals.json").read_text())["ok"] is False

    def test_split_date_alone_fills_split_only_template(self, tpl_nowin, tmp_path, fake_sql):
        res = v.cmd_run(_run_args(tpl_nowin, tmp_path, vt_id="vt-split-only", start=None, end=None,
                                  split_date="2026-09-10"))
        assert res["params"] == {"ws": "123", "split_date": "2026-09-10"}
        with pytest.raises(ArgError, match="split_date"):
            v.cmd_run(_run_args(tpl_nowin, tmp_path, vt_id="vt-split-only", start=None, end=None))

    @pytest.mark.parametrize(
        "kw, match",
        [
            ({"vt_id": "vt-unscoped"}, "no workspace_id"),
            ({"vt_id": "vt-change-rate"}, "unfilled placeholder"),
            ({"ws": "bad id"}, "invalid workspace id"),
            ({"warehouse_id": None}, "--internal-workspace-id"),
        ],
    )
    def test_other_arg_errors_write_ok_false_json(self, tpl_nowin, tmp_path, fake_sql, kw, match):
        with pytest.raises(ArgError, match=match):
            v.cmd_run(_run_args(tpl_nowin, tmp_path, **kw))
        stem = kw.get("vt_id", "vt-product-totals")
        env = json.loads((tmp_path / f"{stem}.json").read_text())
        assert env["ok"] is False and match in env["error"] and env["data"]["verify"]["arg_error"] is True
        assert not fake_sql

    def test_bad_suffix_writes_nothing(self, tpl_nowin, tmp_path):
        with pytest.raises(ArgError, match="--suffix"):
            v.cmd_run(_run_args(tpl_nowin, tmp_path, suffix="a/b"))
        assert not list(tmp_path.glob("*.json"))

    def test_list_required_flags_match_run_enforcement(self, tpl_nowin, tmp_path, fake_sql):
        """Single source of truth: a template whose required_flags omit --start runs without it,
        and one that lists it fails without it."""
        _, templates = v.load_templates(tpl_nowin)
        for t in templates.values():
            if "workspace_id = '{ws}'" not in t.sql:
                continue
            kw = {"vt_id": t.vt_id, "start": None, "end": None, "job_ids": "1",
                  "warehouse_ids": "w1", "pipeline_ids": "p1", "split_date": None}
            flags = v.required_flags(t)
            if any(f.startswith("--set") or "--split-date" in f for f in flags):
                continue
            if "--start" in flags:
                with pytest.raises(ArgError):
                    v.cmd_run(_run_args(tpl_nowin, tmp_path, **kw))
            else:
                v.cmd_run(_run_args(tpl_nowin, tmp_path, **kw))

    def test_real_public_templates_list_matches_runner(self):
        _, templates = v.load_templates(None)
        for t in templates.values():
            req = v.requirements(t)
            assert "ws" not in req
            uses_window = any(p in v.WINDOW_PLACEHOLDERS for p in t.placeholders)
            assert ("--start" in v.required_flags(t)) == uses_window, t.vt_id
