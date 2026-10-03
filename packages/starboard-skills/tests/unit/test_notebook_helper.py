"""Contract for ``starboard-helper notebook render`` (D2).

Renders ``<opportunity-slug>.py`` from the engagement ``templates/notebook.py``
in Databricks source format (header, ``# COMMAND ----------``, ``# MAGIC %md``
markdown cells), filled from a backlog item, with no ``{{X}}`` left. The
evidence cell embeds PUBLIC ``system.*`` SQL rebuilt from the cited verify run.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starboard_skills.helpers import __main__ as cli
from starboard_skills.helpers import notebook as nb
from starboard_skills.helpers.contract import ApiError, ArgError, NotFoundError

_WS = "856932841753731"

#: Source-side templates (a stand-in for the internal ones: different table names).
_SOURCE_TEMPLATES = """
### vt-warehouse-queue: daily queueing

```sql
SELECT date_trunc('DAY', start_time) AS d, COUNT(*) AS queries
FROM other_catalog.other_schema.query_history
WHERE workspace_id = '{ws}'
  AND compute.warehouse_id = '{warehouse_id}'
  AND start_time >= DATE'{qh_start}'
  AND start_time <  DATE_ADD(DATE'{qh_end}', 1)
GROUP BY 1
```
"""


def _backlog() -> dict:
    return {
        "workspace_id": _WS,
        "items": [
            {
                "id": "OPP-WH-QUEUE", "title": "dashboards warehouse: queueing", "tier": "act_now",
                "confidence": 9,
                "sizing": {"kind": "perf_metric", "value": 23.6, "unit": "queued_pct (peak day)",
                           "formula": "vt-warehouse-queue: 7.6-23.6%"},
                "evidence": ["W-W01", "analysis/verify/vt-warehouse-queue-c389980b7b55cfb6.json"],
                "lever": "Warehouse c389980b7b55cfb6 max_num_clusters 1 -> 2",
                "notebook": "deliverables/notebooks/opp-wh-queue-c389980b7b55cfb6.py",
            },
            {
                "id": "OPP-WH-QUEUE", "title": "starter warehouse: queueing", "tier": "investigate",
                "confidence": 6,
                "sizing": {"kind": "perf_metric", "value": 12, "unit": "queued_pct"},
                "evidence": ["analysis/verify/vt-warehouse-queue-c63f916e2f968c5e.json"],
                "lever": "Warehouse c63f916e2f968c5e: raise max clusters",
                "notebook": "deliverables/notebooks/opp-wh-queue-c63f916e2f968c5e.py",
            },
            {
                "id": "OPP-JOB-FAILURE", "title": "failing job", "tier": "investigate",
                "confidence": 5, "job_id": "42",
                "sizing": {"kind": "bounded_dbu", "value": 1234.0, "unit": "DBU",
                           "formula": "12 failed runs x 102.8 DBU"},
                "evidence": ["analysis/verify/vt-product-totals.json"],
                "lever": "Fix the failing task on job 42",
                "notebook": None,
            },
            {
                "id": "OPP-PO", "title": "not now", "tier": "not_now",
                "sizing": {"kind": "none"}, "evidence": [], "lever": None, "notebook": None,
            },
        ],
    }


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    vdir = tmp_path / "analysis" / "verify"
    vdir.mkdir(parents=True)
    (tmp_path / "analysis" / "backlog.json").write_text(json.dumps(_backlog()))
    # 1) produced by `verify run` (metadata present, internal source).
    (vdir / "vt-warehouse-queue-c389980b7b55cfb6.json").write_text(json.dumps({
        "ok": True, "domain": "query", "command": "sql",
        "data": {"columns": [], "rows": [], "verify": {
            "vt_id": "vt-warehouse-queue", "source": "internal",
            "params": {"ws": _WS, "warehouse_id": "c389980b7b55cfb6",
                       "qh_start": "2026-09-24", "qh_end": "2026-09-30"}}},
    }))
    # 2) hand-run pair filled from the source-side templates (no metadata).
    (vdir / "vt-warehouse-queue-c63f916e2f968c5e.json").write_text(json.dumps({"ok": True, "data": {}}))
    (vdir / "vt-warehouse-queue-c63f916e2f968c5e.sql").write_text(
        "SELECT date_trunc('DAY', start_time) AS d, COUNT(*) AS queries\n"
        "FROM other_catalog.other_schema.query_history\n"
        f"WHERE workspace_id = '{_WS}'\n"
        "  AND compute.warehouse_id = 'c63f916e2f968c5e'\n"
        "  AND start_time >= DATE'2026-09-20'\n"
        "  AND start_time <  DATE_ADD(DATE'2026-09-26', 1)\n"
        "GROUP BY 1\n"
    )
    # 3) a hand-run public system.* query (embedded as-is).
    (vdir / "vt-product-totals.json").write_text(json.dumps({"ok": True, "data": {}}))
    (vdir / "vt-product-totals.sql").write_text(
        f"SELECT SUM(usage_quantity) FROM system.billing.usage WHERE workspace_id = '{_WS}'\n"
    )
    (tmp_path / "source.md").write_text(_SOURCE_TEMPLATES)
    return tmp_path


def _args(run_dir: Path, **kw):
    base = {"backlog": str(run_dir / "analysis" / "backlog.json"), "item": None, "render_all": False,
                "run_dir": None, "out": str(run_dir / "deliverables" / "notebooks"), "template": None,
                "verify_templates": None, "source_templates": None}
    base.update(kw)
    return SimpleNamespace(**base)


def _cells(text: str) -> list[str]:
    return [c.strip("\n") for c in text.split("# COMMAND ----------")]


@pytest.mark.unit
class TestSelection:
    def test_ambiguous_id_lists_targets(self, run_dir):
        with pytest.raises(ArgError) as exc:
            nb.cmd_render(_args(run_dir, item=["OPP-WH-QUEUE"]))
        assert "OPP-WH-QUEUE:c389980b7b55cfb6" in exc.value.message
        assert "OPP-WH-QUEUE:c63f916e2f968c5e" in exc.value.message

    def test_unknown_item(self, run_dir):
        with pytest.raises(NotFoundError):
            nb.cmd_render(_args(run_dir, item=["OPP-NOPE"]))

    def test_all_renders_act_now_and_investigate_only(self, run_dir):
        res = nb.cmd_render(_args(run_dir, render_all=True))
        names = sorted(Path(n["path"]).name for n in res["notebooks"])
        assert names == [
            "opp-job-failure-42.py",
            "opp-wh-queue-c389980b7b55cfb6.py",
            "opp-wh-queue-c63f916e2f968c5e.py",
        ]

    def test_filename_matches_backlog_link(self):
        item = _backlog()["items"][0]
        assert nb.notebook_filename(item, None) == "opp-wh-queue-c389980b7b55cfb6.py"
        assert nb.notebook_filename(item, "c389980b7b55cfb6") == "opp-wh-queue-c389980b7b55cfb6.py"
        assert nb.notebook_filename({"id": "OPP-X"}, None) == "opp-x.py"
        assert nb.item_target(item) == "c389980b7b55cfb6"


@pytest.mark.unit
class TestRender:
    def test_perf_metric_notebook_structure_and_public_sql(self, run_dir):
        res = nb.cmd_render(_args(run_dir, item=["OPP-WH-QUEUE:c389980b7b55cfb6"]))
        text = Path(res["notebooks"][0]["path"]).read_text()
        assert text.startswith("# Databricks notebook source\n")
        assert "{{" not in text
        cells = _cells(text)
        md = [c for c in cells if c.startswith("# MAGIC")]
        assert md and all(c.splitlines()[0] == "# MAGIC %md" for c in md)
        assert all(ln.startswith("# MAGIC") for c in md for ln in c.splitlines())
        title = md[0]
        assert "# MAGIC # dashboards warehouse: queueing" in title
        assert "**Sizing (perf_metric):** 23.6 queued_pct (peak day)" in title
        assert "Expected recoverable DBU" not in title  # bounded-only lines dropped
        assert "> Example" not in title and "<!--" not in title
        assert f"Workspace: `{_WS}`" in title and "act_now" in title and "9/10" in title
        # Evidence: the public template re-filled from the recorded params.
        assert "FROM system.query.history" in text
        assert "compute.warehouse_id = 'c389980b7b55cfb6'" in text
        assert "DATE'2026-09-24'" in text
        # Post-change cell for perf_metric, with window placeholders left for change_date.
        assert "## Post-change measurement" in text and 'change_date = ""' in text
        assert "DATE'{qh_start}'" in text
        # Remediation is commented out and carries the lever.
        assert "#   Warehouse c389980b7b55cfb6 max_num_clusters 1 -> 2" in text
        assert "targets = [\n    ('c389980b7b55cfb6'," in text
        assert res["notebooks"][0]["evidence_embedded"] == [
            "analysis/verify/vt-warehouse-queue-c389980b7b55cfb6.json"
        ]
        compile(text, "nb.py", "exec")  # valid Python source

    def test_hand_run_evidence_recovered_via_source_templates(self, run_dir):
        args = _args(run_dir, item=["OPP-WH-QUEUE:c63f916e2f968c5e"],
                     source_templates=str(run_dir / "source.md"))
        text = Path(nb.cmd_render(args)["notebooks"][0]["path"]).read_text()
        assert "FROM system.query.history" in text
        assert "other_catalog" not in text
        assert "compute.warehouse_id = 'c63f916e2f968c5e'" in text and "DATE'2026-09-20'" in text

    def test_unrecoverable_evidence_stops_clearly(self, run_dir):
        res = nb.cmd_render(_args(run_dir, item=["OPP-WH-QUEUE:c63f916e2f968c5e"]))
        text = Path(res["notebooks"][0]["path"]).read_text()
        assert "other_catalog" not in text
        assert "raise NotImplementedError" in text
        assert res["notebooks"][0]["evidence_not_embedded"] == [
            "analysis/verify/vt-warehouse-queue-c63f916e2f968c5e.json"
        ]

    def test_bounded_dbu_variant(self, run_dir):
        res = nb.cmd_render(_args(run_dir, item=["OPP-JOB-FAILURE"]))
        text = Path(res["notebooks"][0]["path"]).read_text()
        assert "**Expected recoverable DBU:** 1,234 DBU (list-price estimate)" in text
        assert "Arithmetic: `12 failed runs x 102.8 DBU`" in text
        assert "FROM system.billing.usage" in text  # public .sql embedded as-is
        assert "## Post-change measurement" not in text
        assert "{{" not in text
        compile(text, "nb.py", "exec")

    def test_template_without_title_cell_fails(self, run_dir, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("# Databricks notebook source\n")
        with pytest.raises(ApiError, match="FINDING_TITLE"):
            nb.cmd_render(_args(run_dir, item=["OPP-JOB-FAILURE"], template=str(bad)))

    def test_unfilled_placeholder_is_rejected(self, run_dir, tmp_path):
        tpl = tmp_path / "t.py"
        tpl.write_text(
            "# Databricks notebook source\n\n# COMMAND ----------\n\n"
            "# MAGIC %md\n# MAGIC # {{FINDING_TITLE}}\n# MAGIC {{SOMETHING_NEW}}\n"
        )
        with pytest.raises(ApiError, match="SOMETHING_NEW"):
            nb.cmd_render(_args(run_dir, item=["OPP-JOB-FAILURE"], template=str(tpl)))

    def test_validate_rejects_bad_markdown_cell(self):
        with pytest.raises(ApiError, match="MAGIC"):
            nb.validate_notebook(
                "# Databricks notebook source\n\n# COMMAND ----------\n\n# MAGIC %md\n# MAGIC x\nplain\n"
            )


@pytest.mark.unit
def test_cli_render_owns_out_dir(run_dir, capsys):
    out = run_dir / "nbs"
    with pytest.raises(SystemExit) as exc:
        cli.main(["notebook", "render", "--backlog", str(run_dir / "analysis" / "backlog.json"),
                  "--item", "OPP-JOB-FAILURE", "--run-dir", str(run_dir), "--out", str(out)])
    env = json.loads(capsys.readouterr().out)
    assert exc.value.code == 0 and env["ok"] is True
    assert (out / "opp-job-failure-42.py").is_file()


def _render(item: dict, evidence: list | None = None, target: str | None = None, deployment=None) -> str:
    template = nb._verify.skill_file(*nb.NOTEBOOK_TEMPLATE_REL).read_text(encoding="utf-8")
    return nb.render_notebook(item, target=target, workspace_id=_WS, template_text=template,
                              evidence=evidence or [], deployment=deployment)


def _remediation(text: str) -> str:
    return next(c for c in _cells(text) if c.startswith("# DESTRUCTIVE"))


_JOB_ITEM = {
    "id": "OPP-JOB-OVERLAP", "target": "job:421876946880414", "tier": "act_now",
    "title": "Vote Processing: hourly CRON runs stack up",
    "sizing": {"kind": "perf_metric", "metric": "pct_runs_started_while_running", "value": 81.9, "unit": "%"},
    "lever": "Job max_concurrent_runs: 1 with queue: {enabled: false}",
}


@pytest.mark.unit
class TestFindingAndRemediation:
    def test_finding_line_uses_finding_then_title_not_lever(self):
        text = _render(_JOB_ITEM)
        assert "**Finding:** Vote Processing: hourly CRON runs stack up" in text
        assert "**Lever:** Job max_concurrent_runs: 1" in text
        text = _render({**_JOB_ITEM, "finding": "81.9% of CRON runs start on top of another"})
        assert "**Finding:** 81.9% of CRON runs start on top of another" in text

    def test_target_field_kind_prefix(self):
        assert nb.item_target(_JOB_ITEM) == "421876946880414"
        assert nb.item_target({"id": "OPP-X", "target": "workspace"}) is None

    @pytest.mark.parametrize(
        "kind, text, expected",
        [
            ("cli", "databricks jobs update 1 --json '{\"new_settings\": {\"max_concurrent_runs\": 2}}'",
             ["# databricks jobs update 1 --json '{\"new_settings\": {\"max_concurrent_runs\": 2}}'"]),
            ("sql", "ALTER TABLE a.b.c SET TBLPROPERTIES ('x' = 'y')",
             ['# spark.sql("""', "# ALTER TABLE a.b.c SET TBLPROPERTIES ('x' = 'y')", '# """)']),
            ("json", '{\n  "max_concurrent_runs": 2\n}', ["# {", '#   "max_concurrent_runs": 2', "# }"]),
        ],
    )
    def test_lever_command_rendered_verbatim_and_commented(self, kind, text, expected):
        cell = _remediation(_render({**_JOB_ITEM, "lever_command": {"kind": kind, "text": text}}))
        assert "# Command (backlog lever_command):" in cell
        lines = cell.splitlines()
        start = lines.index(expected[0])
        assert lines[start:start + len(expected)] == expected
        assert all(ln.startswith("#") or not ln for ln in lines)  # nothing executes
        assert "# Rollback:" in cell

    def test_default_job_overlap_command(self):
        cell = _remediation(_render(_JOB_ITEM))
        assert "# databricks jobs get 421876946880414 > job-421876946880414-before.json" in cell
        assert ("# databricks jobs update 421876946880414 --json "
                "'{\"new_settings\": {\"max_concurrent_runs\": 1, \"queue\": {\"enabled\": false}}}'") in cell
        assert "default for OPP-JOB-OVERLAP" in cell and "# Rollback:" in cell
        assert "# restore from job-421876946880414-before.json (captured above)" in cell
        assert "<" not in cell
        assert all(ln.startswith("#") or not ln for ln in cell.splitlines())

    @pytest.mark.parametrize(
        "opp, target, lever, apply, rollback",
        [
            ("OPP-WH-QUEUE", "c389980b7b55cfb6", "Warehouse max_num_clusters 1 -> 2",
             "databricks warehouses edit c389980b7b55cfb6 --max-num-clusters 2",
             "databricks warehouses edit c389980b7b55cfb6 --max-num-clusters 1"),
            ("OPP-WH-QUEUE", "c389980b7b55cfb6", "Warehouse max_num_clusters 2 → 3",  # docs' arrow
             "databricks warehouses edit c389980b7b55cfb6 --max-num-clusters 3",
             "databricks warehouses edit c389980b7b55cfb6 --max-num-clusters 2"),
            ("OPP-WH-RESIZE", "ca580fec2da67daf", "cluster_size LARGE → MEDIUM",
             "--cluster-size Medium", "--cluster-size Large"),
            ("OPP-WH-RESIZE", "ca580fec2da67daf", "warehouse cluster_size LARGE -> MEDIUM",
             "databricks warehouses edit ca580fec2da67daf --cluster-size Medium",
             "databricks warehouses edit ca580fec2da67daf --cluster-size Large"),
            ("OPP-WH-RESIZE", "06aac8a6d9bf35db", "cluster_size 2X_LARGE -> SMALL",
             "--cluster-size Small", "--cluster-size 2X-Large"),
            ("OPP-SERVERLESS-STANDARD-MODE", "666", "performance_target: STANDARD",
             "databricks jobs update 666 --json '{\"new_settings\": {\"performance_target\": \"STANDARD\"}}'",
             "\"performance_target\": \"PERFORMANCE_OPTIMIZED\""),
            ("OPP-JOB-TIMEOUT", "348", "timeout_seconds: 12000 (just above the CRON p95, about 200 min = 12000 s)",
             "databricks jobs update 348 --json '{\"new_settings\": {\"timeout_seconds\": 12000}}'",
             "restore from job-348-before.json (captured above)"),
        ],
    )
    def test_default_commands_per_catalog_id(self, opp, target, lever, apply, rollback):
        cmd = nb.default_lever_command({"id": opp, "lever": lever}, target)
        assert cmd is not None and apply in cmd["text"] and rollback in cmd["rollback"]
        assert target in cmd["capture"]

    def test_warehouse_default_needs_stated_values_else_prose(self):
        item = {"id": "OPP-WH-QUEUE", "lever": "No capacity change now (max_clusters went 1 -> 3)"}
        assert nb.default_lever_command(item, "c63f916e2f968c5e") is None
        cell = _remediation(_render({**item, "title": "t", "target": "warehouse:c63f916e2f968c5e"}))
        assert "databricks warehouses edit" not in cell and "#     pass" in cell

    def test_unknown_catalog_id_keeps_lever_prose(self):
        cell = _remediation(_render({"id": "OPP-JOB-WAIT-TASK", "title": "t", "target": "job:1",
                                     "lever": "Replace the polling task with trigger.table_update"}))
        assert "#   Replace the polling task" in cell and "# Command" not in cell


@pytest.mark.unit
class TestEvidenceScoping:
    _SQL = (
        "SELECT job_id FROM system.lakeflow.job_run_timeline\n"
        "WHERE workspace_id = '1' AND job_id IN ('111', '222', '333')\n"
        "  AND result_state IN ('FAILED', 'ERROR')\n"
        "UNION ALL SELECT usage_metadata.job_id FROM system.billing.usage\n"
        "WHERE usage_metadata.job_id IN ( '111','222' ) AND compute.warehouse_id IN ('w1', 'w2')"
    )

    def test_scope_sql_to_target_is_deterministic(self):
        out = nb.scope_sql_to_target(self._SQL, "222")
        assert "job_id IN ('222')\n" in out
        assert "usage_metadata.job_id IN ('222')" in out
        assert "result_state IN ('FAILED', 'ERROR')" in out  # non-id list untouched
        assert "compute.warehouse_id IN ('w1', 'w2')" in out  # target not in this list
        assert nb.scope_sql_to_target(out, "222") == out
        assert nb.scope_sql_to_target(self._SQL, None) == self._SQL
        assert nb.scope_sql_to_target(self._SQL, "999") == self._SQL

    def _evidence(self, columns):
        return [{"file": "analysis/verify/vt-x-top5.json", "vt_id": "vt-x", "sql": self._SQL,
                 "template": None, "params": {}, "columns": columns}]

    def test_shared_evidence_narrowed_and_expected_omits_absent_metric(self):
        text = _render({**_JOB_ITEM, "target": "job:111"}, self._evidence(["job_id", "runs"]))
        assert "job_id IN ('111')" in text and "'333'" not in text
        assert "# Scoped to target 111" in text
        assert "81.9" not in text.split("evidence.display()")[1].split("# COMMAND")[0]
        assert "# Expected: the result reproduces the rows behind the cited sizing" in text

    def test_expected_quotes_value_when_metric_column_returned(self):
        text = _render({**_JOB_ITEM, "target": "job:111"},
                       self._evidence(["job_id", "pct_runs_started_while_running"]))
        assert "# Expected: the `pct_runs_started_while_running` column matches 81.9 %" in text

    def test_rendered_from_verify_run_json_records_columns(self, run_dir):
        ev = nb.collect_evidence(_backlog()["items"][0], run_dir, nb._verify.load_templates(None)[1])
        assert ev[0]["columns"] == []


# --------------------------------------------------------------------------- #
# Round 6: OPP-JOB-OVERLAP gating, no placeholders, measurement windows, names
# --------------------------------------------------------------------------- #

_PLACEHOLDER = __import__("re").compile(r"<[A-Za-z_][\w -]{0,30}>")
_SETTINGS_COLS = ["job_id", "name", "change_time", "deployment_kind", "deployment_metadata_file_path"]


def _settings_json(run_dir: Path, rows, objects: bool = False, name="vt-job-settings-history-top.json") -> str:
    vdir = run_dir / "analysis" / "verify"
    vdir.mkdir(parents=True, exist_ok=True)
    data_rows = [dict(zip(_SETTINGS_COLS, r, strict=True)) for r in rows] if objects else rows
    (vdir / name).write_text(json.dumps({"ok": True, "data": {"columns": _SETTINGS_COLS, "rows": data_rows}}))
    return f"analysis/verify/{name}"


@pytest.mark.unit
class TestJobOverlapDefault:
    _INV = {**_JOB_ITEM, "tier": "investigate",
            "lever": "max_concurrent_runs: 1 with queue disabled; preconditions: owner accepts the cadence "
                     "and the ONETIME backfill is finished or moved"}

    def test_investigate_gets_decision_note_not_jobs_update(self):
        cell = _remediation(_render(self._INV))
        assert "databricks jobs update" not in cell and "Rollback" not in cell
        assert "Operator decision first" in cell and "tier investigate" in cell
        assert "Cadence" in cell and "Backfill" in cell
        assert not _PLACEHOLDER.search(cell)
        assert all(ln.startswith("#") or not ln for ln in cell.splitlines())

    def test_act_now_with_unmet_precondition_gets_decision_note(self):
        item = {**_JOB_ITEM, "lever": "max_concurrent_runs: 1; cadence precondition not met yet"}
        cell = _remediation(_render(item))
        assert "databricks jobs update" not in cell
        assert "a stated precondition is not met" in cell

    @pytest.mark.parametrize("objects", [False, True])
    def test_bundle_deployed_act_now_gets_yaml_fragment(self, tmp_path, objects):
        ref = _settings_json(tmp_path, [
            ["421876946880414", "Vote", "2026-09-01T00:00:00Z", "WORKSPACE", None],
            ["421876946880414", "Vote", "2026-09-11T21:09:55Z", "BUNDLE", "/Workspace/b/.bundle/meta.json"],
            ["999", "Other", "2026-09-12T00:00:00Z", "WORKSPACE", None],
        ], objects=objects)
        item = {**_JOB_ITEM, "evidence": [ref]}
        dep = nb.job_deployment(item, tmp_path, "421876946880414")
        assert dep == {"kind": "BUNDLE", "metadata_file_path": "/Workspace/b/.bundle/meta.json", "source": ref}
        cell = _remediation(_render(item, deployment=dep))
        assert "databricks jobs update" not in cell
        assert "# Bundle YAML" in cell and "#   max_concurrent_runs: 1" in cell and "#     enabled: false" in cell
        assert "databricks bundle deploy" in cell and "/Workspace/b/.bundle/meta.json" in cell
        assert "# databricks jobs get 421876946880414 > job-421876946880414-before.json" in cell
        assert not _PLACEHOLDER.search(cell)

    def test_bundle_deployed_investigate_note_carries_fragment(self, tmp_path):
        _settings_json(tmp_path, [["421876946880414", "Vote", "2026-09-11", "BUNDLE", None]])
        dep = nb.job_deployment(self._INV, tmp_path, "421876946880414")  # found by glob, not cited
        cell = _remediation(_render(self._INV, deployment=dep))
        assert "Operator decision first" in cell and "bundle YAML, not `jobs update`" in cell
        assert "databricks jobs update" not in cell

    def test_no_settings_history_means_no_deployment(self, tmp_path):
        assert nb.job_deployment(_JOB_ITEM, tmp_path, "421876946880414") is None

    def test_timeout_without_seconds_has_no_placeholder_command(self):
        assert nb.default_lever_command({"id": "OPP-JOB-TIMEOUT", "lever": "set a timeout"}, "348") is None


@pytest.mark.unit
class TestNoPlaceholders:
    def test_rendered_notebooks_have_no_angle_placeholders(self, run_dir):
        res = nb.cmd_render(_args(run_dir, render_all=True))
        for n in res["notebooks"]:
            text = Path(n["path"]).read_text()
            assert not _PLACEHOLDER.search(text), n["path"]
            assert "--profile <name>" not in text

    def test_cli_intro_and_targets_wording(self):
        text = _render({**_JOB_ITEM, "lever_command": {"kind": "cli", "text": "databricks jobs get 1"}})
        assert "pass --profile with your CLI profile name" in text
        assert "Targets listed for verification" in text and "Targets confirmed" not in text
        empty = _render({"id": "OPP-X", "title": "t", "tier": "investigate"})
        assert not _PLACEHOLDER.search(empty)


# -- post-change measurement: execute the rendered cell against a fake Spark --------------------


class _Col:
    def __init__(self, expr):
        self.expr = expr

    def cast(self, _t):
        return self

    def __eq__(self, other):  # type: ignore[override]
        return ("eq", self.expr, other)

    def alias(self, name):
        return ("alias", self.expr, name)


class _DF:
    def __init__(self, sql, columns, log):
        self.sql, self.columns, self.log = sql, columns, log

    def filter(self, cond):
        self.log.append(("filter", self.sql[:0] or cond))
        return self

    def withColumn(self, name, value):
        self.log.append(("withColumn", name, value))
        return self

    def unionByName(self, other):
        self.log.append(("union",))
        return self

    def display(self):
        self.log.append(("display",))

    def groupBy(self, *cols):
        self.log.append(("groupBy", cols))
        return self

    def agg(self, *aggs):
        self.log.append(("agg", aggs))
        return self

    def orderBy(self, *cols):
        return self


def _run_post_change(text: str, columns: list[str], change_date: str = "2026-09-01"):
    import sys
    import types

    cell = next(c for c in _cells(text) if "post-change measurement: a baseline" in c)
    cell = cell.replace('change_date = ""', f'change_date = "{change_date}"', 1)
    sqls: list[str] = []
    log: list = []

    class _Spark:
        def sql(self, sql):
            sqls.append(sql)
            return _DF(sql, columns, log)

    fn = types.ModuleType("pyspark.sql.functions")
    fn.col = _Col  # type: ignore[attr-defined]
    fn.lit = lambda v: ("lit", v)  # type: ignore[attr-defined]
    fn.expr = _Col  # type: ignore[attr-defined]
    sql_mod = types.ModuleType("pyspark.sql")
    sql_mod.functions = fn  # type: ignore[attr-defined]
    mods = {"pyspark": types.ModuleType("pyspark"), "pyspark.sql": sql_mod, "pyspark.sql.functions": fn}
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        exec(compile(cell, "post_change", "exec"), {"spark": _Spark()})
    finally:
        for k, val in saved.items():
            if val is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = val
    return cell, sqls, log


def _public():
    return nb._verify.load_templates(None)[1]


def _ev(vt_id: str, params: dict, columns: list[str] | None = None) -> dict:
    tpl = _public()[vt_id]
    return {"file": f"analysis/verify/{vt_id}.json", "vt_id": vt_id, "template": tpl, "params": params,
            "sql": nb._verify.fill(tpl, params) if all(p in params for p in tpl.placeholders) else None,
            "columns": columns or []}


@pytest.mark.unit
class TestPostChangeMeasurement:
    _WS_P = {"ws": _WS, "start": "2026-09-02", "end": "2026-10-01"}

    def _render_post(self, item, evidence, templates=None):
        tpl = nb._verify.skill_file(*nb.NOTEBOOK_TEMPLATE_REL).read_text(encoding="utf-8")
        return nb.render_notebook(item, target=None, workspace_id=_WS, template_text=tpl,
                                  evidence=evidence, templates=templates)

    def test_standard_mode_measures_target_job_cron_dbu_and_wall_clock_per_run(self):
        item = {"id": "OPP-SERVERLESS-STANDARD-MODE", "title": "t", "tier": "investigate",
                "target": "job:348089368173138", "sizing": {"kind": "pilot", "value": None}}
        # Only the workspace mode-mix evidence is cited: vt-job-runs is rebuilt for the target.
        text = self._render_post(item, [_ev("vt-perf-target-mix", self._WS_P)], templates=_public())
        cell, sqls, log = _run_post_change(text, ["job_id", "trigger_type", "runs", "dbus"])
        assert "verify query vt-job-runs" in cell and "performance_target" not in cell
        assert len(sqls) == 2
        base, after = sqls
        assert "DATE'2026-08-25'" in base and "DATE_ADD(DATE'2026-08-31', 1)" in base
        assert "DATE'2026-09-02'" in after and "DATE_ADD(DATE'2026-09-08', 1)" in after
        assert "2026-09-01'" not in base + after  # change day in neither window
        for sql in sqls:
            assert "job_id IN ('348089368173138')" in sql and f"workspace_id = '{_WS}'" in sql
            assert "{" not in sql
        filters = [e[1] for e in log if e[0] == "filter"]
        assert "trigger_type = 'CRON'" in filters
        assert ("eq", "job_id", "348089368173138") in filters
        aliases = [a[2] for e in log if e[0] == "agg" for a in e[1]]
        assert aliases[:2] == ["dbus_per_run", "avg_run_mins"]
        assert [e[2] for e in log if e[0] == "withColumn" and e[1] == "comparison_window"] == [
            ("lit", "baseline"), ("lit", "after"),
        ]

    def test_overlap_scoped_to_target_and_metric(self):
        params = {**self._WS_P, "job_ids": "'111', '348089368173138'", "split_date": "2026-09-14"}
        item = {**_JOB_ITEM, "target": "job:348089368173138", "tier": "investigate"}
        text = self._render_post(item, [_ev("vt-job-overlap", params)])
        _, sqls, log = _run_post_change(text, ["job_id", "period", "trigger_type", "runs"])
        assert len(sqls) == 2
        for sql in sqls:
            assert "job_id IN ('348089368173138')" in sql and "'111'" not in sql
            assert "2026-09-14" not in sql  # the evidence split date is not reused
        assert "DATE'2026-08-25'" in sqls[0] and "DATE'2026-09-02'" in sqls[1]
        aliases = [a[2] for e in log if e[0] == "agg" for a in e[1]]
        assert aliases[0] == "pct_runs_started_while_running"

    def test_cadence_uses_per_window_denominators_and_pipeline_filter(self):
        pid = "1eed50fd-fabe-4349-b7b6-7119bb1d52e7"
        item = {"id": "OPP-DLT-CADENCE", "title": "t", "tier": "investigate", "target": f"pipeline:{pid}",
                "sizing": {"kind": "pilot", "value": None}}
        text = self._render_post(item, [_ev("vt-pipeline-updates", {**self._WS_P, "window_days": "30"})])
        cell, sqls, log = _run_post_change(text, ["pipeline_id", "updates", "pipeline_dbus"])
        for sql in sqls:
            assert "/ 7, 1)" in sql and "/ 30" not in sql  # updates_per_day over this window only
            assert not sql.rstrip().upper().endswith("LIMIT 15")
        assert ("eq", "pipeline_id", pid) in [e[1] for e in log if e[0] == "filter"]
        aliases = [a[2] for e in log if e[0] == "agg" for a in e[1]]
        assert aliases[0] == "dbus_per_day"

    def test_resize_change_time_comes_from_change_date(self):
        params = {"ws": _WS, "warehouse_id": "ca580fec2da67daf", "change_time": "2026-09-30 15:18:38.766"}
        item = {"id": "OPP-WH-RESIZE", "title": "t", "tier": "investigate", "target": "warehouse:ca580fec2da67daf",
                "sizing": {"kind": "perf_metric", "metric": "dbus_per_billed_hour_after", "value": 78.82,
                           "unit": "DBU/hour"}}
        text = self._render_post(item, [_ev("vt-warehouse-change-rate", params)])
        cell, sqls, log = _run_post_change(text, ["period", "billed_hours", "dbus", "dbus_per_billed_hour"])
        assert "2026-09-30" not in cell  # no literal historical change timestamp
        assert "TIMESTAMP'2026-09-01 00:00:00'" in sqls[0]  # baseline: the 7 days before change_date
        assert "TIMESTAMP'2026-09-02 00:00:00'" in sqls[1]  # after: from the first full day after
        for sql in sqls:
            assert "usage_metadata.warehouse_id = 'ca580fec2da67daf'" in sql
        filters = [e[1] for e in log if e[0] == "filter"]
        assert ("eq", "period", "a_before") in filters and ("eq", "period", "b_after") in filters
        aliases = [a[2] for e in log if e[0] == "agg" for a in e[1]]
        assert aliases[0] == "dbus_per_billed_hour"

    def test_warehouse_queue_peak_metric(self):
        params = {"ws": _WS, "warehouse_id": "c389980b7b55cfb6", "qh_start": "2026-09-24", "qh_end": "2026-09-30"}
        item = {"id": "OPP-WH-QUEUE", "title": "t", "tier": "act_now", "target": "warehouse:c389980b7b55cfb6",
                "sizing": {"kind": "perf_metric", "metric": "peak_daily_queued_pct", "value": 23.6, "unit": "%"}}
        text = self._render_post(item, [_ev("vt-warehouse-queue", params)])
        _, sqls, log = _run_post_change(text, ["query_date", "queries", "queued_pct"])
        assert "DATE'2026-08-25'" in sqls[0] and "DATE_ADD(DATE'2026-08-31', 1)" in sqls[0]
        assert "compute.warehouse_id = 'c389980b7b55cfb6'" in sqls[1]
        assert [a[2] for e in log if e[0] == "agg" for a in e[1]][0] == "peak_daily_queued_pct"

    def test_after_window_must_be_complete(self):
        import datetime as dt

        item = {"id": "OPP-WH-QUEUE", "title": "t", "tier": "act_now", "target": "warehouse:w1",
                "sizing": {"kind": "perf_metric", "metric": "peak_daily_queued_pct", "value": 1, "unit": "%"}}
        params = {"ws": _WS, "warehouse_id": "w1", "qh_start": "2026-09-24", "qh_end": "2026-09-30"}
        text = self._render_post(item, [_ev("vt-warehouse-queue", params)])
        with pytest.raises(ValueError, match="after window ends"):
            _run_post_change(text, [], change_date=str(dt.date.today() - dt.timedelta(days=3)))

    def test_no_reusable_template_falls_back_to_instructions(self):
        item = {"id": "OPP-STEP-CHANGE", "title": "t", "tier": "investigate", "target": "workspace",
                "sizing": {"kind": "none", "value": 1.0}}
        params = {"ws": _WS, "before_start": "2026-09-07", "after_end": "2026-09-20", "step_date": "2026-09-14"}
        text = self._render_post(item, [_ev("vt-step-change", params)])  # a split template: not per-window
        cell = next(c for c in _cells(text) if "READ-ONLY — post-change" in c)
        assert "No verify template" in cell and "spark.sql" not in cell
        text = self._render_post(item, [_ev("vt-step-change", params)], templates=_public())
        assert "verify query vt-daily-totals" in text  # rebuilt for the workspace


@pytest.mark.unit
class TestFilenames:
    def test_item_with_kind_prefix_matches_all(self, run_dir, capsys):
        backlog = _backlog()
        backlog["items"][2] = {**backlog["items"][2], "job_id": None, "target": "job:42"}
        (run_dir / "analysis" / "backlog.json").write_text(json.dumps(backlog))
        all_names = {Path(n["path"]).name for n in nb.cmd_render(_args(run_dir, render_all=True))["notebooks"]}
        one = nb.cmd_render(_args(run_dir, item=["OPP-JOB-FAILURE:job:42"]))["notebooks"][0]
        assert Path(one["path"]).name == "opp-job-failure-42.py" and Path(one["path"]).name in all_names
        assert one["target"] == "42"

    def test_backlog_link_used_for_item_and_all(self):
        item = {"id": "OPP-JOB-WAIT-TASK", "target": "job:1009",
                "notebook": "deliverables/notebooks/opp-job-wait-task-1009.py"}
        assert nb.notebook_filename(item, None) == nb.notebook_filename(item, "1009") == "opp-job-wait-task-1009.py"
        assert nb.notebook_filename({"id": "OPP-X", "target": "job:5"}, "job:5") == "opp-x-5.py"

    def test_stderr_one_line_summary(self, run_dir, capsys):
        nb.cmd_render(_args(run_dir, render_all=True))
        err = capsys.readouterr().err.strip().splitlines()
        assert len(err) == 1 and "wrote 3 notebook(s)" in err[0]


# -- round 7: command direction, bundle-managed jobs, measurement scope, custom evidence --------

_CFG_COLS = ["warehouse_id", "warehouse_name", "change_time", "warehouse_type", "prev_size", "warehouse_size",
             "prev_min_clusters", "min_clusters", "prev_max_clusters", "max_clusters",
             "prev_auto_stop_minutes", "auto_stop_minutes", "delete_time"]
#: The real gpt-6 round-7 vt-warehouse-config-history rows (MEDIUM -> LARGE on ca580fec2da67daf).
_CFG_ROWS = [
    ["c63f916e2f968c5e", "Serverless Starter Warehouse", "2026-09-30T23:53:39.020Z", "SERVERLESS",
     "MEDIUM", "MEDIUM", 1, 1, 1, 3, 10, 10, None],
    ["ca580fec2da67daf", "Flow Capture", "2026-09-30T15:18:38.766Z", "CLASSIC", "MEDIUM", "LARGE",
     2, 2, 2, 2, 30, 30, None],
    ["06aac8a6d9bf35db", "clayton_serverless", "2026-09-30T09:08:13.139Z", "SERVERLESS", "SMALL", "2X_LARGE",
     1, 1, 1, 1, 10, 10, None],
]
_RESIZE = {
    "id": "OPP-WH-RESIZE", "target": "warehouse:ca580fec2da67daf", "tier": "investigate",
    "title": "Review the recent size change on ca580fec2da67daf",
    "sizing": {"kind": "perf_metric", "metric": "dbus_per_billed_hour_after", "value": 78.82, "unit": "DBU/hour"},
    "evidence": ["analysis/verify/vt-warehouse-config-history.json"],
    "lever": "cluster_size MEDIUM -> LARGE on 2026-09-30 15:18:38 UTC. Confirm ingestion throughput intent; "
             "measure latency, DBU/billed-hour and volume before considering a return to MEDIUM.",
}


def _flat(cell: str) -> str:
    """Comment text of a cell as one line (``#`` prefixes and wrapping removed)."""
    return " ".join(ln.lstrip("#").strip() for ln in cell.splitlines())


def _cfg_dir(tmp_path: Path, objects: bool = False) -> Path:
    vdir = tmp_path / "analysis" / "verify"
    vdir.mkdir(parents=True, exist_ok=True)
    rows = [dict(zip(_CFG_COLS, r, strict=True)) for r in _CFG_ROWS] if objects else _CFG_ROWS
    (vdir / "vt-warehouse-config-history.json").write_text(
        json.dumps({"ok": True, "data": {"columns": _CFG_COLS, "rows": rows}}))
    return tmp_path


def _render_wh(item: dict, warehouse=None, evidence=None) -> str:
    template = nb._verify.skill_file(*nb.NOTEBOOK_TEMPLATE_REL).read_text(encoding="utf-8")
    return nb.render_notebook(item, target=None, workspace_id=_WS, template_text=template,
                              evidence=evidence or [], warehouse=warehouse)


@pytest.mark.unit
class TestWarehouseDirection:
    @pytest.mark.parametrize("objects", [False, True])
    def test_gpt6_resize_applies_target_and_rolls_back_to_current(self, tmp_path, objects):
        run = _cfg_dir(tmp_path, objects)
        wh = nb.warehouse_current(_RESIZE, run, "ca580fec2da67daf")
        assert wh is not None and wh["warehouse_size"] == "LARGE" and wh["max_clusters"] == "2"
        cell = _remediation(_render_wh(_RESIZE, wh))
        lines = cell.splitlines()
        apply_i = lines.index("# databricks warehouses edit ca580fec2da67daf --cluster-size Medium")
        rollback_i = lines.index("# databricks warehouses edit ca580fec2da67daf --cluster-size Large")
        assert lines.index("# Rollback:") < rollback_i and apply_i < lines.index("# Rollback:")
        assert "Operator decision first (tier investigate)" in cell
        assert "current cluster_size LARGE per analysis/verify/vt-warehouse-config-history.json" in cell
        assert all(ln.startswith("#") or not ln for ln in lines)

    def test_second_gpt6_resize_small_from_2x_large(self, tmp_path):
        item = {**_RESIZE, "target": "warehouse:06aac8a6d9bf35db",
                "lever": "cluster_size SMALL -> 2X_LARGE on 2026-09-30 09:08:13 UTC. Confirm workload purpose; "
                         "measure first, then consider SMALL only if the owner confirms the larger size is unnecessary."}
        wh = nb.warehouse_current(item, _cfg_dir(tmp_path), "06aac8a6d9bf35db")
        cmd = nb.default_lever_command(item, "06aac8a6d9bf35db", warehouse=wh)
        assert cmd and cmd["text"].endswith("--cluster-size Small") and cmd["rollback"].endswith("--cluster-size 2X-Large")

    def test_lever_text_only_x_is_current(self):
        cmd = nb.default_lever_command({"id": "OPP-WH-RESIZE", "tier": "act_now",
                                        "lever": "cluster_size LARGE → MEDIUM"}, "w1")
        assert cmd and cmd["text"].endswith("Medium") and cmd["rollback"].endswith("Large")
        assert "per the lever text" in cmd["note"][0] and len(cmd["note"]) == 1  # act_now: no decision-first line

    @pytest.mark.parametrize(
        "lever, why",
        [
            ("cluster_size MEDIUM -> LARGE on 2026-09-30; keep it while measuring", "restates the recorded change"),
            ("cluster_size SMALL -> MEDIUM", "does not start from the recorded current value LARGE"),
        ],
    )
    def test_contradicting_lever_gets_decision_note(self, tmp_path, lever, why):
        wh = nb.warehouse_current(_RESIZE, _cfg_dir(tmp_path), "ca580fec2da67daf")
        cell = _remediation(_render_wh({**_RESIZE, "lever": lever}, wh))
        assert "warehouses edit" not in cell and "Operator decision first — no command rendered" in cell
        assert why in _flat(cell) and not _PLACEHOLDER.search(cell)

    def test_direction_word_contradiction(self):
        cmd = nb.default_lever_command({"id": "OPP-WH-RESIZE", "lever": "downsize: cluster_size MEDIUM -> LARGE"}, "w1")
        assert cmd and cmd["kind"] == "decision" and "upsize" in cmd["lines"][0]

    def test_queue_restated_raise_is_not_reapplied(self, tmp_path):
        item = {"id": "OPP-WH-QUEUE", "target": "warehouse:c63f916e2f968c5e", "tier": "investigate",
                "lever": "max_num_clusters 1 -> 3 on 2026-09-30. Keep 3 while measuring."}
        wh = nb.warehouse_current(item, _cfg_dir(tmp_path), "c63f916e2f968c5e")
        cmd = nb.default_lever_command(item, "c63f916e2f968c5e", warehouse=wh)
        assert cmd and cmd["kind"] == "decision"

    def test_given_command_setting_current_value_is_refused(self, tmp_path):
        wh = nb.warehouse_current(_RESIZE, _cfg_dir(tmp_path), "ca580fec2da67daf")
        same = {**_RESIZE, "lever_command": {"kind": "cli",
                                             "text": "databricks warehouses edit ca580fec2da67daf --cluster-size Large"}}
        assert "already the current value" in _flat(_remediation(_render_wh(same, wh)))
        ok = {**_RESIZE, "lever_command": {"kind": "cli",
                                           "text": "databricks warehouses edit ca580fec2da67daf --cluster-size Medium"}}
        cell = _remediation(_render_wh(ok, wh))
        assert "# databricks warehouses edit ca580fec2da67daf --cluster-size Large" in cell  # rollback to current


_BUNDLE_DEP = {"kind": "BUNDLE", "metadata_file_path": None, "source": "analysis/verify/vt-job-settings-history.json"}


@pytest.mark.unit
class TestBundleManagedJobs:
    _STD = {"id": "OPP-SERVERLESS-STANDARD-MODE", "target": "job:348089368173138", "tier": "investigate",
            "title": "t", "sizing": {"kind": "pilot", "value": None},
            "lever": "pilot job-level performance_target: STANDARD for 7 days"}

    @pytest.mark.parametrize(
        "item, dep",
        [
            (_STD, _BUNDLE_DEP),
            ({**_STD, "lever": "pilot job-level performance_target: STANDARD in the bundle for 7 days"}, None),
        ],
    )
    def test_standard_mode_bundle_yaml_never_jobs_update(self, item, dep):
        cell = _remediation(_render(item, deployment=dep))
        assert "# databricks jobs update" not in cell
        assert "# Bundle YAML" in cell and "#   performance_target: STANDARD" in cell
        assert "redeploy the bundle" in cell
        assert "PERFORMANCE_OPTIMIZED on the job resource in the bundle source" in cell

    def test_workspace_job_keeps_jobs_update(self):
        dep = {**_BUNDLE_DEP, "kind": "WORKSPACE"}
        cell = _remediation(_render(self._STD, deployment=dep))
        assert "# databricks jobs update 348089368173138" in cell

    def test_timeout_bundle(self):
        item = {"id": "OPP-JOB-TIMEOUT", "target": "job:348", "tier": "act_now", "title": "t",
                "lever": "timeout_seconds: 12000 — just above the CRON p95 (12000 s)"}
        cell = _remediation(_render(item, deployment=_BUNDLE_DEP))
        assert "#   timeout_seconds: 12000" in cell and "# databricks jobs update" not in cell

    @pytest.mark.parametrize(
        "given",
        [
            {"kind": "json", "text": '{"performance_target": "STANDARD"}'},
            {"kind": "cli", "text": "databricks jobs update 348089368173138 --json "
                                    "'{\"new_settings\": {\"performance_target\": \"STANDARD\"}}'"},
        ],
    )
    def test_given_jobs_update_translated_to_bundle_yaml(self, given):
        cell = _remediation(_render({**self._STD, "lever_command": given}, deployment=_BUNDLE_DEP))
        assert "as bundle YAML (the job is bundle-managed)" in cell
        assert "#   performance_target: STANDARD" in cell and "# databricks jobs update" not in cell

    def test_given_bundle_yaml_rendered_verbatim(self):
        given = {"kind": "bundle_yaml", "text": "resources:\n  jobs:\n    leaderboard:\n      performance_target: STANDARD",
                 "rollback": "set performance_target back in the bundle and redeploy"}
        cell = _remediation(_render({**self._STD, "lever_command": given}, deployment=_BUNDLE_DEP))
        assert "# Command (backlog lever_command):" in cell and "# Bundle YAML" in cell
        assert "#       performance_target: STANDARD" in cell
        assert "# set performance_target back in the bundle and redeploy" in cell

    def test_overlap_bundle_kind(self):
        cmd = nb.default_lever_command(_JOB_ITEM, "421876946880414", deployment=_BUNDLE_DEP)
        assert cmd and cmd["kind"] == "bundle_yaml" and "redeploy the bundle" in cmd["text"]


_DRV_COLS = ["warehouse_id", "source_type", "source_id", "client_application", "queries", "read_tb",
             "avg_read_gb_per_query", "non_capacity_duration_h", "exec_duration_h", "pct_of_warehouse_exec"]
_DRV_ROWS = [
    ["c389980b7b55cfb6", "other", None, "Databricks CLI", 612, 80.3, 135.87, 26.9, 26.9, 29.4],
    ["c389980b7b55cfb6", "dashboard", "01f0f1a9ee8612beb50cf09ec2351f4b", "Databricks SQL Dashboard",
     2183, 0.11, 0.05, 26.7, 26.7, 29.2],
    ["c389980b7b55cfb6", "dashboard", "01f16688bc5719bdb992b55e5e6798f0", "Databricks SQL Dashboard",
     172, 18.92, 134.22, 22.6, 22.6, 24.7],
]


def _drv_ev(rows=None, cols=None) -> dict:
    cols = cols or _DRV_COLS
    params = {"ws": _WS, "warehouse_id": "c389980b7b55cfb6", "qh_start": "2026-09-25", "qh_end": "2026-10-01"}
    ev = _ev("vt-warehouse-drivers", params, cols)
    ev["rows"] = [dict(zip(cols, r, strict=False)) for r in (rows or _DRV_ROWS)]
    return ev


@pytest.mark.unit
class TestScanMeasurementScope:
    _ITEM = {"id": "OPP-WH-SCAN", "target": "warehouse:c389980b7b55cfb6", "tier": "investigate", "title": "t",
             "sizing": {"kind": "perf_metric", "metric": "avg_read_gb_per_query", "value": 135.87, "unit": "GB/query",
                        "formula": "Top source by execution time: other:Databricks CLI; 135.87 GB/query"}}

    def _filters(self, item, ev):
        tpl = nb._verify.skill_file(*nb.NOTEBOOK_TEMPLATE_REL).read_text(encoding="utf-8")
        text = nb.render_notebook(item, target=None, workspace_id=_WS, template_text=tpl, evidence=[ev])
        cell, sqls, log = _run_post_change(text, _DRV_COLS)
        return cell, [e[1] for e in log if e[0] == "filter"]

    def test_cited_source_with_null_id(self):
        cell, filters = self._filters(self._ITEM, _drv_ev())
        want = "source_type = 'other' AND source_id IS NULL AND client_application = 'Databricks CLI'"
        assert want in filters and "Scoped to the cited source" in cell

    def test_first_named_source_beats_supporting_mention(self):
        formula = ("Driver by execution time: Databricks CLI - 612 queries. Supporting: dashboard "
                   "01f16688bc5719bdb992b55e5e6798f0 at 134 GB/query")
        item = {**self._ITEM, "sizing": {**self._ITEM["sizing"], "formula": formula, "value": None}}
        _, filters = self._filters(item, _drv_ev())
        assert any("client_application = 'Databricks CLI'" in str(f) for f in filters)

    def test_dashboard_source_id(self):
        item = {**self._ITEM, "lever": "Review dashboard:01f16688bc5719bdb992b55e5e6798f0 dataset SQL",
                "sizing": {"kind": "perf_metric", "value": None}}
        assert nb.scan_source(item, [_drv_ev()], "c389980b7b55cfb6")["source_id"] == "01f16688bc5719bdb992b55e5e6798f0"

    @pytest.mark.parametrize("col", ["non_capacity_duration_h", "exec_duration_h"])
    def test_top_by_execution_reads_either_column(self, col):
        cols = ["warehouse_id", "source_type", "source_id", "client_application", "avg_read_gb_per_query", col]
        rows = [["w", "job", "1", "x", 1.0, 5.0], ["w", "job", "2", "y", 2.0, 9.0]]
        item = {"id": "OPP-WH-SCAN", "sizing": {"kind": "perf_metric", "formula": "top source by execution time"}}
        src = nb.scan_source(item, [{"rows": [dict(zip(cols, r, strict=True)) for r in rows]}], "w")
        assert src == {"source_type": "job", "source_id": "2", "client_application": "y"}

    def test_unidentified_source_warns(self):
        item = {**self._ITEM, "sizing": {"kind": "perf_metric", "value": None, "formula": "reads are high"}}
        cell, _ = self._filters(item, _drv_ev())
        assert "WARNING: no cited source row was identified" in cell


@pytest.mark.unit
class TestClosedWindows:
    def test_resize_after_window_is_bounded(self):
        params = {"ws": _WS, "warehouse_id": "ca580fec2da67daf", "change_time": "2026-09-30 15:18:38.766"}
        tpl = nb._verify.skill_file(*nb.NOTEBOOK_TEMPLATE_REL).read_text(encoding="utf-8")
        text = nb.render_notebook({**_RESIZE, "evidence": []}, target=None, workspace_id=_WS, template_text=tpl,
                                  evidence=[_ev("vt-warehouse-change-rate", params)])
        cell, sqls, _ = _run_post_change(text, ["period", "billed_hours", "dbus", "dbus_per_billed_hour"])
        assert "current_date()" not in cell
        assert "DATE_ADD(DATE'2026-08-31', 1)" in sqls[0]  # baseline ends the day before change_date
        assert "DATE_ADD(DATE'2026-09-08', 1)" in sqls[1]  # after = 7 full days from the day after
        assert "TIMESTAMP'2026-09-02 00:00:00'" in sqls[1]

    def test_measure_sql_closes_open_end(self):
        tpl = nb._verify.VerifyTemplate("vt-x", "x", "SELECT 1 FROM system.a.b WHERE workspace_id = '{ws}' "
                                                     "AND d >= DATE'{start}' AND d < current_date()")
        sql = nb._measure_sql(tpl, {"ws": _WS}, None, None)
        assert sql and "current_date()" not in sql and "DATE_ADD(DATE'{end}', 1)" in sql


@pytest.mark.unit
class TestCustomEvidence:
    def _run(self, tmp_path: Path, sql: str) -> dict:
        vdir = tmp_path / "analysis" / "verify"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "cron-readiness.json").write_text(json.dumps({"ok": True, "data": {"columns": ["a"], "rows": [{"a": 1}]}}))
        (vdir / "cron-readiness.sql").write_text(sql)
        item = {"id": "OPP-X", "evidence": ["analysis/verify/cron-readiness.json"]}
        return nb.collect_evidence(item, tmp_path, _public(), ws=_WS)[0]

    def test_public_read_only_workspace_filtered_is_embedded(self, tmp_path):
        e = self._run(tmp_path, f"SELECT job_id FROM system.lakeflow.job_run_timeline WHERE workspace_id = '{_WS}'")
        assert e["sql"] and e["reason"] is None and e["rows"] == [{"a": 1}]

    @pytest.mark.parametrize(
        "sql, why",
        [
            (f"SELECT 1 FROM main.other_schema.job_run_timeline WHERE workspace_id = '{_WS}'", "outside system.*"),
            ("SELECT job_id FROM system.lakeflow.job_run_timeline", "no workspace_id"),
            (f"DELETE FROM system.lakeflow.jobs WHERE workspace_id = '{_WS}'", "not a single read-only"),
        ],
    )
    def test_not_embedded_with_reason(self, tmp_path, sql, why):
        e = self._run(tmp_path, sql)
        assert e["sql"] is None and why in e["reason"]
        cells = nb._evidence_cells([e], _WS, False, "n/a")
        assert why in _flat(cells[0])

    def test_template_gained_derived_placeholder(self):
        tpl = nb._verify.VerifyTemplate("vt-t", "t", "SELECT 1 FROM system.a.b WHERE workspace_id = '{ws}' "
                                                     "AND x >= DATE'{start}' AND x <= DATE'{end}' AND s = '{split_date}'")
        filled = nb._with_derived({"ws": _WS, "start": "2026-09-07", "end": "2026-09-13"}, tpl)
        assert filled["split_date"] == "2026-09-07"


@pytest.mark.unit
class TestBacklogRegistration:
    def test_render_writes_notebook_paths(self, run_dir):
        res = nb.cmd_render(_args(run_dir, render_all=True))
        backlog = json.loads((run_dir / "analysis" / "backlog.json").read_text())
        job = next(i for i in backlog["items"] if i["id"] == "OPP-JOB-FAILURE")
        assert job["notebook"] == "deliverables/notebooks/opp-job-failure-42.py"
        assert (run_dir / job["notebook"]).is_file()
        assert [u["id"] for u in res["backlog_updated"]] == ["OPP-JOB-FAILURE"]
        again = nb.cmd_render(_args(run_dir, render_all=True))
        assert again["backlog_updated"] == []

    def test_no_update_backlog(self, run_dir):
        before = (run_dir / "analysis" / "backlog.json").read_text()
        res = nb.cmd_render(_args(run_dir, render_all=True, no_update_backlog=True))
        assert res["backlog_updated"] is None
        assert (run_dir / "analysis" / "backlog.json").read_text() == before


_TASK_OLD = ["job_id", "task_key", "task_runs", "non_success_runs", "p50_mins", "p95_mins", "task_hours"]
_TASK_NEW = [*_TASK_OLD, "task_runs_before", "p95_mins_before", "task_runs_after", "p95_mins_after"]


@pytest.mark.unit
class TestWaitTaskMeasurement:
    _ITEM = {"id": "OPP-JOB-WAIT-TASK", "target": "job:348089368173138", "tier": "investigate",
             "title": "Agentic Leaderboard Processing: replace readiness polling",
             "sizing": {"kind": "pilot", "value": None}, "lever": "Replace the readiness polling task"}

    def _ev(self, cols):
        rows = [["348089368173138", "ingest", 300, 0, 3.0, 9.0, 20.0],
                ["348089368173138", "wait_for_agentic_processing_readiness", 400, 12, 15.0, 50.8, 120.0]]
        params = {"ws": _WS, "job_ids": "'348089368173138'", "start": "2026-09-02", "end": "2026-10-01"}
        e = {"file": "analysis/verify/vt-task-durations.json", "vt_id": "vt-task-durations", "template": None,
             "params": params, "sql": None, "columns": cols}
        e["rows"] = [dict(zip(cols, r + [0] * (len(cols) - len(r)), strict=True)) for r in rows]
        return e

    @pytest.mark.parametrize("cols", [_TASK_OLD, _TASK_NEW])
    def test_successful_cron_parents_and_wait_task(self, cols):
        ev = self._ev(cols)
        assert nb.wait_task_key(self._ITEM, [ev], "348089368173138") == "wait_for_agentic_processing_readiness"
        tpl = nb._verify.skill_file(*nb.NOTEBOOK_TEMPLATE_REL).read_text(encoding="utf-8")
        text = nb.render_notebook(self._ITEM, target=None, workspace_id=_WS, template_text=tpl, evidence=[ev],
                                  templates=_public())
        cell, sqls, log = _run_post_change(text, ["job_id", "successful_cron_runs", "dbus_per_run"])
        assert len(sqls) == 2
        for sql in sqls:
            assert "task_key = 'wait_for_agentic_processing_readiness'" in sql
            assert "trigger_type = 'CRON' AND result_state IN ('SUCCEEDED', 'SUCCESS')" in sql
            assert "task_end > task_start" in sql and f"workspace_id = '{_WS}'" in sql
            assert "{" not in sql and "current_date()" not in sql
        assert "DATE'2026-08-25'" in sqls[0] and "DATE_ADD(DATE'2026-09-08', 1)" in sqls[1]
        aliases = [a[2] for e in log if e[0] == "agg" for a in e[1]]
        assert aliases[:3] == ["dbus_per_run", "avg_run_mins", "p95_wait_mins"]

    def test_named_task_in_text_wins_and_unresolved_falls_back(self):
        ev = self._ev(_TASK_OLD)
        item = {**self._ITEM, "lever": "replace ingest polling"}
        assert nb.wait_task_key(item, [ev], "348089368173138") == "ingest"
        ev["rows"].append({"job_id": "348089368173138", "task_key": "wait_for_other"})
        item = {**self._ITEM, "lever": "replace the polling"}
        assert nb.wait_task_key(item, [ev], "348089368173138") is None
        tpl = nb._verify.skill_file(*nb.NOTEBOOK_TEMPLATE_REL).read_text(encoding="utf-8")
        text = nb.render_notebook(item, target=None, workspace_id=_WS, template_text=tpl, evidence=[ev],
                                  templates=_public())
        assert "verify query vt-job-runs" in text


# --------------------------------------------------------------------------- #
# Round 8: default commands need one unambiguous `setting: value` (gpt-6 #1)
# --------------------------------------------------------------------------- #

#: The gpt-6 round-8 OPP-JOB-TIMEOUT lever, verbatim — it rendered `timeout_seconds: 12600`.
_GPT6_TIMEOUT_LEVER = (
    "Owner verifies the effective 27000-second timeout scope and adds a RUN_DURATION_SECONDS health alert "
    "just above the measured CRON p95 (proposed 12600 seconds / 210 minutes), in bundle source; tune "
    "timeout only after readiness diagnosis and owner approval."
)


@pytest.mark.unit
class TestDefaultCommandAmbiguity:
    _TIMEOUT = {"id": "OPP-JOB-TIMEOUT", "target": "job:348089368173138", "tier": "investigate", "title": "t",
                "sizing": {"kind": "perf_metric", "metric": "max_run_mins", "value": 3308.3, "unit": "min"}}

    @pytest.mark.parametrize("dep", [None, _BUNDLE_DEP])
    def test_gpt6_health_alert_lever_is_a_decision_note(self, dep):
        item = {**self._TIMEOUT, "lever": _GPT6_TIMEOUT_LEVER}
        cmd = nb.default_lever_command(item, "348089368173138", deployment=dep)
        assert cmd and cmd["kind"] == "decision"
        assert "run_duration_seconds" in cmd["lines"][0]
        cell = _remediation(_render(item, deployment=dep))
        assert "timeout_seconds: 12600" not in cell and "\"timeout_seconds\": 12600" not in cell
        assert "databricks jobs update" not in cell and "Operator decision first" in cell

    @pytest.mark.parametrize(
        "lever, why",
        [
            ("Retain timeout_seconds: 27000 pending diagnosis", "hold or pending"),
            ("timeout_seconds: 12600 after a health alert at 10800 s", "health alert"),
            ("timeout_seconds: 12600; p95 is 11000 s", "other second values (11000)"),
            ("timeout_seconds: 12600 or timeout_seconds: 14400", "2 timeout_seconds values"),
            ("set the timeout just above p95 (12600 s)", "no `timeout_seconds: N`"),
            ("timeout_seconds: 12600 and max_concurrent_runs: 1", "max_concurrent_runs"),
            ("timeout_seconds 12600 -> 12600", "equals the current value"),
        ],
    )
    def test_ambiguous_timeout_levers(self, lever, why):
        cmd = nb.default_lever_command({**self._TIMEOUT, "lever": lever}, "348")
        assert cmd and cmd["kind"] == "decision" and why in cmd["lines"][0]

    @pytest.mark.parametrize(
        "lever, seconds",
        [
            ("timeout_seconds: 12600", 12600),
            ("timeout_seconds 27000 → 12600", 12600),
            ("timeout_seconds 27,000 -> 12,600 (210 min, above the 185.8 min p95)", 12600),
        ],
    )
    def test_explicit_timeout_renders(self, lever, seconds):
        cmd = nb.default_lever_command({**self._TIMEOUT, "lever": lever}, "348")
        assert cmd and cmd["kind"] == "cli" and f'"timeout_seconds": {seconds}' in cmd["text"]

    @pytest.mark.parametrize(
        "lever",
        [
            "pilot performance_target: STANDARD; keep PERFORMANCE_OPTIMIZED on the SLA job",
            "performance_target: STANDARD after the timeout_seconds change",
            "pilot standard mode pending owner SLA confirmation",
        ],
    )
    def test_ambiguous_standard_mode(self, lever):
        cmd = nb.default_lever_command({"id": "OPP-SERVERLESS-STANDARD-MODE", "lever": lever}, "348")
        assert cmd and cmd["kind"] == "decision"

    def test_standard_mode_without_field_keeps_prose(self):
        assert nb.default_lever_command({"id": "OPP-SERVERLESS-STANDARD-MODE", "lever": "pilot standard mode"},
                                        "348") is None

    def test_gpt6_standard_mode_lever_still_renders(self):
        lever = ("After owner confirms SLA tolerance, performance_target: STANDARD in the job bundle source. Run "
                 "this pilot before or after any readiness, timeout or overlap change, never simultaneously; "
                 "rollback PERFORMANCE_OPTIMIZED in bundle source and redeploy.")
        cmd = nb.default_lever_command({"id": "OPP-SERVERLESS-STANDARD-MODE", "lever": lever}, "348")
        assert cmd and cmd["kind"] == "bundle_yaml" and "performance_target: STANDARD" in cmd["text"]

    @pytest.mark.parametrize(
        "lever, why",
        [
            ("max_concurrent_runs: 1 with queue disabled, timeout_seconds: 12600", "timeout_seconds"),
            ("max_concurrent_runs: 1 or max_concurrent_runs: 2", "2 max_concurrent_runs values"),
            ("cap concurrent runs with queue disabled", "no `max_concurrent_runs: N`"),
            ("keep max_concurrent_runs: 1", "hold or pending"),
        ],
    )
    def test_ambiguous_overlap_act_now(self, lever, why):
        cmd = nb.default_lever_command({**_JOB_ITEM, "lever": lever}, "421876946880414")
        assert cmd and cmd["kind"] == "decision" and why in cmd["lines"][0]

    @pytest.mark.parametrize(
        "opp, lever, why",
        [
            ("OPP-WH-RESIZE", "cluster_size LARGE -> MEDIUM and max_num_clusters 2 -> 1", "max_num_clusters"),
            ("OPP-WH-RESIZE", "cluster_size LARGE -> MEDIUM, alert on p95 latency", "health alert"),
            ("OPP-WH-QUEUE", "max_num_clusters 1 -> 2, pending owner sign-off", "hold or pending"),
            ("OPP-WH-QUEUE", "max_num_clusters 1 -> 2 or max_num_clusters 1 -> 3", "more than one"),
        ],
    )
    def test_ambiguous_warehouse(self, opp, lever, why):
        cmd = nb.default_lever_command({"id": opp, "tier": "act_now", "lever": lever}, "w1")
        assert cmd and cmd["kind"] == "decision" and why in cmd["lines"][0]


@pytest.mark.unit
class TestRenderEnvelope:
    def test_rendered_count_paths_and_registration(self, run_dir):
        res = nb.cmd_render(_args(run_dir, render_all=True))
        assert res["rendered"] == res["count"] == len(res["paths"]) > 0
        assert res["paths"] == [n["path"] for n in res["notebooks"]]
        assert all(Path(p).is_file() for p in res["paths"])
        reg = res["backlog_registration"]
        assert reg["enabled"] and reg["written"] and reg["registered"] == len(res["backlog_updated"]) > 0
        assert reg["registered"] + reg["already_registered"] == res["count"]
        again = nb.cmd_render(_args(run_dir, render_all=True))["backlog_registration"]
        assert again == {"enabled": True, "written": False, "registered": 0, "already_registered": res["count"]}

    def test_no_update_backlog(self, run_dir):
        reg = nb.cmd_render(_args(run_dir, render_all=True, no_update_backlog=True))["backlog_registration"]
        assert reg == {"enabled": False, "written": False, "registered": 0, "already_registered": 0}
