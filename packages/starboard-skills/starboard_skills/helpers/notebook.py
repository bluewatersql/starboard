"""Notebook domain helper — render a remediation notebook from a backlog item.

``notebook render`` replaces hand-built notebooks (dropped ``# MAGIC %md``
markers, unfilled ``{{X}}``): it reads ``analysis/backlog.json``, picks the item
(``--item <OPP-ID>[:<target>]`` or ``--all`` act_now/investigate items), and
renders the engagement ``templates/notebook.py`` structure in Databricks source
format — ``# Databricks notebook source`` header, ``# COMMAND ----------``
separators, ``# MAGIC %md`` markdown cells — filled from the item (id, title,
target, sizing, verify evidence, lever). The variant follows ``sizing.kind``:
``bounded_dbu`` reproduces the DBU figure; ``perf_metric`` / ``pilot`` / ``none``
reproduce the metric and add the post-change measurement.

The evidence cell embeds the PUBLIC ``system.*`` SQL: for a ``verify run``
result it re-fills the public verify template with the recorded params (so an
internal-source run still yields customer-runnable SQL); a ``.sql`` that only
names ``system.*`` tables is embedded as-is; anything else is left out with a
clear stop. When a verify result is shared by several targets (e.g. a
``job_id IN (...)`` list of five jobs), the embedded SQL is narrowed to the
item's own target id. The ``Expected:`` note quotes the sizing value only when
the verify result returns the ``sizing.metric`` column.

Backlog item fields read (beyond ``id``/``tier``/``sizing``/``evidence``):

* ``title`` — notebook heading; ``finding`` / ``summary`` (else ``title``) — the
  ``**Finding:**`` line; ``lever`` — the action-plan lever prose.
* ``target`` (``"<kind>:<id>"``, e.g. ``"job:421876946880414"``) or
  ``target_id`` / ``job_id`` / ``warehouse_id`` / ``pipeline_id`` — the target.
* ``lever_command`` (optional) — the concrete remediation, rendered verbatim
  (commented out) in the DESTRUCTIVE cell::

      "lever_command": {"kind": "cli" | "sql" | "json" | "bundle_yaml", "text": "<command / statement / payload>"}

  Without it, common catalog ids get a default command filled from the target
  (``OPP-JOB-OVERLAP``, ``OPP-WH-QUEUE``, ``OPP-WH-RESIZE``,
  ``OPP-SERVERLESS-STANDARD-MODE``, ``OPP-JOB-TIMEOUT``) with a capture + rollback
  line; otherwise the cell carries the lever prose only. ``OPP-JOB-OVERLAP`` gets
  no default command while the item is not ``act_now`` or its preconditions are
  stated unmet (an operator decision note instead).
* Bundle-managed jobs: for ANY job lever, when ``vt-job-settings-history`` shows
  ``deployment_kind = BUNDLE`` or the lever says the change goes in the bundle, the
  command is a ``bundle_yaml`` fragment + "redeploy the bundle" with the rollback in
  the bundle source — never ``jobs update`` (a backlog ``jobs update`` / JSON
  ``lever_command`` is translated to the YAML fragment).
* Warehouse direction (``OPP-WH-RESIZE`` / ``OPP-WH-QUEUE``): the current value comes
  from ``vt-warehouse-config-history`` (latest row), else the X of the lever's
  ``X → Y``. Apply sets the proposed value, Rollback restores the current one; a
  lever that restates the recorded change is a return to X only when it says so
  ("return to X", "consider X"), and a proposed value equal to the current one or
  against the lever's stated direction gets a decision note instead of a command.

The post-change cell (non-``bounded_dbu`` items) runs the id's measurement query
twice — a baseline window (the 7 full days before ``change_date``) and an after
window (the 7 full days from the day after it), each with an explicit start AND
end (an open ``< current_date()`` bound is closed at the window end) — scoped to the
item's target, and summarises the catalog canonical metric per window. OPP-WH-SCAN
is scoped to the exact cited source (``source_type`` / ``source_id`` /
``client_application`` of the cited ``vt-warehouse-drivers`` row); OPP-JOB-WAIT-TASK
measures successful CRON parent runs and the wait task's successful, non-zero
attempts when the evidence names the wait task.

Cited evidence that is not a template instance is embedded when it names only
``system.*`` tables, is read-only and filters ``workspace_id``; otherwise it is
listed (in the notebook and ``evidence_not_embedded_reasons``) with the reason.
``notebook render`` writes each rendered path into its backlog item's ``notebook``
field (atomic write; ``--no-update-backlog`` to skip) and reports ``rendered`` (count), ``paths``,
``backlog_updated`` and ``backlog_registration`` (``registered`` / ``already_registered``).

Default commands are synthesized only when the lever states exactly one unambiguous
``setting: value`` for the id's canonical field (``timeout_seconds``, ``performance_target``,
``max_concurrent_runs``, ``cluster_size X → Y``, ``max_num_clusters X → Y``). A lever that names
another setting or other second values, describes a health alert, or says keep / retain /
pending gets an operator decision note — no write preview.
Verify results are read in either ``--rows`` shape (objects or arrays).
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starboard_skills.helpers import query as _query
from starboard_skills.helpers import verify as _verify
from starboard_skills.helpers.contract import (
    ApiError,
    ArgError,
    HelperError,
    NotFoundError,
)

NOTEBOOK_TEMPLATE_REL = ("templates", "notebook.py")
_HEADER = "# Databricks notebook source"
_SEP = "# COMMAND ----------"
_MAGIC = "# MAGIC"
_RENDER_TIERS = ("act_now", "investigate")
_UNFILLED = re.compile(r"\{\{[A-Z0-9_]+\}\}")
_TABLE_REF = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w`]*(?:\.[A-Za-z_][\w`]*){2})", re.IGNORECASE)
#: Window placeholders recomputed per window from ``change_date`` in the post-change cell.
_WINDOW_KEYS = (
    "start", "end", "window_days", "lookback_days", "split_date", "qh_start", "qh_end", "change_time",
)
#: Placeholders of templates that are themselves a before/after split — not usable per window.
_SPLIT_KEYS = ("step_date", "before_start", "before_end", "after_end")
_WINDOW_DAYS = 7
#: Per catalog id: the measurement template, an optional row filter, and the per-window
#: summary (canonical metric first) as ``(column, Spark SQL aggregate)`` pairs.
_MEASURES: dict[str, tuple[str, str | None, tuple[tuple[str, str], ...]]] = {
    "OPP-WH-QUEUE": ("vt-warehouse-queue", None, (
        ("peak_daily_queued_pct", "max(queued_pct)"),
        ("queries", "sum(queries)"),
        ("peak_p95_capacity_wait_s", "max(p95_capacity_wait_s)"),
    )),
    "OPP-WH-SCAN": ("vt-warehouse-drivers", None, (
        ("avg_read_gb_per_query", "round(sum(avg_read_gb_per_query * queries) / sum(queries), 2)"),
        ("queries", "sum(queries)"),
    )),
    "OPP-WH-RESIZE": ("vt-warehouse-change-rate", None, (
        ("dbus_per_billed_hour", "max(dbus_per_billed_hour)"),
        ("billed_hours", "sum(billed_hours)"),
        ("dbus", "sum(dbus)"),
    )),
    "OPP-JOB-OVERLAP": ("vt-job-overlap", "trigger_type = 'CRON'", (
        ("pct_runs_started_while_running", "round(100 * sum(runs_started_while_running) / sum(runs), 1)"),
        ("cron_runs", "sum(runs)"),
        ("max_concurrent_any", "max(max_concurrent_any)"),
        ("avg_run_mins", "round(sum(avg_run_mins * runs) / sum(runs), 1)"),
    )),
    "OPP-JOB-TIMEOUT": ("vt-job-run-tail", "trigger_type = 'CRON'", (
        ("max_run_mins", "max(run_mins)"),
        ("p95_run_mins", "max(p95_run_mins)"),
    )),
    "OPP-DLT-CADENCE": ("vt-pipeline-updates", None, (
        ("dbus_per_day", f"round(sum(pipeline_dbus) / {_WINDOW_DAYS}, 1)"),
        ("updates_per_day", f"round(sum(updates) / {_WINDOW_DAYS}, 1)"),
        ("avg_update_mins", "max(avg_update_mins)"),
    )),
    "OPP-STEP-CHANGE": ("vt-daily-totals", None, (
        ("avg_daily_dbus", "round(sum(dbus) / count(distinct usage_date), 1)"),
        ("days_billed", "count(distinct usage_date)"),
    )),
}
_JOB_RUN_MEASURE: tuple[str, str | None, tuple[tuple[str, str], ...]] = (
    "vt-job-runs", "trigger_type = 'CRON'", (
        ("dbus_per_run", "round(try_divide(sum(dbus), sum(runs - runs_without_billing)), 1)"),
        ("avg_run_mins", "round(sum(avg_run_mins * runs) / sum(runs), 1)"),
        ("cron_runs", "sum(runs)"),
        ("p95_run_mins", "max(p95_run_mins)"),
    ),
)
_MEASURES["OPP-SERVERLESS-STANDARD-MODE"] = _JOB_RUN_MEASURE
_MEASURES["OPP-JOB-WAIT-TASK"] = _JOB_RUN_MEASURE
#: Target kind → the result column the post-change cell filters on.
_TARGET_COLUMNS = {"job": "job_id", "warehouse": "warehouse_id", "pipeline": "pipeline_id", "dashboard": "source_id"}
#: Target kind → the template placeholders that carry the target id.
_TARGET_PARAMS = {
    "job": ("job_id", "job_ids"),
    "warehouse": ("warehouse_id", "warehouse_ids"),
    "pipeline": ("pipeline_id", "pipeline_ids"),
}
_KIND_PREFIX = re.compile(r"^(?P<kind>[a-z_]+):(?P<id>.+)$")
_TARGET_TYPES = (
    ("OPP-JOB", "jobs"),
    ("OPP-WH", "SQL warehouses"),
    ("OPP-DLT", "pipelines"),
    ("OPP-SERVERLESS", "jobs"),
    ("OPP-CLUSTER", "clusters"),
    ("OPP-LAKEBASE", "Lakebase instances"),
)


# --------------------------------------------------------------------------- #
# Backlog item selection
# --------------------------------------------------------------------------- #


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def _items(backlog: Any) -> list[dict[str, Any]]:
    items = backlog.get("items") if isinstance(backlog, dict) else backlog
    if not isinstance(items, list):
        raise ArgError("backlog has no 'items' list")
    return [i for i in items if isinstance(i, dict) and i.get("id")]


def _first_id(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value not in (None, "") else None


def item_target(item: dict[str, Any]) -> str | None:
    """The item's target id: explicit fields, ``target`` ``<kind>:<id>``, else the notebook-link suffix."""
    for key in ("target_id", "job_id", "warehouse_id", "pipeline_id"):
        found = _first_id(item.get(key))
        if found:
            return found
    target = item.get("target")
    if isinstance(target, str) and ":" in target:
        found = target.partition(":")[2].strip()
        if found:
            return found
    link = item.get("notebook")
    if isinstance(link, str) and link:
        stem, prefix = Path(link).stem, slugify(item["id"]) + "-"
        if stem.startswith(prefix) and len(stem) > len(prefix):
            return stem[len(prefix):]
    return None


def strip_kind(target: str | None) -> str | None:
    """``job:123`` → ``123`` (an ``--item`` target may carry the backlog's ``<kind>:`` prefix)."""
    if not target:
        return target
    m = _KIND_PREFIX.match(target.strip())
    return m.group("id").strip() if m else target.strip()


def item_target_kind(item: dict[str, Any]) -> str | None:
    """``job`` / ``warehouse`` / ``pipeline`` / ``dashboard`` … from ``target``, the id fields, or the opp id."""
    target = item.get("target")
    if isinstance(target, str):
        m = _KIND_PREFIX.match(target.strip())
        if m:
            return m.group("kind")
    for key, kind in (("job_id", "job"), ("warehouse_id", "warehouse"), ("pipeline_id", "pipeline")):
        if _first_id(item.get(key)):
            return kind
    opp = str(item.get("id") or "")
    for prefix, kind in (("OPP-JOB", "job"), ("OPP-SERVERLESS", "job"), ("OPP-WH", "warehouse"), ("OPP-DLT", "pipeline")):
        if opp.startswith(prefix):
            return kind
    return None


def _haystack(item: dict[str, Any]) -> str:
    parts = [item.get(k) for k in ("notebook", "title", "lever", "target", "job_id", "warehouse_id", "pipeline_id")]
    return " ".join(json.dumps(p) if isinstance(p, list) else str(p) for p in parts if p).lower()


def select_items(items: list[dict[str, Any]], specs: list[str] | None, render_all: bool) -> list[tuple[dict[str, Any], str | None]]:
    """Resolve ``--item ID[:target]`` specs (or ``--all``) to ``(item, target)`` pairs."""
    if render_all:
        chosen = [i for i in items if i.get("tier") in _RENDER_TIERS]
        if not chosen:
            raise NotFoundError("backlog has no act_now / investigate items to render")
        return [(i, None) for i in chosen]
    if not specs:
        raise ArgError("pass --item <OPP-ID>[:<target>] (repeatable) or --all")
    out: list[tuple[dict[str, Any], str | None]] = []
    for spec in specs:
        opp_id, _, raw_target = spec.partition(":")
        target = strip_kind(raw_target.strip()) or None
        matches = [i for i in items if i["id"] == opp_id.strip()]
        if target:
            matches = [i for i in matches if target.lower() in _haystack(i)]
        if not matches:
            raise NotFoundError(f"no backlog item matches --item {spec}")
        if len(matches) > 1:
            options = ", ".join(f"{opp_id}:{item_target(i) or '?'}" for i in matches)
            raise ArgError(f"--item {spec} is ambiguous ({len(matches)} items); use one of: {options}")
        out.append((matches[0], target))
    return out


def notebook_filename(item: dict[str, Any], target: str | None) -> str:
    """The backlog's own ``notebook`` link when present (``run check`` requires that path),
    else ``<opp-id-lower>-<target id without kind prefix>.py`` — the same name for
    ``--all`` and ``--item ID[:target]``."""
    link = item.get("notebook")
    if isinstance(link, str) and link.endswith(".py"):
        return Path(link).name
    target = strip_kind(target) or item_target(item)
    slug = slugify(item["id"]) + (f"-{slugify(target)}" if target else "")
    return f"{slug}.py"


# --------------------------------------------------------------------------- #
# Evidence (verify results → public SQL)
# --------------------------------------------------------------------------- #


def _is_public_sql(sql: str) -> bool:
    refs = [r.replace("`", "") for r in _TABLE_REF.findall(sql)]
    return bool(refs) and all(r.lower().startswith("system.") for r in refs)


_RECOVERED_VALUE = re.compile(r"^[^;\n]{1,2000}$")


def _inverse(template: Any) -> re.Pattern[str]:
    """Regex that matches ``template`` filled with any values (whitespace-tolerant)."""
    seen: set[str] = set()
    parts: list[str] = []
    for chunk in re.split(r"(\{\w+\})", template.sql):
        name = re.fullmatch(r"\{(\w+)\}", chunk)
        if name:
            key = name.group(1)
            parts.append(f"(?P={key})" if key in seen else f"(?P<{key}>.*?)")
            seen.add(key)
        else:
            parts.append(r"\s+".join(re.escape(tok) for tok in chunk.split()) if chunk.strip() else "")
            if chunk[:1].isspace():
                parts.insert(len(parts) - 1, r"\s*")
            if chunk[-1:].isspace():
                parts.append(r"\s*")
    return re.compile(r"\s*" + "".join(parts) + r"\s*;?\s*\Z", re.DOTALL)


def recover_params(sql: str, file_stem: str, source_templates: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
    """Recover ``(vt_id, params)`` from a hand-run ``<vt-id>[-suffix].sql``.

    The vt-id is the longest template id prefixing the file name; the params come
    from matching the SQL against that template. ``(None, {})`` when it does not match.
    """
    ids = [v for v in source_templates if file_stem == v or file_stem.startswith(v + "-")]
    if not ids:
        return None, {}
    vt_id = max(ids, key=len)
    match = _inverse(source_templates[vt_id]).match(sql)
    if not match:
        return vt_id, {}
    params = {k: v.strip() for k, v in match.groupdict().items()}
    if not all(_RECOVERED_VALUE.match(v) for v in params.values()):
        return vt_id, {}
    return vt_id, params


def _custom_sql_problem(sql: str, ws: str | None) -> str | None:
    """Why a hand-written (non-template) verify ``.sql`` can't be embedded, else ``None``:
    it must name only ``system.*`` tables, be one read-only statement, and filter ``workspace_id``."""
    if not _is_public_sql(sql):
        return ("custom SQL (not a verify-template instance) reads tables outside system.* — it cannot be "
                "re-run from a customer notebook; translate it to system.* tables and re-render")
    try:
        _query._assert_read_only(sql)
    except HelperError as exc:
        return f"custom SQL is not a single read-only statement ({exc.message})"
    if ws:
        try:
            _verify.assert_workspace_filter(sql, ws)
        except HelperError:
            return f"custom SQL has no workspace_id = '{ws}' filter"
    return None


def _with_derived(params: dict[str, str], tpl: Any) -> dict[str, str]:
    """Fill derived placeholders the template has gained since the evidence ran (e.g. a
    ``{split_date}`` added to vt-task-durations) from the recorded ``ws``/``start``/``end``,
    exactly as ``verify run`` would (``split_date`` = ``start``: no split)."""
    missing = [p for p in tpl.placeholders if p not in params and p in _verify.DERIVED_PLACEHOLDERS]
    if not missing or not all(params.get(k) for k in ("ws", "start", "end")):
        return params
    try:
        derived = _verify.derive_params(ws=params["ws"], start=params["start"], end=params["end"])
    except HelperError:
        return params
    return {**params, **{p: derived[p] for p in missing if p in derived}}


def collect_evidence(
    item: dict[str, Any],
    run_dir: Path,
    public_templates: dict[str, Any],
    source_templates: dict[str, Any] | None = None,
    ws: str | None = None,
) -> list[dict[str, Any]]:
    """For each cited ``analysis/verify/*.json``, the public SQL that reproduces it.

    Params come from the ``verify run`` metadata in the ``.json``; for a hand-run
    pair they are recovered from the ``.sql`` against ``source_templates`` (the
    templates it was filled from, default the public ones). A ``.sql`` that is not a
    template instance is embedded as-is when it names only ``system.*`` tables, is
    read-only and filters ``workspace_id = ws``; otherwise ``reason`` says why not.
    Each entry carries the result ``rows`` (as dicts, either ``--rows`` shape).
    """
    out: list[dict[str, Any]] = []
    for ref in item.get("evidence") or []:
        if not isinstance(ref, str) or not ref.endswith(".json") or "verify" not in ref:
            continue
        path = run_dir / ref
        entry: dict[str, Any] = {
            "file": ref, "vt_id": None, "sql": None, "template": None, "params": {}, "rows": [], "reason": None,
        }
        meta: dict[str, Any] = {}
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
            data = payload.get("data") if isinstance(payload, dict) else None
            meta = (data or {}).get("verify") or {} if isinstance(data, dict) else {}
            columns = data.get("columns") if isinstance(data, dict) else None
            if isinstance(columns, list):
                entry["columns"] = [str(c) for c in columns]
            if isinstance(data, dict):
                entry["rows"] = _rows_as_dicts(data)
                if not columns and entry["rows"]:
                    entry["columns"] = [str(c) for c in entry["rows"][0]]
        vt_id = meta.get("vt_id")
        raw_params = meta.get("params")
        params: dict[str, str] = raw_params if isinstance(raw_params, dict) else {}
        sql_path = path.with_suffix(".sql")
        raw_sql = sql_path.read_text(encoding="utf-8").strip() if sql_path.is_file() else None
        if not params and raw_sql:
            vt_id, params = recover_params(raw_sql, sql_path.stem, source_templates or public_templates)
            entry["recovered"] = bool(params)
        tpl = public_templates.get(vt_id) if vt_id else None
        if tpl is not None and params:
            params = _with_derived(params, tpl)
        if tpl is not None and all(p in params for p in tpl.placeholders):
            entry.update(vt_id=vt_id, params=params, template=tpl, sql=_verify.fill(tpl, params))
        elif raw_sql:
            problem = _custom_sql_problem(raw_sql, ws or params.get("ws"))
            gaps = [p for p in tpl.placeholders if p not in params] if tpl is not None and params else []
            if problem is None:
                entry.update(vt_id=vt_id, sql=raw_sql)
            elif gaps:
                entry["reason"] = (
                    f"the current public {vt_id} template needs {', '.join(gaps)}, which the recorded run "
                    "did not set; re-run it with `starboard-helper verify run`"
                )
            elif vt_id:
                entry["reason"] = (
                    f"{vt_id} params could not be recovered from {sql_path.name} (pass --source-templates "
                    f"with the templates it was filled from); and as {problem}"
                )
            else:
                entry["reason"] = problem
        elif not path.is_file():
            entry["reason"] = "the cited .json does not exist"
        else:
            entry["reason"] = (
                f"no {sql_path.name} beside it and no `verify run` metadata — re-run it with "
                "`starboard-helper verify run`"
            )
        out.append(entry)
    return out


#: ``[alias.]job_id|warehouse_id|pipeline_id IN ('a', 'b', ...)`` — a shared target list.
_ID_LIST = re.compile(
    r"(?P<col>\b(?:[A-Za-z_]\w*\.)*(?:job_id|warehouse_id|pipeline_id))(?P<op>\s+IN\s*)"
    r"\((?P<ids>\s*'[^']*'(?:\s*,\s*'[^']*')*\s*)\)",
    re.IGNORECASE,
)


def scope_sql_to_target(sql: str, target: str | None) -> str:
    """Narrow every ``job_id/warehouse_id/pipeline_id IN (...)`` list that contains
    ``target`` (and other ids) to ``IN ('<target>')``; lists without it are left as-is."""
    if not target:
        return sql

    def _sub(m: re.Match[str]) -> str:
        ids = re.findall(r"'([^']*)'", m.group("ids"))
        if len(ids) > 1 and target in ids:
            return f"{m.group('col')}{m.group('op')}('{target}')"
        return m.group(0)

    return _ID_LIST.sub(_sub, sql)


# --------------------------------------------------------------------------- #
# Remediation commands
# --------------------------------------------------------------------------- #

_ARROW = r"\s*(?:->|→|=>)\s*"  # the docs write levers with a Unicode arrow; accept ASCII too
_WH_SIZES = re.compile(r"cluster[_ ]size\s+([\w-]+)" + _ARROW + r"([\w-]+)", re.IGNORECASE)
_WH_CLUSTERS = re.compile(r"max_num_clusters\s+(\d+)" + _ARROW + r"(\d+)", re.IGNORECASE)
_SECONDS = re.compile(r"(\d[\d,]*)\s*(?:s|sec|seconds)\b")
_MAX_RUNS = re.compile(r"max_concurrent_runs\s*[:=]?\s*(\d+)", re.IGNORECASE)
#: Lever words that turn a restated ``X → Y`` (Y = the recorded current value) into a return to X.
_REVERT_WORDS = r"(?:return|revert|back|roll(?:\s|-)?back|downsiz|upsiz|consider|restor|size\s+back)"
_SIZE_DOWN = re.compile(r"\b(?:downsiz\w*|size\s+down|scale\s+down)\b", re.IGNORECASE)
_SIZE_UP = re.compile(r"\b(?:upsiz\w*|size\s+up|scale\s+up)\b", re.IGNORECASE)
_SIZE_ORDER = ("2X_SMALL", "X_SMALL", "SMALL", "MEDIUM", "LARGE", "X_LARGE", "2X_LARGE", "3X_LARGE", "4X_LARGE")
#: Lever text that says the job is bundle-managed (when no settings-history evidence says so).
_BUNDLE_TEXT = re.compile(r"\b(?:bundles?|DAB|asset\s+bundle)\b", re.IGNORECASE)
_CLI_JSON = re.compile(r"databricks\s+jobs\s+(?:update|reset)\b.*?--json\s+'(?P<json>.*)'", re.DOTALL)
_CLI_WH_VALUE = re.compile(r"--(?P<flag>cluster-size|max-num-clusters)\s+(?P<value>[\w-]+)")
#: ``timeout_seconds: N`` / ``timeout_seconds N → M`` — the only lever form a default timeout command reads.
_TIMEOUT_SET = re.compile(
    r"\btimeout_seconds\b\s*(?:[:=]|to)?\s*(\d[\d,]*)(?:" + _ARROW + r"(\d[\d,]*))?", re.IGNORECASE,
)
#: ``performance_target: STANDARD`` / ``performance_target PERFORMANCE_OPTIMIZED → STANDARD``.
_PERF_TARGET = re.compile(
    r"\bperformance_target\b\s*[:=]?\s*(STANDARD|PERFORMANCE_OPTIMIZED)\b(?:" + _ARROW
    + r"(STANDARD|PERFORMANCE_OPTIMIZED)\b)?",
    re.IGNORECASE,
)
#: Job / warehouse setting names; a default command only writes its own canonical field, so a lever
#: naming any other one is ambiguous (e.g. a RUN_DURATION_SECONDS health alert in a timeout lever).
_SETTING_NAMES = re.compile(
    r"\b(timeout_seconds|max_concurrent_runs|performance_target|cluster_size|max_num_clusters|min_num_clusters"
    r"|auto_stop_mins|run_duration_seconds|streaming_backlog_\w+)\b",
    re.IGNORECASE,
)
_HEALTH_ALERT = re.compile(r"\b(?:health|alerts?)\b", re.IGNORECASE)
#: Lever words that say "do not change it (yet)".
_HOLD = re.compile(
    r"\b(?:retain\w*|keep\w*|pending|unchanged|leave\s+(?:it|the\s+\w+)\s+(?:as|at|unchanged)"
    r"|no\s+change|do\s+not\s+change|don'?t\s+change)\b",
    re.IGNORECASE,
)


def _cli_size(raw: str) -> str:
    """``2X_LARGE`` / ``MEDIUM`` → the CLI/API spelling ``2X-Large`` / ``Medium``."""
    parts = raw.strip().upper().replace("_", "-").split("-")
    return "-".join(p if p.endswith("X") else p.capitalize() for p in parts)


def _norm_size(raw: Any) -> str:
    """``2X-Large`` / ``Medium`` / ``2X_LARGE`` → the system-table spelling ``2X_LARGE`` / ``MEDIUM``."""
    return str(raw).strip().upper().replace("-", "_")


def _job_update(job_id: str, settings: dict[str, Any]) -> str:
    return f"databricks jobs update {job_id} --json '{json.dumps({'new_settings': settings})}'"


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    text = str(value)
    plain = re.fullmatch(r"[A-Za-z_][\w./-]*", text) and text.lower() not in (
        "true", "false", "null", "yes", "no", "on", "off",
    )
    return text if plain else json.dumps(text)


def _yaml(obj: Any, indent: int = 0) -> list[str]:
    """A minimal block-YAML rendering of a JSON settings fragment (dicts, lists, scalars)."""
    pad = "  " * indent
    out: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)) and value:
                out += [f"{pad}{key}:", *_yaml(value, indent + 1)]
            else:
                out.append(f"{pad}{key}: {_yaml_scalar(value)}")
    elif isinstance(obj, list):
        for value in obj:
            if isinstance(value, (dict, list)) and value:
                sub = _yaml(value, indent + 1)
                out += [f"{pad}- {sub[0].strip()}", *sub[1:]]
            else:
                out.append(f"{pad}- {_yaml_scalar(value)}")
    return out


def is_bundle_job(item: dict[str, Any], deployment: dict[str, Any] | None) -> bool:
    """A job lever is bundle-managed when ``vt-job-settings-history`` says ``deployment_kind = BUNDLE``
    or the lever text says the change goes in the bundle."""
    if deployment and deployment.get("kind") == "BUNDLE":
        return True
    return bool(_BUNDLE_TEXT.search(str(item.get("lever") or "")))


def _bundle_where(deployment: dict[str, Any] | None) -> str:
    if deployment and deployment.get("kind") == "BUNDLE":
        return f"bundle-deployed per {deployment['source']}"
    return "bundle-managed per the lever"


def _bundle_lines(target: str, settings: dict[str, Any], deployment: dict[str, Any] | None) -> list[str]:
    lines = [f"In the bundle source for job {target} ({_bundle_where(deployment)}), on the job resource:"]
    if deployment and deployment.get("metadata_file_path"):
        lines.append(f"(deployment metadata: {deployment['metadata_file_path']})")
    lines += ["  " + ln for ln in _yaml(settings)]
    lines.append(
        "then redeploy the bundle (`databricks bundle deploy` from that bundle) — a `jobs update` "
        "would be overwritten by the next deploy."
    )
    return lines


def _bundle_command(
    target: str, settings: dict[str, Any], deployment: dict[str, Any] | None, rollback: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "bundle_yaml", "capture": f"databricks jobs get {target} > job-{target}-before.json",
        "text": "\n".join(_bundle_lines(target, settings, deployment)),
        "rollback": rollback or (
            f"revert the change in the bundle source and redeploy the bundle; the previous values are in "
            f"job-{target}-before.json (captured above)"
        ),
    }


def _bundle_from_given(
    cmd: dict[str, Any], target: str, deployment: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """A backlog ``jobs update`` / JSON ``lever_command`` for a bundle-managed job as the bundle
    YAML fragment (``None`` when it is already bundle YAML or carries no job settings)."""
    kind, text = str(cmd.get("kind") or "cli").lower(), str(cmd.get("text") or "")
    raw: str | None = None
    if kind == "json":
        raw = text
    elif kind == "cli":
        m = _CLI_JSON.search(text)
        raw = m.group("json") if m else None
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return {"kind": "decision", "lines": [
            f"Operator decision first — no command rendered: job {target} is bundle-managed "
            f"({_bundle_where(deployment)}), so the backlog lever_command would be overwritten by the "
            "next bundle deploy, and its JSON could not be read to translate it.",
            "Put the change in the bundle source (a lever_command of kind bundle_yaml) and re-render.",
        ]}
    settings = payload.get("new_settings", payload) if isinstance(payload, dict) else None
    if not isinstance(settings, dict) or not settings:
        return None
    out = _bundle_command(target, settings, deployment, rollback=cmd.get("rollback"))
    out["translated"] = True
    return out


#: Precondition text that says it is not met yet (OPP-JOB-OVERLAP cadence / backfill gates).
_UNMET = re.compile(
    r"\b(?:unmet|not\s+(?:yet\s+)?(?:met|confirmed|finished|done)|unconfirmed|pending|awaiting|until\s+the\s+owner)\b",
    re.IGNORECASE,
)


def lever_ambiguity(lever: str, canonical: set[str]) -> str | None:
    """Why ``lever`` is not one unambiguous ``setting: value`` for the ``canonical`` field(s), else ``None``.

    Ambiguous: another setting is named, a health alert is described, or the lever says to
    keep / retain / leave the value or that the change is pending (diagnosis, owner, ...)."""
    others = sorted({m.lower() for m in _SETTING_NAMES.findall(lever)} - canonical)
    if others:
        return f"the lever names another setting ({', '.join(others)}) besides {', '.join(sorted(canonical))}"
    if _HEALTH_ALERT.search(lever):
        return "the lever describes a health alert, not a value for " + ", ".join(sorted(canonical))
    hold = _HOLD.search(lever)
    if hold:
        return f"the lever says “{hold.group(0)}” — a hold or pending decision, not a change to make"
    return None


def _ambiguous_note(problem: str, field: str) -> dict[str, Any]:
    return {"kind": "decision", "lines": [
        f"Operator decision first — no command rendered: {problem}.",
        f"State exactly one `{field}: <value>` in the lever (or add a lever_command) once the owner "
        "has decided, then re-render.",
    ]}


def _timeout_command(
    item: dict[str, Any], target: str, deployment: dict[str, Any] | None, job_get: str,
) -> dict[str, Any] | None:
    """OPP-JOB-TIMEOUT: only an explicit ``timeout_seconds: N`` (or ``N → M``) in an otherwise
    unambiguous lever renders a command; a lever with other numbers / settings / a health alert /
    "retain" gets a decision note; a lever with no seconds at all keeps the prose."""
    lever = str(item.get("lever") or "")
    found = _TIMEOUT_SET.findall(lever)
    proposed = {int((m[1] or m[0]).replace(",", "")) for m in found}
    mentioned = {int(m.replace(",", "")) for m in _SECONDS.findall(lever)}
    mentioned |= {int(m.replace(",", "")) for m in re.findall(r"(\d[\d,]*)-second", lever)}
    if not found and not mentioned and not lever_ambiguity(lever, {"timeout_seconds"}):
        return None
    current = {int(m[0].replace(",", "")) for m in found if m[1]}
    problem = lever_ambiguity(lever, {"timeout_seconds"})
    if not problem and not found:
        problem = "the lever names seconds but no `timeout_seconds: N` to set"
    if not problem and len(proposed) != 1:
        problem = f"the lever names {len(proposed)} timeout_seconds values ({', '.join(map(str, sorted(proposed)))})"
    stray = mentioned - proposed - current
    if not problem and stray:
        problem = f"the lever also names other second values ({', '.join(map(str, sorted(stray)))})"
    if not problem and proposed & current:
        problem = "the proposed timeout_seconds equals the current value"
    if problem:
        return _ambiguous_note(problem, "timeout_seconds")
    seconds = next(iter(proposed))
    if is_bundle_job(item, deployment):
        cmd = _bundle_command(target, {"timeout_seconds": seconds}, deployment)
        cmd["text"] += "\n(job-level timeout_seconds; task-level timeout_seconds are set per task)"
        return cmd
    return {
        "kind": "cli", "capture": job_get,
        "text": _job_update(target, {"timeout_seconds": seconds})
        + "   # job-level; task-level timeout_seconds are set per task",
        "rollback": _restore_line(target),
    }


def _standard_mode_command(
    item: dict[str, Any], target: str, deployment: dict[str, Any] | None, job_get: str,
) -> dict[str, Any] | None:
    """OPP-SERVERLESS-STANDARD-MODE: only an explicit ``performance_target: STANDARD`` in an
    otherwise unambiguous lever renders a command."""
    lever = str(item.get("lever") or "")
    found = _PERF_TARGET.findall(lever)
    problem = lever_ambiguity(lever, {"performance_target"})
    if not found:
        return _ambiguous_note(problem, "performance_target") if problem else None
    proposed = {(m[1] or m[0]).upper() for m in found}
    if not problem and proposed != {"STANDARD"}:
        problem = f"the lever sets performance_target to {', '.join(sorted(proposed))}, not only STANDARD"
    if problem:
        return _ambiguous_note(problem, "performance_target")
    if is_bundle_job(item, deployment):
        return _bundle_command(
            target, {"performance_target": "STANDARD"}, deployment,
            rollback="set performance_target: PERFORMANCE_OPTIMIZED on the job resource in the bundle source "
                     "and redeploy the bundle",
        )
    return {
        "kind": "cli", "capture": job_get,
        "text": _job_update(target, {"performance_target": "STANDARD"}),
        "rollback": _job_update(target, {"performance_target": "PERFORMANCE_OPTIMIZED"}),
    }


def _restore_line(target: str) -> str:
    return f"restore from job-{target}-before.json (captured above)"


def _rows_as_dicts(data: dict[str, Any]) -> list[dict[str, Any]]:
    """``data.rows`` as dicts — ``--rows arrays`` (with ``data.columns``) or ``--rows objects``."""
    rows, columns = data.get("rows") or [], data.get("columns") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
        elif isinstance(row, list) and columns:
            out.append({str(c): v for c, v in zip(columns, row, strict=False)})
    return out


def job_deployment(item: dict[str, Any], run_dir: Path, target: str | None) -> dict[str, Any] | None:
    """The target job's latest ``deployment_kind`` (+ metadata file) from a
    ``vt-job-settings-history`` result in the run dir (cited evidence first), else ``None``."""
    if not target:
        return None
    cited = [run_dir / r for r in item.get("evidence") or [] if isinstance(r, str) and r.endswith(".json")]
    for path, rows in _verify_rows(run_dir, cited, "vt-job-settings-history"):
        rows = [r for r in rows if str(r.get("job_id")) == target and "deployment_kind" in r]
        if not rows:
            continue
        latest = max(rows, key=lambda r: str(r.get("change_time") or ""))
        if not latest.get("deployment_kind"):
            continue
        return {
            "kind": str(latest["deployment_kind"]).upper(),
            "metadata_file_path": latest.get("deployment_metadata_file_path"),
            "source": _rel(path, run_dir),
        }
    return None


def _rel(path: Path, run_dir: Path) -> str:
    return str(path.relative_to(run_dir) if path.is_relative_to(run_dir) else path)


def _verify_rows(run_dir: Path, cited: list[Path], vt_id: str) -> list[tuple[Path, list[dict[str, Any]]]]:
    """``(path, rows as dicts)`` of the cited ``.json`` files, then every ``analysis/verify/<vt_id>*.json``."""
    candidates = [*cited, *sorted((run_dir / "analysis" / "verify").glob(f"{vt_id}*.json"))]
    out: list[tuple[Path, list[dict[str, Any]]]] = []
    for path in dict.fromkeys(candidates):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            out.append((path, _rows_as_dicts(data)))
    return out


def warehouse_current(item: dict[str, Any], run_dir: Path, target: str | None) -> dict[str, Any] | None:
    """The target warehouse's current ``warehouse_size`` / ``max_clusters`` (latest ``change_time``
    row) from a ``vt-warehouse-config-history`` result in the run dir, else ``None``."""
    if not target:
        return None
    cited = [run_dir / r for r in item.get("evidence") or [] if isinstance(r, str) and r.endswith(".json")]
    for path, rows in _verify_rows(run_dir, cited, "vt-warehouse-config-history"):
        rows = [r for r in rows if str(r.get("warehouse_id")) == target and "warehouse_size" in r]
        if not rows:
            continue
        latest = max(rows, key=lambda r: str(r.get("change_time") or ""))
        return {
            "warehouse_size": _norm_size(latest["warehouse_size"]) if latest.get("warehouse_size") else None,
            "max_clusters": str(latest["max_clusters"]) if latest.get("max_clusters") is not None else None,
            "change_time": latest.get("change_time"),
            "source": _rel(path, run_dir),
        }
    return None


def _resolve_change(
    lever: str, match: re.Match[str], current: str | None, norm: Any,
) -> tuple[str, str | None, str | None]:
    """``(current, proposed, problem)`` for a lever ``X → Y``.

    ``current`` (recorded evidence) wins over the lever text: X = current means "set Y"; Y =
    current means the lever restates the recorded change, a return to X only when the lever
    says so (``return to X`` / ``consider X`` / ``revert``); anything else is a contradiction."""
    x, y = norm(match.group(1)), norm(match.group(2))
    if current is None or current == x:
        cur, prop = x, y
    elif current == y:
        rest = lever[match.end():]
        if not re.search(rf"\b{_REVERT_WORDS}\w*[^.;]{{0,40}}?(?<![\w-]){re.escape(x)}(?![\w-])", rest, re.IGNORECASE):
            return y, None, (
                f"the lever restates the recorded change {x} → {y} (current {y}) and does not name the value to set"
            )
        cur, prop = y, x
    else:
        return current, None, f"the lever's {x} → {y} does not start from the recorded current value {current}"
    if prop == cur:
        return cur, None, f"the proposed value {prop} equals the current value"
    return cur, prop, None


def _size_direction_problem(lever: str, cur: str, prop: str) -> str | None:
    if cur not in _SIZE_ORDER or prop not in _SIZE_ORDER:
        return None
    bigger = _SIZE_ORDER.index(prop) > _SIZE_ORDER.index(cur)
    if bigger and _SIZE_DOWN.search(lever) and not _SIZE_UP.search(lever):
        return f"the lever says downsize, but {cur} → {prop} is an upsize"
    if not bigger and _SIZE_UP.search(lever) and not _SIZE_DOWN.search(lever):
        return f"the lever says upsize, but {cur} → {prop} is a downsize"
    return None


def _warehouse_command(
    item: dict[str, Any], target: str, warehouse: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """OPP-WH-RESIZE / OPP-WH-QUEUE: Apply sets the proposed value, Rollback restores the current one."""
    opp, lever = str(item.get("id") or ""), str(item.get("lever") or "")
    norm: Callable[[Any], str]
    show: Callable[[str], str]
    if opp == "OPP-WH-RESIZE":
        field, flag, rx, label = "warehouse_size", "--cluster-size", _WH_SIZES, "cluster_size"
        norm, show = _norm_size, _cli_size
    else:
        field, flag, rx, label = "max_clusters", "--max-num-clusters", _WH_CLUSTERS, "max_num_clusters"
        norm, show = str, str
    found = rx.search(lever)
    if not found:
        return None
    recorded = (warehouse or {}).get(field)
    cur, prop, problem = _resolve_change(lever, found, recorded, norm)
    if prop and opp == "OPP-WH-RESIZE":
        problem = _size_direction_problem(lever, cur, prop)
    if prop and not problem:
        canonical = {"cluster_size"} if opp == "OPP-WH-RESIZE" else {"max_num_clusters"}
        problem = lever_ambiguity(lever, canonical)
        if not problem and len(rx.findall(lever)) > 1:
            problem = f"the lever states more than one {label} change"
    basis = (
        f"current {label} {cur} per {warehouse['source']}" if recorded and warehouse
        else f"current {label} {cur} per the lever text (no vt-warehouse-config-history row for {target})"
    )
    if problem or prop is None:
        return {"kind": "decision", "lines": [
            f"Operator decision first — no command rendered: {problem}.",
            f"Recorded: {basis}.",
            f"Restate the lever with the current value first and the value to set second (`{label} {cur} → …`), "
            "or add a lever_command, then re-render.",
        ]}
    cmd: dict[str, Any] = {
        "kind": "cli", "capture": f"databricks warehouses get {target} > warehouse-{target}-before.json",
        "text": f"databricks warehouses edit {target} {flag} {show(prop)}",
        "rollback": f"databricks warehouses edit {target} {flag} {show(cur)}",
        "note": [f"{basis}; Apply sets the proposed {prop}, Rollback restores {cur}."],
    }
    tier = str(item.get("tier") or "n/a")
    if tier != "act_now":
        cmd["note"].insert(0, (
            f"Operator decision first (tier {tier}): measure first and confirm owner intent (see the lever) "
            "before running the commands below."
        ))
    return cmd


def _check_given_warehouse(
    cmd: dict[str, Any], target: str, warehouse: dict[str, Any] | None,
) -> dict[str, Any]:
    """A backlog ``warehouses edit`` lever_command that sets the recorded current value is a no-op:
    a decision note instead; otherwise a missing rollback restores the recorded current value."""
    m = _CLI_WH_VALUE.search(str(cmd.get("text") or ""))
    if not m or not warehouse:
        return cmd
    field = "warehouse_size" if m.group("flag") == "cluster-size" else "max_clusters"
    current = warehouse.get(field)
    if not current:
        return cmd
    value = _norm_size(m.group("value")) if field == "warehouse_size" else m.group("value")
    if value == current:
        return {"kind": "decision", "lines": [
            f"Operator decision first — no command rendered: the backlog lever_command sets --{m.group('flag')} "
            f"{m.group('value')}, which is already the current value per {warehouse['source']}.",
            "Correct the lever_command (Apply sets the proposed value) and re-render.",
        ]}
    if not cmd.get("rollback"):
        shown = _cli_size(current) if field == "warehouse_size" else current
        cmd = {**cmd, "rollback": f"databricks warehouses edit {target} --{m.group('flag')} {shown}"}
    return cmd


def _overlap_command(item: dict[str, Any], target: str, deployment: dict[str, Any] | None) -> dict[str, Any]:
    """OPP-JOB-OVERLAP without ``lever_command``: decision note, bundle fragment, or ``jobs update``."""
    lever = str(item.get("lever") or "")
    values = {int(v) for v in _MAX_RUNS.findall(lever)}
    max_runs = next(iter(values)) if len(values) == 1 else 1
    gates = " ".join(str(item.get(k) or "") for k in ("lever", "precondition", "preconditions"))
    bundle = is_bundle_job(item, deployment)
    where = (
        f"the bundle source that deploys job {target} ({_bundle_where(deployment)})"
        if bundle else f"job {target}"
    )
    settings = {"max_concurrent_runs": max_runs, "queue": {"enabled": False}}
    bundle_lines = _bundle_lines(target, settings, deployment)
    tier = str(item.get("tier") or "n/a")
    ambiguous = (
        lever_ambiguity(lever, {"max_concurrent_runs"})
        or ("the lever states no `max_concurrent_runs: N`" if not values else None)
        or (f"the lever names {len(values)} max_concurrent_runs values" if len(values) > 1 else None)
    )
    if tier != "act_now" or _UNMET.search(gates) or ambiguous:
        why = (
            f"tier {tier}" if tier != "act_now"
            else "a stated precondition is not met" if _UNMET.search(gates) else str(ambiguous)
        )
        lines = [
            f"Operator decision first — no command rendered ({why}).",
            f"Before any change to {where}, the job owner confirms:",
            "  1. Cadence: while a run is longer than the schedule interval, a cap of "
            f"max_concurrent_runs: {max_runs} makes the effective cadence the run length — the owner accepts it.",
            "  2. Backfill: concurrent ONETIME / run-now runs are finished or moved to their own job "
            "(the cap applies to every trigger).",
            "Once both are confirmed, add a lever_command to the backlog item and re-render this notebook.",
        ]
        if bundle:
            lines += ["", "The change, once confirmed (bundle YAML, not `jobs update`):", *bundle_lines]
        return {"kind": "decision", "lines": lines}
    if bundle:
        return _bundle_command(target, settings, deployment)
    return {
        "kind": "cli", "capture": f"databricks jobs get {target} > job-{target}-before.json",
        "text": _job_update(target, settings),
        "rollback": _restore_line(target),
    }


def default_lever_command(
    item: dict[str, Any], target: str | None, deployment: dict[str, Any] | None = None,
    warehouse: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Per-catalog-id default command for ``target`` (``None`` when there is none).

    Returns ``{"kind", "text", "capture", "rollback"}`` (or ``{"kind": "decision",
    "lines"}`` for an operator decision note). Values the lever does not state are
    never rendered as ``<...>`` placeholders: OPP-JOB-TIMEOUT needs the seconds and
    warehouse commands need ``before -> after`` in the lever (else lever prose only).
    A bundle-managed job (``deployment`` from :func:`job_deployment` says BUNDLE, or the
    lever says the change goes in the bundle) gets a ``bundle_yaml`` fragment + redeploy
    instead of ``jobs update``. ``warehouse`` (see :func:`warehouse_current`) is the
    recorded current size / max clusters: Apply sets the proposed value, Rollback restores
    the current one, and a lever that contradicts it gets a decision note.
    """
    opp = str(item.get("id") or "")
    if not target or not re.fullmatch(r"[\w.:-]+", target):
        return None
    job_get = f"databricks jobs get {target} > job-{target}-before.json"
    if opp == "OPP-JOB-OVERLAP":
        return _overlap_command(item, target, deployment)
    if opp == "OPP-SERVERLESS-STANDARD-MODE":
        return _standard_mode_command(item, target, deployment, job_get)
    if opp == "OPP-JOB-TIMEOUT":
        return _timeout_command(item, target, deployment, job_get)
    if opp in ("OPP-WH-QUEUE", "OPP-WH-RESIZE"):
        return _warehouse_command(item, target, warehouse)
    return None


def _command_lines(cmd: dict[str, Any]) -> list[str]:
    kind, text = str(cmd.get("kind") or "cli").lower(), str(cmd.get("text") or "").rstrip()
    bundle_intro = "# Bundle YAML — change the bundle source (not the deployed job), then redeploy the bundle:"
    intro = {
        "cli": "# Databricks CLI — run in a terminal authenticated to this workspace "
               "(pass --profile with your CLI profile name if it is not the default):",
        "sql": "# SQL — run in the SQL editor or uncomment the spark.sql(...) lines below:",
        "json": "# JSON settings payload — apply with the Databricks CLI (--json), the REST API, or the UI:",
        "bundle_yaml": bundle_intro,
        "yaml": bundle_intro,
    }.get(kind, f"# {kind}:")
    body = text.splitlines() or [""]
    if kind == "sql":
        body = ['spark.sql("""', *body, '""")']
    return [intro, *[f"# {ln}".rstrip() for ln in body]]


# --------------------------------------------------------------------------- #
# Cell rendering
# --------------------------------------------------------------------------- #


def _split_cells(template: str) -> list[str]:
    return [c.strip("\n") for c in template.split(_SEP)]


def _find_cell(cells: list[str], marker: str) -> str | None:
    return next((c for c in cells if marker in c), None)


def _md(lines: list[str]) -> str:
    body = [f"{_MAGIC} %md"] + [f"{_MAGIC} {ln}".rstrip() if ln else _MAGIC for ln in lines]
    return "\n".join(body)


def _comment(text: str, width: int = 96, indent: str = "#   ") -> list[str]:
    return textwrap.wrap(str(text), width=width, initial_indent=indent, subsequent_indent=indent) or [indent.rstrip()]


def _fmt_value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}"
    return str(value) if value not in (None, "") else "n/a"


def _title_cell(template_cell: str, values: dict[str, str], bounded: bool, lever: str | None) -> str:
    """Fill the template's title cell; drop example quotes and the off-variant lines."""
    out: list[str] = []
    skip_bounded = not bounded
    for line in template_cell.splitlines():
        body = line[len(_MAGIC):].lstrip() if line.startswith(_MAGIC) else None
        if body is None:
            continue
        if body.startswith(">"):
            continue  # template examples
        if body.startswith("<!--"):
            continue  # variant instruction comment
        if skip_bounded and ("{{RECOVERABLE_DBU" in body):
            continue
        if lever and lever != values.get("FINDING_SUMMARY") and body.startswith("**Evidence citation:**"):
            out += [f"{_MAGIC} **Lever:** {lever}", _MAGIC]
        out.append(f"{_MAGIC} {body}".rstrip() if body else _MAGIC)
    filled = "\n".join(out)
    for key, value in values.items():
        filled = filled.replace("{{" + key + "}}", value)
    filled = re.sub(rf"(?:{re.escape(_MAGIC)}\n)+", f"{_MAGIC}\n", filled)  # collapse blank runs
    filled = filled.replace(f"{_MAGIC} %md\n{_MAGIC}\n", f"{_MAGIC} %md\n")
    return re.sub(rf"(?:\n{re.escape(_MAGIC)})+\Z", "", filled.rstrip("\n"))


def _sql_literal(sql: str) -> str:
    return sql.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def _expected_line(e: dict[str, Any], metric: str | None, sizing: str) -> str:
    """Quote the sizing value only against a column the query actually returns."""
    if metric and metric in (e.get("columns") or []) and sizing and sizing != "n/a":
        return f"# Expected: the `{metric}` column matches {sizing} from the evidence pack within rounding."
    return "# Expected: the result reproduces the rows behind the cited sizing in the evidence pack."


def _evidence_cells(
    ev: list[dict[str, Any]], ws: str, bounded: bool, sizing: str,
    metric: str | None = None, target: str | None = None,
) -> list[str]:
    what = "DBU figure" if bounded else "metric"
    cells: list[str] = []
    skipped = [
        line
        for x in ev if not x["sql"]
        for line in _comment(f"{x['file']} — {x.get('reason') or 'its public system.* SQL could not be rebuilt'}",
                             indent="#   ")
    ]
    for i, e in enumerate([x for x in ev if x["sql"]]):
        name = "evidence" if i == 0 else f"evidence_{i + 1}"
        src = f"verify query {e['vt_id']}" if e["vt_id"] else "the cited verify query"
        sql = scope_sql_to_target(e["sql"], target)
        scoped = (
            [f"# Scoped to target {target} (the verify run covered several ids)."] if sql != e["sql"] else []
        )
        lines = [
            "# READ-ONLY — this cell does not modify anything.",
            f"# Reproduces the cited {what} with {src} (evidence: {e['file']}).",
            *scoped,
            "# Run this first to confirm the number before acting on anything.",
            "",
            f'workspace_id = "{ws}"  # scope: this notebook covers exactly this workspace',
            "",
            f'{name}_sql = """',
            _sql_literal(sql),
            '"""',
            "",
            f"{name} = spark.sql({name}_sql)",
            f"{name}.display()",
            "",
            *(
                [
                    _expected_line(e, metric, sizing),
                    "# If it differs materially, stop — do not proceed to the remediation cell — and re-verify the finding.",
                ]
                if i == 0
                else ["# Supporting evidence: compare with the figures cited in the evidence pack."]
            ),
        ]
        if i == 0 and skipped:
            lines += ["#", "# Cited evidence NOT embedded (compare it by hand before acting):", *skipped]
        cells.append("\n".join(lines))
    if not cells:
        files = ", ".join(e["file"] for e in ev) or "none cited"
        cells.append("\n".join([
            "# READ-ONLY — evidence query not embedded.",
            f"# Cited verify evidence: {files}.",
            "# Its public system.* SQL could not be reconstructed (not produced by",
            "# `starboard-helper verify run`). Re-run verify for this item, then re-render.",
            *(["# Why:", *skipped] if skipped else []),
            "",
            'raise NotImplementedError("Evidence query not embedded: re-render after `starboard-helper verify run`.")',
        ]))
    return cells


def _targets_cells(targets: list[tuple[str, str, str]], target_type: str) -> list[str]:
    md = _md([
        "## Targets enumerated",
        "",
        f"The following **{target_type}** were identified as contributing to the finding.",
        "",
        "Confirm this list matches the evidence query output above before proceeding.",
    ])
    rows = [f"    ({t!r}, {n!r}, {d!r})," for t, n, d in targets] or [
        "    # (target id, target name, why it is listed),  — one tuple per target from the query output",
    ]
    code = "\n".join([
        "# Enumerate specific targets — review and confirm before proceeding to the remediation cell.",
        "# Do not act on an id without verifying it is still live.",
        "",
        "targets = [",
        *rows,
        "]",
        "",
        "if not targets:",
        '    raise ValueError("No targets populated — fill in the targets list from the query output above.")',
        "",
        'print(f"Targets listed for verification ({len(targets)}) — confirm each is still live before acting:")',
        "for target_id, target_name, description in targets:",
        '    print(f"  id={target_id}  name={target_name}  —  {description}")',
    ])
    return [md, code]


def _remediation_code(
    ws: str, item: dict[str, Any], target: str | None, deployment: dict[str, Any] | None = None,
    warehouse: dict[str, Any] | None = None,
) -> str:
    lever = item.get("lever")
    head = [
        "# DESTRUCTIVE — REVIEW BEFORE UNCOMMENTING",
        f"# These commands modify live resources in workspace {ws}.",
        "# Verify each target above before uncommenting.",
        "#",
        "# Lever (from the action plan):",
        *_comment(lever or "see the evidence pack"),
        "",
    ]
    given = item.get("lever_command")
    cmd: dict[str, Any] | None = (
        given if isinstance(given, dict) and str(given.get("text") or "").strip() else None
    )
    source = "backlog lever_command"
    bundle = item_target_kind(item) == "job" and is_bundle_job(item, deployment)
    if cmd is not None and target and _SAFE_ID.match(target):
        if bundle and str(cmd.get("kind") or "cli").lower() not in ("bundle_yaml", "yaml"):
            translated = _bundle_from_given(cmd, target, deployment)
            if translated is not None:
                cmd = translated
                source = "backlog lever_command, as bundle YAML (the job is bundle-managed)"
        elif item_target_kind(item) == "warehouse":
            cmd = _check_given_warehouse(cmd, target, warehouse)
    if cmd is None:
        cmd = default_lever_command(item, target, deployment, warehouse)
        source = f"default for {item.get('id')} — check every value against the lever above"
    if cmd is not None and cmd.get("kind") == "decision":
        note: list[str] = []
        for ln in cmd["lines"]:
            lead = " " * (len(ln) - len(ln.lstrip()))
            hang = lead + ("   " if re.match(r"\s*\d+\.\s", ln) else "")
            note += textwrap.wrap(ln, width=98, initial_indent="# ", subsequent_indent="# " + hang,
                                  drop_whitespace=True, break_on_hyphens=False) or ["#"]
        return "\n".join([*head, *note])
    if cmd is None:
        return "\n".join([
            *head,
            "# for target_id, target_name, description in targets:",
            '#     print(f"Acting on: {target_id}  ({target_name})")',
            "#     # Apply the lever above to target_id (Databricks CLI, SDK or UI), one target at a time.",
            "#     pass",
        ])
    lines = list(head)
    for note in cmd.get("note") or []:
        lines += textwrap.wrap(str(note), width=98, initial_indent="# ", subsequent_indent="# ") or ["#"]
    lines.append(f"# Command ({source}):")
    if cmd.get("capture"):
        lines += ["# 1) Capture the current settings (needed for rollback):", f"# {cmd['capture']}", "# 2) Apply:"]
    lines += _command_lines(cmd)
    lines += ["#", "# Rollback:"]
    if cmd.get("rollback"):
        lines.append(f"# {cmd['rollback']}")
    elif str(cmd.get("kind") or "").lower() in ("bundle_yaml", "yaml"):
        lines.append("# Revert the change in the bundle source and redeploy the bundle.")
    else:
        lines.append(
            "# Re-apply the settings captured before the change (e.g. `databricks jobs get` / `warehouses get`)."
        )
    return "\n".join(lines)


_TRAILING_LIMIT = re.compile(r"\s+LIMIT\s+\d+\s*;?\s*\Z", re.IGNORECASE)
_SAFE_ID = re.compile(r"^[\w.:-]+$")


def _measure_sql(
    template: Any, params: dict[str, str], target: str | None, kind: str | None,
) -> str | None:
    """``template`` filled with every non-window param and scoped to ``target``; window
    placeholders are left for the notebook to fill per window. ``None`` when a
    non-window placeholder can't be filled or the template is itself a before/after split."""
    if any(p in _SPLIT_KEYS for p in template.placeholders):
        return None
    fixed = {k: v for k, v in params.items() if k not in _WINDOW_KEYS}
    if target and kind in _TARGET_PARAMS and _SAFE_ID.match(target):
        singular, plural = _TARGET_PARAMS[kind]
        if singular in template.placeholders:
            fixed[singular] = target
        if plural in template.placeholders:
            fixed[plural] = f"'{target}'"
    left = [p for p in template.placeholders if p not in fixed]
    if any(p not in _WINDOW_KEYS for p in left):
        return None
    sql = template.sql
    for key, value in fixed.items():
        sql = sql.replace("{" + key + "}", value)
    # Every window is closed: an open ``< current_date()`` bound would silently grow the after
    # window with every day the notebook is re-run later, so it ends at the window's own end.
    sql = _OPEN_END.sub("DATE_ADD(DATE'{end}', 1)", sql)
    return _TRAILING_LIMIT.sub("", scope_sql_to_target(sql, target))


_OPEN_END = re.compile(r"\bcurrent_date\s*\(\s*\)", re.IGNORECASE)
_SUCCESS = "('SUCCEEDED', 'SUCCESS')"
#: Post-change wait-task measurement: successful CRON parent runs only (wall-clock, DBU per run)
#: and the wait task's own successful, non-zero-duration attempts — skipped / excluded / zero-length
#: task rows and ONETIME / run-now parents never dilute the comparison.
_WAIT_TASK_SQL = """\
WITH parents AS (
  SELECT job_id, run_id,
         MIN(period_start_time)                AS run_start,
         MAX(period_end_time)                  AS run_end,
         MAX_BY(result_state, period_end_time) AS result_state,
         MAX_BY(trigger_type, period_end_time) AS trigger_type
  FROM system.lakeflow.job_run_timeline
  WHERE workspace_id = '{ws}'
    AND job_id = '{job_id}'
    AND period_end_time >= DATE_SUB(DATE'{start}', 3)
  GROUP BY job_id, run_id
  HAVING MAX(period_end_time) >= DATE'{start}' AND MAX(period_end_time) < DATE_ADD(DATE'{end}', 1)
),
ok_runs AS (
  SELECT * FROM parents WHERE trigger_type = 'CRON' AND result_state IN %(ok)s
),
wait_attempts AS (
  SELECT job_run_id, run_id,
         MIN(period_start_time)                AS task_start,
         MAX(period_end_time)                  AS task_end,
         MAX_BY(result_state, period_end_time) AS result_state
  FROM system.lakeflow.job_task_run_timeline
  WHERE workspace_id = '{ws}'
    AND job_id = '{job_id}'
    AND task_key = '{task_key}'
    AND period_end_time >= DATE_SUB(DATE'{start}', 3)
  GROUP BY job_run_id, run_id
),
waits AS (  -- one row per parent run: its successful, non-zero wait
  SELECT job_run_id, MAX((unix_timestamp(task_end) - unix_timestamp(task_start)) / 60) AS wait_mins
  FROM wait_attempts
  WHERE result_state IN %(ok)s AND task_end > task_start
  GROUP BY job_run_id
),
run_dbu AS (
  SELECT usage_metadata.job_run_id AS run_id, SUM(usage_quantity) AS dbus
  FROM system.billing.usage
  WHERE workspace_id = '{ws}'
    AND usage_unit = 'DBU'
    AND usage_metadata.job_id = '{job_id}'
    AND usage_metadata.job_run_id IS NOT NULL
    AND usage_date BETWEEN DATE_SUB(DATE'{start}', 3) AND DATE_ADD(DATE'{end}', 1)
  GROUP BY 1
)
SELECT r.job_id,
       '{task_key}'                                                                         AS task_key,
       COUNT(*)                                                                             AS successful_cron_runs,
       ROUND(try_divide(SUM(d.dbus), COUNT(d.dbus)), 1)                                     AS dbus_per_run,
       ROUND(AVG((unix_timestamp(r.run_end) - unix_timestamp(r.run_start)) / 60), 1)        AS avg_run_mins,
       ROUND(percentile((unix_timestamp(r.run_end) - unix_timestamp(r.run_start)) / 60, 0.95), 1) AS p95_run_mins,
       COUNT(w.wait_mins)                                                                   AS wait_task_runs,
       ROUND(AVG(w.wait_mins), 1)                                                           AS avg_wait_mins,
       ROUND(percentile(w.wait_mins, 0.95), 1)                                              AS p95_wait_mins
FROM ok_runs r
LEFT JOIN run_dbu d ON d.run_id = r.run_id
LEFT JOIN waits w   ON w.job_run_id = r.run_id
GROUP BY r.job_id""".replace("%(ok)s", _SUCCESS)
_WAIT_TASK_AGGS: tuple[tuple[str, str], ...] = (
    ("dbus_per_run", "max(dbus_per_run)"),
    ("avg_run_mins", "max(avg_run_mins)"),
    ("p95_wait_mins", "max(p95_wait_mins)"),
    ("avg_wait_mins", "max(avg_wait_mins)"),
    ("successful_cron_runs", "sum(successful_cron_runs)"),
)
_WAIT_WORDS = re.compile(r"wait|poll|readiness|sensor|ready", re.IGNORECASE)
_TASK_KEY = re.compile(r"^[\w.-]+$")


def _item_text(item: dict[str, Any]) -> str:
    raw = item.get("sizing")
    formula = raw.get("formula") if isinstance(raw, dict) else None
    parts = [item.get(k) for k in ("title", "finding", "summary", "lever", "why")] + [formula]
    return " ".join(str(p) for p in parts if p)


def wait_task_key(item: dict[str, Any], ev: list[dict[str, Any]], target: str | None) -> str | None:
    """The wait/poll task of an OPP-JOB-WAIT-TASK item: ``task_key`` on the item, else the
    ``vt-task-durations`` task (old or new column set — only ``job_id``/``task_key`` are read)
    the item text names, else the only wait-like task in that evidence, else ``wait_for_*`` in the text."""
    explicit = item.get("task_key")
    if isinstance(explicit, str) and _TASK_KEY.match(explicit):
        return explicit
    text = _item_text(item)
    keys = list(dict.fromkeys(
        str(r["task_key"]) for e in ev for r in e.get("rows") or []
        if r.get("task_key") and (not target or str(r.get("job_id")) == target)
    ))
    named = sorted((k for k in keys if re.search(rf"(?<![\w-]){re.escape(k)}(?![\w-])", text)), key=len, reverse=True)
    if named:
        return named[0] if _TASK_KEY.match(named[0]) else None
    waits = [k for k in keys if _WAIT_WORDS.search(k)]
    if len(waits) == 1 and _TASK_KEY.match(waits[0]):
        return waits[0]
    if not keys:
        m = re.search(r"\bwait_for_\w+\b", text)
        return m.group(0) if m else None
    return None


def _sql_str(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def scan_source(item: dict[str, Any], ev: list[dict[str, Any]], target: str | None) -> dict[str, Any] | None:
    """The cited OPP-WH-SCAN source (``source_type`` / ``source_id`` / ``client_application``).

    From the item's own ``source`` (dict) / top-level fields, else the ``vt-warehouse-drivers``
    row of the target warehouse that the item text names (``<source_type>:<source_id>``,
    ``<source_type>:<client_application>`` or the bare source id), else the only row whose
    ``avg_read_gb_per_query`` equals ``sizing.value``."""
    keys = ("source_type", "source_id", "client_application")
    given = item.get("source")
    given = given if isinstance(given, dict) else item
    if given.get("source_type") and any(k in given for k in keys[1:]):
        return {k: given.get(k) for k in keys}
    rows = [
        r for e in ev for r in e.get("rows") or []
        if "source_type" in r and (not target or str(r.get("warehouse_id", target)) == target)
    ]
    text = _item_text(item).lower()
    # The driver is the source the item names FIRST ("Top source by execution time: X ...
    # Supporting: Y"); a row matched by its own source id beats one matched by a shared client name.
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for r in rows:
        st, sid, app = (str(r.get(k)) if r.get(k) is not None else None for k in keys)
        cands = [
            (f"{st}:{sid}" if sid else None, 1), (sid if sid and len(sid) >= 8 else None, 1),
            (f"{st}:{app}" if app else None, 0), (app if app and not sid and len(app) >= 6 else None, 0),
        ]
        hits = [(text.find(c.lower()), by_id) for c, by_id in cands if c and c.lower() in text]
        if hits:
            pos = min(p for p, _ in hits)
            scored.append((pos, max(b for p, b in hits if p == pos), r))
    pool = rows
    if scored:
        first = min(p for p, _, _ in scored)
        pool = [r for p, _, r in scored if p == first]
        if len(pool) > 1 and any(b for p, b, _ in scored if p == first):
            pool = [r for p, b, r in scored if p == first and b]
        if len(pool) == 1:
            return {k: pool[0].get(k) for k in keys}
    raw = item.get("sizing")
    value = raw.get("value") if isinstance(raw, dict) else None
    if isinstance(value, (int, float)):
        same = [r for r in pool if isinstance(r.get("avg_read_gb_per_query"), (int, float))
                and abs(float(r["avg_read_gb_per_query"]) - float(value)) < 1e-9]
        if len(same) == 1:
            return {k: same[0].get(k) for k in keys}
    if not scored and re.search(r"\b(?:top|driver|largest)\b.*\b(?:execution|non-capacity)\b", text):
        # "top source by execution": the row with the most non-capacity time (either column name).
        def _exec_h(r: dict[str, Any]) -> float:
            v = r.get("non_capacity_duration_h", r.get("exec_duration_h"))
            return float(v) if isinstance(v, (int, float)) else -1.0

        ranked = sorted(rows, key=_exec_h, reverse=True)
        if ranked and _exec_h(ranked[0]) >= 0 and (len(ranked) == 1 or _exec_h(ranked[0]) > _exec_h(ranked[1])):
            return {k: ranked[0].get(k) for k in keys}
    return None


def _source_filter(src: dict[str, Any]) -> str:
    return " AND ".join(
        f"{k} IS NULL" if src.get(k) is None else f"{k} = {_sql_str(src[k])}"
        for k in ("source_type", "source_id", "client_application")
    )


def _measure_base(
    item: dict[str, Any], ev: list[dict[str, Any]], target: str | None, kind: str | None,
    ws: str, templates: dict[str, Any] | None,
) -> tuple[str, str, Any, tuple[tuple[str, str], ...], str | None] | None:
    """``(vt_id, sql, template, summary aggregates, row filter)`` for the post-change cell.

    The catalog id's measurement template (from the cited evidence, else rebuilt from the
    public templates for the target), else a cited template returning ``sizing.metric``,
    else the first cited template that can run per window (rows only, no summary)."""
    spec = _MEASURES.get(str(item.get("id") or ""))
    raw = item.get("sizing")
    metric = str(raw.get("metric") or "") if isinstance(raw, dict) else ""
    usable = [e for e in ev if e.get("template") is not None]
    picks: list[tuple[Any, dict[str, str], bool]] = []
    if spec:
        picks += [(e["template"], e["params"], True) for e in usable if e["vt_id"] == spec[0]]
        if templates and spec[0] in templates and ws:
            picks.append((templates[spec[0]], {"ws": ws}, True))
    if metric:
        picks += [(e["template"], e["params"], False) for e in usable if metric in (e.get("columns") or [])]
    picks += [(e["template"], e["params"], False) for e in usable]
    for template, params, is_spec in picks:
        sql = _measure_sql(template, params, target, kind)
        if sql is None:
            continue
        if is_spec and spec:
            return template.vt_id, sql, template, spec[2], spec[1]
        return template.vt_id, sql, template, (), None
    return None


def _post_change_code(
    ev: list[dict[str, Any]], target: str | None = None, *, item: dict[str, Any] | None = None,
    ws: str = "", templates: dict[str, Any] | None = None,
) -> str:
    item = item or {}
    kind = item_target_kind(item) if item else None
    opp = str(item.get("id") or "")
    notes: list[str] = []
    task_key = (
        wait_task_key(item, ev, target)
        if opp == "OPP-JOB-WAIT-TASK" and kind == "job" and target and _SAFE_ID.match(target) and ws else None
    )
    base: tuple[str, str, Any, tuple[tuple[str, str], ...], str | None] | None
    if task_key and target:
        wait_sql = _WAIT_TASK_SQL.replace("{ws}", ws).replace("{job_id}", target).replace("{task_key}", task_key)
        tpl = _verify.VerifyTemplate("successful-CRON wait-task measurement", "wait task", wait_sql)
        base = ("the successful-CRON wait-task measurement", wait_sql, tpl, _WAIT_TASK_AGGS, None)
        notes = [
            f"# Successful CRON parent runs of job {target} only; wait task {task_key} counts only its",
            "# successful, non-zero-duration attempts (skipped / excluded / zero-length task rows and",
            "# ONETIME / run-now parents are left out).",
        ]
    else:
        base = _measure_base(item, ev, target, kind, ws, templates)
    if base is None:
        return "\n".join([
            "# READ-ONLY — post-change measurement.",
            "# No verify template for this item can be re-run per window. Re-run the evidence cell above",
            "# twice — once for the 7 full days before change_date, once for the 7 full days starting the",
            "# day after it — and compare the cited metric between the two runs.",
        ])
    vt_id, sql, template, aggs, row_filter = base
    if opp == "OPP-WH-SCAN" and vt_id == "vt-warehouse-drivers":
        src = scan_source(item, ev, target)
        if src:
            row_filter = _source_filter(src)
            notes = ["# Scoped to the cited source (not a warehouse-wide average): "
                     + ", ".join(f"{k}={src.get(k)}" for k in ("source_type", "source_id", "client_application"))
                     + "."]
        else:
            notes = [
                "# WARNING: no cited source row was identified, so this averages every source on the warehouse",
                "# (a change in workload mix moves it). Set row_filter to the cited source_type / source_id /",
                "# client_application before comparing.",
            ]
    column = _TARGET_COLUMNS.get(kind or "") if target else None
    scope = f"{kind} {target}" if target and kind else (f"target {target}" if target else f"workspace {ws}")
    query_name = vt_id if " " in vt_id else f"verify query {vt_id}"
    lines = [
        "# READ-ONLY — post-change measurement: a baseline window and an after window, run separately.",
        f"# Measures {scope} with {query_name} (public system.* tables).",
        *notes,
        f"# baseline = the {_WINDOW_DAYS} full days before change_date; after = the {_WINDOW_DAYS} full days",
        "# starting the day after change_date (the change day is in neither window). Each window is",
        "# its own query, so per-day and per-run figures use that window's own denominators.",
        "import datetime as _dt",
        "",
        "from pyspark.sql import functions as F",
        "",
        'change_date = ""  # YYYY-MM-DD the operator applied the change — enter it before running',
        "if not change_date:",
        '    raise ValueError("Set change_date (YYYY-MM-DD) before running the post-change measurement.")',
        "_c = _dt.date.fromisoformat(change_date)",
        "_day = lambda n: str(_c + _dt.timedelta(days=n))  # noqa: E731",
        f"if _dt.date.today() <= _c + _dt.timedelta(days={_WINDOW_DAYS}):",
        f'    raise ValueError(f"The after window ends {{_day({_WINDOW_DAYS})}}: run this on or after {{_day({_WINDOW_DAYS + 1})}}.")',
        "",
        "windows = {",
        f'    "baseline": {{"start": _day(-{_WINDOW_DAYS}), "end": _day(-1)}},',
        f'    "after": {{"start": _day(1), "end": _day({_WINDOW_DAYS})}},',
        "}",
    ]
    if "change_time" in template.placeholders:
        lines += [
            "# The query splits at change_time itself: the baseline run keeps its rows before change_date,",
            "# the after run keeps its rows from the first full day after the change.",
            'windows["baseline"].update(change_time=f"{change_date} 00:00:00", keep_period="a_before")',
            'windows["after"].update(change_time=f"{_day(1)} 00:00:00", keep_period="b_after")',
        ]
    lines += [
        f"target_column, target_id = {column!r}, {target if column else None!r}",
        f"row_filter = {row_filter!r}",
        "",
        'measure_sql = """',
        _sql_literal(sql),
        '"""',
        "",
        "frames = []",
        "for name, w in windows.items():",
        "    params = {",
        '        "start": w["start"], "end": w["end"], "qh_start": w["start"], "qh_end": w["end"],',
        f'        "window_days": "{_WINDOW_DAYS}", "lookback_days": "{_WINDOW_DAYS}", "split_date": w["start"],',
        '        "change_time": w.get("change_time", ""),',
        "    }",
        "    sql = measure_sql",
        "    for key, value in params.items():",
        '        sql = sql.replace("{" + key + "}", value)',
        "    df = spark.sql(sql)",
        '    if "keep_period" in w:',
        '        df = df.filter(F.col("period") == w["keep_period"])',
        "    if target_column and target_column in df.columns:",
        '        df = df.filter(F.col(target_column).cast("string") == target_id)',
        "    if row_filter:",
        "        df = df.filter(row_filter)",
        "    frames.append(",
        '        df.withColumn("comparison_window", F.lit(name))',
        '        .withColumn("window_start", F.lit(w["start"]))',
        '        .withColumn("window_end", F.lit(w["end"]))',
        "    )",
        "",
        "rows = frames[0].unionByName(frames[1])",
        "rows.display()  # per-window rows",
    ]
    if aggs:
        raw = item.get("sizing")
        sizing: dict[str, Any] = raw if isinstance(raw, dict) else {}
        cited = _fmt_value(sizing.get("value")) if sizing.get("value") is not None else None
        lines += [
            "",
            'summary = rows.groupBy("comparison_window", "window_start", "window_end").agg(',
            *[f"    F.expr({expr!r}).alias({name!r})," for name, expr in aggs],
            ').orderBy("window_start")',
            "summary.display()",
            "",
            f"# Compare `{aggs[0][0]}` (the catalog metric for {item.get('id')}) between the baseline and after rows"
            + (f"; the finding cited {cited} {sizing.get('unit') or ''}".rstrip() + "." if cited else "."),
        ]
    return "\n".join(lines)


def render_notebook(
    item: dict[str, Any],
    *,
    target: str | None,
    workspace_id: str,
    template_text: str,
    evidence: list[dict[str, Any]],
    templates: dict[str, Any] | None = None,
    deployment: dict[str, Any] | None = None,
    warehouse: dict[str, Any] | None = None,
) -> str:
    """Render one item into Databricks notebook source (validated).

    ``templates`` (the public verify templates) lets the post-change cell rebuild the
    id's measurement query when the cited evidence lacks it; ``deployment`` (see
    :func:`job_deployment`) makes job commands bundle YAML for a bundle-deployed job;
    ``warehouse`` (see :func:`warehouse_current`) is the recorded current warehouse
    config the OPP-WH-RESIZE / OPP-WH-QUEUE command direction is checked against."""
    cells = _split_cells(template_text)
    title_tpl = _find_cell(cells, "{{FINDING_TITLE}}")
    if title_tpl is None:
        raise ApiError("notebook template has no {{FINDING_TITLE}} title cell")
    raw_sizing = item.get("sizing")
    sizing: dict[str, Any] = raw_sizing if isinstance(raw_sizing, dict) else {}
    kind = str(sizing.get("kind") or "none")
    bounded = kind == "bounded_dbu"
    lever = item.get("lever")
    tgt = strip_kind(target) or item_target(item)
    value, unit = _fmt_value(sizing.get("value")), str(sizing.get("unit") or "")
    sizing_text = f"{value} {unit}".strip()
    cited = [e["file"] for e in evidence]
    other_refs = [r for r in (item.get("evidence") or []) if isinstance(r, str) and r not in cited]
    values = {
        "FINDING_TITLE": str(item.get("title") or item["id"]),
        "FINDING_SUMMARY": str(
            item.get("finding") or item.get("summary") or item.get("why") or item.get("signal")
            or item.get("title") or lever or item["id"]
        ),
        "SIZING_KIND": kind,
        "SIZING_VALUE": value,
        "SIZING_UNIT": unit,
        "SIZING_FORMULA": str(sizing.get("formula") or "see the evidence pack"),
        "RECOVERABLE_DBU": value,
        "RECOVERABLE_DBU_ARITHMETIC": str(sizing.get("formula") or value),
        "QUERY_ID": ", ".join(cited) or "n/a",
        "ROW_REFERENCE": ", ".join(other_refs) or "n/a",
        "WORKSPACE_ID": workspace_id,
        "BACKLOG_TIER": str(item.get("tier") or "n/a"),
        "CONFIDENCE": str(item.get("confidence") if item.get("confidence") is not None else "n/a"),
        "TARGET_ID": tgt or "",
    }
    target_type = next((t for p, t in _TARGET_TYPES if item["id"].startswith(p)), "resources")
    targets = [(tgt, str(item.get("title") or item["id"]), str(lever or ""))] if tgt else []

    header = f"{_HEADER}\n# Generated by Starboard for {item['id']} — review before running; nothing here writes to your workspace until you uncomment it."
    out: list[str] = [header, _title_cell(title_tpl, values, bounded, lever)]
    metric = str(sizing["metric"]) if sizing.get("metric") else None
    out += _evidence_cells(evidence, workspace_id, bounded, sizing_text, metric, tgt)
    out += _targets_cells(targets, target_type)
    for marker in ("## Remediation",):
        cell = _find_cell(cells, marker)
        if cell:
            out.append(cell)
    out.append(_remediation_code(workspace_id, item, tgt, deployment, warehouse))
    if not bounded:
        cell = _find_cell(cells, "## Post-change measurement")
        if cell:
            out.append(cell)
        out.append(_post_change_code(evidence, tgt, item=item, ws=workspace_id, templates=templates))
    footer = _find_cell(cells, "*Generated by Starboard")
    if footer:
        out.append(footer)
    text = f"\n\n{_SEP}\n\n".join(out) + "\n"
    validate_notebook(text)
    return text


def validate_notebook(text: str) -> None:
    """Databricks source format + no unfilled ``{{X}}`` placeholders."""
    if not text.startswith(_HEADER + "\n"):
        raise ApiError(f"rendered notebook must start with '{_HEADER}'")
    left = sorted(set(_UNFILLED.findall(text)))
    if left:
        raise ApiError(f"rendered notebook has unfilled placeholder(s): {', '.join(left)}")
    for cell in text.split(_SEP)[1:]:
        lines = cell.strip("\n").splitlines()
        if lines and lines[0].startswith(_MAGIC) and lines[0] != f"{_MAGIC} %md":
            raise ApiError("markdown cell must start with '# MAGIC %md'")
        if lines and lines[0] == f"{_MAGIC} %md" and any(not ln.startswith(_MAGIC) for ln in lines):
            raise ApiError("every line of a markdown cell must start with '# MAGIC'")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def register(subparsers) -> None:
    p = subparsers.add_parser("notebook", help="Render remediation notebooks from the backlog")
    sp = p.add_subparsers(dest="command", required=True)
    r = sp.add_parser(
        "render",
        help="Render <opportunity-slug>.py notebook(s) from analysis/backlog.json",
        description=(
            "Render Databricks-source notebooks (# MAGIC %md cells, # COMMAND ---------- separators) "
            "for --item <OPP-ID>[:<target>] (repeatable) or --all act_now/investigate items. The "
            "evidence cell embeds the public system.* SQL of the cited verify results. Each rendered path "
            "is written into its backlog item's `notebook` field (atomic; --no-update-backlog to skip)."
        ),
    )
    r.add_argument("--backlog", required=True, help="Path to analysis/backlog.json")
    r.add_argument("--item", action="append", default=None, metavar="OPP-ID[:TARGET]",
                   help="Item to render; add :<target> to pick one of several items with the same id")
    r.add_argument("--all", dest="render_all", action="store_true",
                   help="Render every act_now / investigate item")
    r.add_argument("--run-dir", default=None,
                   help="Run directory the evidence paths are relative to (default: the backlog's ../..)")
    r.add_argument("--out", required=True, metavar="DIR", help="Output directory, e.g. deliverables/notebooks/")
    r.add_argument("--template", default=None, help="Notebook template (default: engagement templates/notebook.py)")
    r.add_argument("--verify-templates", default=None, metavar="MD",
                   help="Public verify-SQL templates used to rebuild evidence SQL (default: verify-sql.md)")
    r.add_argument("--source-templates", default=None, metavar="MD",
                   help=("Templates hand-run .sql evidence was filled from (e.g. the internal ones), used "
                         "to recover its params when the .json has no `verify run` metadata"))
    r.add_argument("--no-update-backlog", dest="no_update_backlog", action="store_true",
                   help="Do not write the rendered notebook paths into the backlog items' `notebook` field")
    r.set_defaults(func=cmd_render)


def cmd_render(args) -> dict[str, Any]:
    backlog_path = Path(args.backlog)
    if not backlog_path.is_file():
        raise NotFoundError(f"backlog not found: {backlog_path}")
    try:
        backlog = json.loads(backlog_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ArgError(f"backlog is not valid JSON: {exc}") from exc
    if args.item and args.render_all:
        raise ArgError("pass --item or --all, not both")
    run_dir = Path(args.run_dir) if args.run_dir else backlog_path.resolve().parent.parent
    template_path = Path(args.template) if args.template else _verify.skill_file(*NOTEBOOK_TEMPLATE_REL)
    template_text = template_path.read_text(encoding="utf-8")
    _, public_templates = _verify.load_templates(args.verify_templates)
    source_templates = (
        _verify.load_templates(args.source_templates)[1] if getattr(args, "source_templates", None) else None
    )
    ws = str(backlog.get("workspace_id") or "") if isinstance(backlog, dict) else ""

    selected = select_items(_items(backlog), args.item, args.render_all)
    planned: dict[str, str] = {}
    for item, target in selected:
        name = notebook_filename(item, target)
        if name in planned:
            raise ArgError(f"two items render to {name} ({planned[name]} and {item['id']}); use --item ID:target")
        planned[name] = item["id"]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[dict[str, Any]] = []
    update = not getattr(args, "no_update_backlog", False)
    updated: list[dict[str, Any]] = []
    for item, target in selected:
        evidence = collect_evidence(item, run_dir, public_templates, source_templates, ws=ws or None)
        item_ws = ws or next((e["params"].get("ws") for e in evidence if e["params"].get("ws")), "")
        if not item_ws:
            raise ArgError("backlog has no workspace_id")
        tgt = target or item_target(item)
        kind = item_target_kind(item)
        deployment = job_deployment(item, run_dir, tgt) if kind == "job" else None
        warehouse = warehouse_current(item, run_dir, tgt) if kind == "warehouse" else None
        text = render_notebook(
            item, target=target, workspace_id=item_ws, template_text=template_text, evidence=evidence,
            templates=public_templates, deployment=deployment, warehouse=warehouse,
        )
        path = out_dir / notebook_filename(item, target)
        path.write_text(text, encoding="utf-8")
        link = _backlog_link(path, run_dir)
        if update and item.get("notebook") != link:
            updated.append({"id": item["id"], "target": tgt, "notebook": link, "previous": item.get("notebook")})
            item["notebook"] = link
        rendered.append({
            "id": item["id"],
            "target": tgt,
            "path": str(path),
            "variant": (item.get("sizing") or {}).get("kind") or "none",
            "evidence_embedded": [e["file"] for e in evidence if e["sql"]],
            "evidence_not_embedded": [e["file"] for e in evidence if not e["sql"]],
            "evidence_not_embedded_reasons": {e["file"]: e.get("reason") for e in evidence if not e["sql"]},
        })
    if updated:
        _verify._atomic_write(backlog_path, json.dumps(backlog, indent=2, ensure_ascii=False) + "\n")
    missing = sum(1 for r in rendered if r["evidence_not_embedded"])
    print(
        f"starboard-helper notebook render: wrote {len(rendered)} notebook(s) to {out_dir}"
        + (f"; {missing} with evidence not embedded (see evidence_not_embedded)" if missing else "")
        + (f"; registered {len(updated)} path(s) in {backlog_path.name}" if updated else ""),
        file=sys.stderr,
    )
    return {
        "template": str(template_path), "count": len(rendered), "rendered": len(rendered),
        "paths": [r["path"] for r in rendered], "notebooks": rendered,
        "backlog": str(backlog_path), "backlog_updated": updated if update else None,
        "backlog_registration": {
            "enabled": update, "written": bool(updated),
            "registered": len(updated) if update else 0,
            "already_registered": len(rendered) - len(updated) if update else 0,
        },
    }


def _backlog_link(path: Path, run_dir: Path) -> str:
    """The backlog ``notebook`` value for a rendered file: relative to the run dir when inside it."""
    resolved, root = path.resolve(), run_dir.resolve()
    return str(resolved.relative_to(root)) if resolved.is_relative_to(root) else str(path)
