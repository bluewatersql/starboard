"""Verify domain helper — fill a ``vt-<id>`` verify template and run it read-only.

``verify run`` replaces hand-filling the verify SQL templates (scope-filter
mistakes, column guessing): it parses the template file at runtime by
``### vt-<id>: title`` heading + the following ```` ```sql ```` block, fills every
``{placeholder}`` from the flags, refuses to run if any placeholder is left, the
statement is not read-only, or the ``workspace_id`` filter for ``--ws`` is
missing, then executes through the same path as ``query sql`` and writes the
``<vt-id>[-<suffix>].sql`` / ``.json`` evidence pair. The ``.json`` rows are
column-keyed objects by default (``--rows objects``; ``--rows arrays`` for positional
rows); ``data.columns`` is always present.

On ANY failure after the ``.sql`` is written (query error, timeout, exception)
the ``.json`` is still written — the standard helper envelope with ``ok: false``,
the ``error`` and ``data.verify`` metadata — a one-line error goes to stderr and
the command exits non-zero, so an evidence pair is never half-written. Both files
are written through the artifact sink (a stale local ``.json`` is dropped first).

``--run-folder ID`` writes the pair to that Drive run folder instead: ``--out`` is
then a run-relative directory under ``analysis/verify`` (the default), ``--ws`` must
be in the run's authorized scope, the ``.json`` is recorded as run evidence, and
stdout is the bounded compact envelope (``--stdout`` prints it in full; refused on a
covered run).

Argument errors found once the template id is known (bad ``--ws``, missing
``--start/--end`` for a template that uses window placeholders, unfilled
placeholders, a missing workspace filter, ...) also write ``<stem>.json`` with
``ok: false`` (``data.verify.arg_error: true``), so every attempted verify leaves
its ``.json``. Only argparse errors (unknown flag, flag without a value) and an
invalid ``--suffix`` (no safe file name) write nothing.

``--start/--end`` are needed only when the template uses a window placeholder
(``start``/``end``/``window_days``/``lookback_days``/``qh_start``/``qh_end``, or
``split_date`` without ``--split-date``). ``verify list`` prints the ids, titles
and placeholders of a template file: ``derived`` (computed from other flags),
``required`` (placeholder → the flag that fills it) and ``required_flags`` — the
same :func:`requirements` that ``verify run`` enforces.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

from starboard_skills.helpers import query as _query
from starboard_skills.helpers.contract import (
    ApiError,
    ArgError,
    HelperError,
    HelperRun,
    NotFoundError,
    ProfileMismatchError,
    StorageRefusedError,
    add_run_folder_args,
    api_error_text,
    build_meta,
    envelope,
    helper_writer,
    local_run_dir,
    record_evidence,
    refuse_local,
    relpath_flag,
    run_result,
    storage_failure,
)

#: Run-relative directory of the verify evidence pairs on a ``--run-folder`` run.
VERIFY_DIR = "analysis/verify"

#: Relative path of the public verify templates inside the engagement skill.
PUBLIC_TEMPLATES_REL = ("references", "verify-sql.md")
_ENGAGEMENT_SKILL = "starboard-engagement"

_HEADING = re.compile(r"^###\s+(?P<id>vt-[\w-]+)\s*:\s*(?P<title>.*?)\s*$", re.MULTILINE)
_ANY_H3 = re.compile(r"^###\s", re.MULTILINE)
_SQL_BLOCK = re.compile(r"```sql[ \t]*\n(?P<sql>.*?)\n?```", re.DOTALL)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Identifier values are interpolated into SQL literals, so the charset is closed:
# no quote, backslash, semicolon or whitespace can reach the statement.
_ID_VALUE = re.compile(r"^[\w.:-]+$")
# ``--set`` values (e.g. ``change_time`` = ``2026-09-30 23:53:39``) also allow a space.
_SET_VALUE = re.compile(r"^[\w.: -]+$")
_SUFFIX = re.compile(r"^[\w.-]+$")
_QH_MAX_DAYS = 7
_DEFAULT_LIMIT = 1000
#: Row cap of ``verify run``: its rows go to the run folder / ``--out`` file, never to
#: stdout, so it is above ``query sql``'s 1000-row stdout cap. Equals the kernel's
#: ``plays.VERIFY_LIMIT`` (the ``--limit`` the play commands pass); a test pins that.
VERIFY_ROW_LIMIT = 20000
#: Default ``--timeout``: below the 600 s tool limit, so a slow statement fails (cancelled,
#: retryable with a larger --timeout) instead of killing the whole tool call.
_DEFAULT_TIMEOUT_S = 240.0

#: Single-id placeholder → its list form (filled when more than one id was given).
_SINGLE_ID = {
    "job_id": "job_ids", "warehouse_id": "warehouse_ids", "pipeline_id": "pipeline_ids",
    "endpoint_id": "endpoint_ids",
}
#: Which flag fills which placeholder — used in the unfilled-placeholder error.
_PLACEHOLDER_HINTS = {
    "ws": "--ws",
    "start": "--start",
    "end": "--end",
    "window_days": "--start/--end",
    "job_id": "--job-ids (exactly one id)",
    "job_ids": "--job-ids (one or more ids)",
    "warehouse_id": "--warehouse-ids (exactly one id)",
    "warehouse_ids": "--warehouse-ids (one or more ids)",
    "pipeline_id": "--pipeline-ids (exactly one id)",
    "pipeline_ids": "--pipeline-ids (one or more ids)",
    "endpoint_id": "--endpoint-ids (exactly one id)",
    "endpoint_ids": "--endpoint-ids (one or more ids)",
    "split_date": "--split-date",
    "step_date": "--split-date",
    "before_start": "--split-date",
    "before_end": "--split-date",
    "after_end": "--split-date",
    "qh_start": "--start/--end",
    "qh_end": "--start/--end",
    "lookback_days": "--start/--end",
    "change_time": "--split-date (midnight) or --set change_time='YYYY-MM-DD HH:MM:SS'",
}

#: Placeholders ``derive_params`` always fills from ``--ws/--start/--end`` (``--set`` overrides).
DERIVED_PLACEHOLDERS = frozenset(
    {"ws", "start", "end", "window_days", "qh_start", "qh_end", "lookback_days", "split_date"}
)
#: Placeholders filled from ``--start/--end`` — a template using any of them needs both flags.
WINDOW_PLACEHOLDERS = frozenset({"start", "end", "window_days", "qh_start", "qh_end", "lookback_days"})

_RUN_EPILOG = """\
id lists (--job-ids / --warehouse-ids / --pipeline-ids / --endpoint-ids) accept any of:
  --job-ids 1,2,3      --job-ids 1 2 3      --job-ids 1 --job-ids 2 --job-ids 3
  (put VT_ID before the flags: a space-separated list takes every following bare value)

workspace: --ws fills {ws}; on the internal source --ws defaults to --internal-workspace-id
(when both are given they must be equal).

--start/--end: required only when the template uses start, end, window_days, lookback_days,
qh_start or qh_end (or split_date without --split-date); `verify list` required_flags says which.

derived placeholders (filled when the template uses them and no --set is given):
  window_days, lookback_days = (end - start) + 1
  qh_start, qh_end           = max(start, end - 6 days) .. end  (7-day query-history window)
  split_date                 = --split-date, else --start ("no split")
  step_date, before_start, before_end, after_end = 7-day bounds around --split-date
  change_time                = '<--split-date> 00:00:00'
  --set NAME=VALUE always overrides; `verify list` shows derived vs required per template.

rows: the .json rows are column-keyed objects by default (`data.rows[].<column>`); pass
--rows arrays for positional rows aligned with `data.columns`. `data.columns` is always written.

failure: on any error once VT_ID is known (argument errors included, exit 4), <stem>.json is
still written with ok:false + the error + data.verify metadata, a one-line error goes to
stderr, and the exit code is non-zero (3 = API error / timeout).

parallelism: run at most 3 verifies concurrently on the shared warehouse / internal
source (timeline and query-history templates are heavy); run the rest in waves.
"""


@dataclass(frozen=True)
class VerifyTemplate:
    """One ``vt-<id>`` template parsed from a verify-SQL markdown file."""

    vt_id: str
    title: str
    sql: str

    @property
    def placeholders(self) -> list[str]:
        return list(dict.fromkeys(_PLACEHOLDER.findall(self.sql)))


# --------------------------------------------------------------------------- #
# Template location + parsing
# --------------------------------------------------------------------------- #


def skill_file(*rel: str) -> Path:
    """Locate a file inside the engagement skill (dev tree, wheel, or plugin).

    Search order: ``$CLAUDE_PLUGIN_ROOT/skills/<skill>/``; the dev checkout
    (``<pkg-parent>/skills/starboard/<skill>/``); the wheel-vendored copy
    (``<pkg>/skills/starboard/<skill>/``); then any ancestor's
    ``plugin/skills/<skill>/`` or ``skills/<skill>/`` (vendored plugin layout).
    """
    import starboard_skills

    pkg = Path(starboard_skills.__file__).resolve().parent
    candidates: list[Path] = []
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        candidates.append(Path(plugin_root) / "skills" / _ENGAGEMENT_SKILL)
    candidates += [
        pkg.parent / "skills" / "starboard" / _ENGAGEMENT_SKILL,
        pkg / "skills" / "starboard" / _ENGAGEMENT_SKILL,
    ]
    for parent in pkg.parents:
        candidates += [
            parent / "plugin" / "skills" / _ENGAGEMENT_SKILL,
            parent / "skills" / _ENGAGEMENT_SKILL,
        ]
    for base in candidates:
        path = base.joinpath(*rel)
        if path.is_file():
            return path
    raise NotFoundError(
        f"could not locate {_ENGAGEMENT_SKILL}/{'/'.join(rel)} in the skills tree; "
        "pass the path explicitly"
    )


def default_templates_path() -> Path:
    """The public ``verify-sql.md`` shipped with the skills."""
    return skill_file(*PUBLIC_TEMPLATES_REL)


def parse_templates(text: str) -> dict[str, VerifyTemplate]:
    """Parse ``### vt-<id>: title`` headings and their first ```` ```sql ```` block.

    The SQL block must sit between the heading and the next ``###`` heading; a
    heading without one is skipped. A duplicated id is an error (ambiguous).
    """
    out: dict[str, VerifyTemplate] = {}
    for match in _HEADING.finditer(text):
        nxt = _ANY_H3.search(text, match.end())
        section_end = nxt.start() if nxt else len(text)
        block = _SQL_BLOCK.search(text, match.end(), section_end)
        if not block:
            continue
        vt_id = match.group("id")
        if vt_id in out:
            raise ArgError(f"verify template {vt_id} is defined twice")
        out[vt_id] = VerifyTemplate(vt_id, match.group("title"), block.group("sql").strip())
    return out


def load_templates(path: str | Path | None) -> tuple[Path, dict[str, VerifyTemplate]]:
    tpl_path = Path(path) if path else default_templates_path()
    if not tpl_path.is_file():
        raise NotFoundError(f"templates file not found: {tpl_path}")
    templates = parse_templates(tpl_path.read_text(encoding="utf-8"))
    if not templates:
        raise ArgError(f"no '### vt-<id>: title' + sql templates found in {tpl_path}")
    return tpl_path, templates


# --------------------------------------------------------------------------- #
# Placeholder derivation
# --------------------------------------------------------------------------- #


def _date(value: str, flag: str) -> dt.date:
    if not value or not _DATE.match(value):
        raise ArgError(f"{flag} must be YYYY-MM-DD, got {value!r}")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ArgError(f"{flag} is not a valid date: {value!r}") from exc


_ID_FORMS = "accepted forms: {flag} 1,2  |  {flag} 1 2  |  {flag} 1 {flag} 2"


def _ids(value: str | list[str] | None, flag: str) -> list[str]:
    """Ids from a comma- and/or space-separated string, or a list of such strings
    (``nargs='+'`` and repeated flags), de-duplicated in order."""
    if not value:
        return []
    parts = [value] if isinstance(value, str) else list(value)
    ids = list(dict.fromkeys(v for part in parts for v in re.split(r"[\s,]+", str(part)) if v))
    for v in ids:
        if not _ID_VALUE.match(v):
            raise ArgError(
                f"{flag}: invalid id {v!r} (letters, digits, '_', '-', '.', ':' only; "
                + _ID_FORMS.format(flag=flag) + ")"
            )
    return ids


def _quoted(ids: list[str]) -> str:
    return ", ".join(f"'{v}'" for v in ids)


def derive_params(
    *,
    ws: str,
    start: str | None,
    end: str | None,
    job_ids: str | list[str] | None = None,
    warehouse_ids: str | list[str] | None = None,
    pipeline_ids: str | list[str] | None = None,
    endpoint_ids: str | list[str] | None = None,
    split_date: str | None = None,
    sets: list[str] | None = None,
) -> dict[str, str]:
    """Build the placeholder → value map from the CLI flags (deterministic).

    * ``window_days`` = inclusive days ``start..end``.
    * ``job_ids`` / ``warehouse_ids`` / ``pipeline_ids`` / ``endpoint_ids`` = quoted SQL
      list; the singular ``job_id`` / ``warehouse_id`` / ``pipeline_id`` /
      ``endpoint_id`` only when exactly one id was given.
    * ``split_date`` = ``--split-date`` (else ``start``: "no split").
    * ``step_date`` / ``before_start`` / ``before_end`` / ``after_end`` = the 7-day
      bounds around ``--split-date`` (only when it is given).
    * ``change_time`` = ``<--split-date> 00:00:00`` (only when it is given).
    * ``qh_start`` / ``qh_end`` = the last <=7 days of the window (query history).
    * ``lookback_days`` = ``window_days``. ``--set NAME=VALUE`` overrides anything.

    Without ``start``/``end`` (both omitted) the window placeholders are simply not filled;
    one without the other is an error.
    """
    if not ws or not _ID_VALUE.match(ws):
        raise ArgError(f"--ws: invalid workspace id {ws!r}")
    if bool(start) != bool(end):
        raise ArgError("pass both --start and --end (or neither, for a template without window placeholders)")
    params: dict[str, str] = {"ws": ws}
    if start and end:
        d_start, d_end = _date(start, "--start"), _date(end, "--end")
        if d_start > d_end:
            raise ArgError(f"--start {start} is after --end {end}")
        window_days = str((d_end - d_start).days + 1)
        params.update({
            "start": d_start.isoformat(),
            "end": d_end.isoformat(),
            "window_days": window_days,
            "qh_start": max(d_start, d_end - dt.timedelta(days=_QH_MAX_DAYS - 1)).isoformat(),
            "qh_end": d_end.isoformat(),
            "lookback_days": window_days,
            "split_date": d_start.isoformat(),
        })
    for flag, plural, singular, raw in (
        ("--job-ids", "job_ids", "job_id", job_ids),
        ("--warehouse-ids", "warehouse_ids", "warehouse_id", warehouse_ids),
        ("--pipeline-ids", "pipeline_ids", "pipeline_id", pipeline_ids),
        ("--endpoint-ids", "endpoint_ids", "endpoint_id", endpoint_ids),
    ):
        ids = _ids(raw, flag)
        if ids:
            params[plural] = _quoted(ids)
            if len(ids) == 1:
                params[singular] = ids[0]
    if split_date:
        step = _date(split_date, "--split-date")
        params.update(
            split_date=step.isoformat(),
            step_date=step.isoformat(),
            before_start=(step - dt.timedelta(days=7)).isoformat(),
            before_end=(step - dt.timedelta(days=1)).isoformat(),
            after_end=(step + dt.timedelta(days=6)).isoformat(),
            change_time=f"{step.isoformat()} 00:00:00",
        )
    for kv in sets or []:
        name, sep, value = kv.partition("=")
        name, value = name.strip(), value.strip().strip("'\"")
        if not sep or not re.match(r"^\w+$", name):
            raise ArgError(f"--set must be NAME=VALUE, got {kv!r}")
        if not _SET_VALUE.match(value):
            raise ArgError(f"--set {name}: value {value!r} has disallowed characters")
        params[name] = value
    return params


def requirements(template: VerifyTemplate) -> dict[str, str]:
    """Placeholder → the flag that fills it, for every placeholder but ``{ws}`` (always
    filled from ``--ws`` / ``--internal-workspace-id``). The single source of truth for
    ``verify list`` ``required`` and for what ``verify run`` enforces."""
    out: dict[str, str] = {}
    for p in template.placeholders:
        if p == "ws":
            continue
        if p == "split_date":
            out[p] = "--split-date (else --start/--end: no split)"
        else:
            out[p] = _PLACEHOLDER_HINTS.get(p, f"--set {p}=VALUE")
    return out


def required_flags(template: VerifyTemplate) -> list[str]:
    """The ``verify run`` flags this template needs (``--set`` overrides any of them)."""
    flags: list[str] = []
    for p in template.placeholders:
        if p == "ws":
            continue
        if p in WINDOW_PLACEHOLDERS:
            flags += ["--start", "--end"]
        elif p == "split_date":
            continue  # --split-date or --start/--end; never required on its own
        elif p in ("job_id", "job_ids"):
            flags.append("--job-ids")
        elif p in ("warehouse_id", "warehouse_ids"):
            flags.append("--warehouse-ids")
        elif p in ("pipeline_id", "pipeline_ids"):
            flags.append("--pipeline-ids")
        elif p in ("endpoint_id", "endpoint_ids"):
            flags.append("--endpoint-ids")
        elif p in ("step_date", "before_start", "before_end", "after_end", "change_time"):
            flags.append("--split-date")
        else:
            flags.append(f"--set {p}=VALUE")
    if "split_date" in template.placeholders and "--split-date" not in flags and "--start" not in flags:
        flags.append("--split-date or --start/--end")
    return list(dict.fromkeys(flags))


def _check_window(template: VerifyTemplate, start: str | None, end: str | None, split_date: str | None,
                  sets: list[str] | None) -> None:
    """``--start/--end`` are required exactly when :func:`required_flags` says so."""
    if start and end:
        return
    if start or end:
        raise ArgError("pass both --start and --end (or neither, for a template without window placeholders)")
    overridden = {kv.partition("=")[0].strip() for kv in sets or []}
    window = [p for p in template.placeholders if p in WINDOW_PLACEHOLDERS and p not in overridden]
    if "split_date" in template.placeholders and not split_date and "split_date" not in overridden:
        window.append("split_date")
    if window:
        raise ArgError(
            f"{template.vt_id} uses {', '.join('{' + p + '}' for p in window)}: pass --start and --end "
            "(YYYY-MM-DD, full days)"
        )


def fill(template: VerifyTemplate, params: dict[str, str]) -> str:
    """Substitute every ``{placeholder}``; ArgError listing any left unfilled."""
    missing = [p for p in template.placeholders if p not in params]
    if missing:
        hints = ", ".join(f"{{{p}}} ({_PLACEHOLDER_HINTS.get(p, f'--set {p}=VALUE')})" for p in missing)
        several = [p for p in missing if p in _SINGLE_ID and _SINGLE_ID[p] in params]
        if several:
            n = params[_SINGLE_ID[several[0]]].count(",") + 1
            hints += (
                f" — {template.vt_id} takes one id per call and {n} were given: run it once per id "
                "(--suffix <id> keeps the saved files apart)"
            )
        raise ArgError(f"{template.vt_id}: unfilled placeholder(s): {hints}")
    return _PLACEHOLDER.sub(lambda m: params[m.group(1)], template.sql)


def assert_workspace_filter(sql: str, ws: str) -> None:
    """The filled statement must filter ``workspace_id`` to ``ws`` (fleet-safe)."""
    pattern = re.compile(
        r"\bworkspace_id\s*(?:=\s*'" + re.escape(ws) + r"'|IN\s*\(\s*'" + re.escape(ws) + r"'\s*\))",
        re.IGNORECASE,
    )
    if not pattern.search(sql):
        raise ArgError(
            f"refusing to run: the statement has no workspace_id = '{ws}' filter "
            "(system tables span every workspace in the account)"
        )


def _verify_dir(value: str | None, *, covered: bool) -> PurePosixPath:
    """``--out`` on a run-folder run: a relpath under :data:`VERIFY_DIR` (the default).

    A trailing ``/`` names the same directory (``analysis/verify/``).
    """
    raw = (value or VERIFY_DIR).rstrip("/") or (value or VERIFY_DIR)
    rel = relpath_flag("--out", raw, covered=covered)
    if rel != VERIFY_DIR and not rel.startswith(VERIFY_DIR + "/"):
        raise ArgError(f"--out {rel!r} must be {VERIFY_DIR} or below it with --run-folder")
    return PurePosixPath(rel)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def register(subparsers) -> None:
    p = subparsers.add_parser("verify", help="Fill and run vt-<id> verify templates (read-only)")
    sp = p.add_subparsers(dest="command", required=True)

    lst = sp.add_parser("list", help="List template ids, titles and placeholders")
    lst.add_argument(
        "--templates", default=None, metavar="MD",
        help="Verify-SQL markdown file (default: the public verify-sql.md shipped with the skills)",
    )
    lst.set_defaults(func=cmd_list)

    run = sp.add_parser(
        "run",
        help="Fill one vt-<id> template, run it read-only, write <vt-id>[-suffix].sql/.json",
        description=(
            "Fill a vt-<id> template from the flags, refuse unfilled placeholders, non-read-only "
            "SQL, or a missing workspace_id filter, run it via the `query sql` path, and write "
            "the .sql + .json (query result envelope) evidence pair to --out. Query-history "
            "templates get qh_start/qh_end (<= 7 days ending --end) derived automatically."
        ),
        epilog=_RUN_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.add_argument("vt_id", metavar="VT_ID", help="Template id, e.g. vt-product-totals")
    run.add_argument("--templates", default=None, metavar="MD",
                     help="Verify-SQL markdown file (default: the public verify-sql.md)")
    run.add_argument("--ws", default=None,
                     help="Workspace id (fills {ws}; the filter is enforced). Defaults to "
                          "--internal-workspace-id on the internal source; required otherwise")
    run.add_argument("--start", default=None,
                     help="Window start, YYYY-MM-DD (full days, inclusive); required only when the template "
                          "uses a window placeholder (see `verify list` required_flags)")
    run.add_argument("--end", default=None,
                     help="Window end, YYYY-MM-DD (inclusive; a window ending today includes "
                          "today's partial data); required with --start")
    for flag, plural, singular in (
        ("--job-ids", "job_ids", "job_id"),
        ("--warehouse-ids", "warehouse_ids", "warehouse_id"),
        ("--pipeline-ids", "pipeline_ids", "pipeline_id"),
        ("--endpoint-ids", "endpoint_ids", "endpoint_id"),
    ):
        run.add_argument(
            flag, nargs="+", action="extend", default=None, metavar="ID",
            help=f"Ids for {{{plural}}} (one id also fills {{{singular}}}): {flag} 1,2 or {flag} 1 2 "
                 f"or repeat {flag}",
        )
    run.add_argument("--split-date", default=None,
                     help="YYYY-MM-DD split/step date ({split_date}, {step_date} and its 7-day bounds)")
    run.add_argument("--suffix", default=None, help="Output file suffix: <vt-id>-<suffix>.sql/.json")
    run.add_argument("--set", dest="sets", action="append", default=None, metavar="NAME=VALUE",
                     help="Fill/override any placeholder, e.g. --set change_time='2026-09-30 23:53:39'")
    run.add_argument("--internal-workspace-id", default=None, metavar="ID",
                     help="Run on the internal source scoped to this workspace (must equal --ws)")
    run.add_argument("--profile", default=None, metavar="NAME",
                     help="Databricks CLI profile (public path); with --run-folder it defaults "
                          "to the run's verified profile and another one is refused "
                          "(PROFILE_MISMATCH, exit 2)")
    run.add_argument("--warehouse-id", default=None, help="SQL warehouse to run on (public path)")
    run.add_argument("--limit", type=int, default=_DEFAULT_LIMIT, help=f"Max rows written (capped at {VERIFY_ROW_LIMIT})")
    run.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT_S, metavar="SECONDS",
                     help=f"Max seconds to wait for the statement (public path; default {_DEFAULT_TIMEOUT_S:g})")
    run.add_argument("--rows", choices=["arrays", "objects"], default="objects",
                     help=("Row shape in the .json (same as `query sql --rows`): objects (default) = "
                           "column-keyed rows; arrays = positional rows aligned with data.columns"))
    run.add_argument("--out", default=None, metavar="DIR",
                     help="Output directory, e.g. analysis/verify/ (required without --run-folder; "
                          f"with it a run-relative dir, default {VERIFY_DIR})")
    add_run_folder_args(run)
    run.set_defaults(func=cmd_run)


def cmd_list(args) -> dict[str, Any]:
    path, templates = load_templates(args.templates)
    return {
        "templates": str(path),
        "count": len(templates),
        "items": [
            {
                "id": t.vt_id,
                "title": t.title,
                "placeholders": t.placeholders,
                "derived": [p for p in t.placeholders if p in DERIVED_PLACEHOLDERS],
                "required": requirements(t),
                "required_flags": required_flags(t),
            }
            for t in templates.values()
        ],
    }


def _write_failure(
    run: HelperRun, json_path: PurePosixPath | Path, verify_meta: dict[str, Any], message: str
) -> None:
    failure = envelope(
        ok=False, domain="query", command="sql",
        data={"verify": verify_meta}, error=message, meta=build_meta(),
    )
    # The original error is what matters; stderr + the exit code still report it.
    with contextlib.suppress(Exception):
        run.write(json_path, (json.dumps(failure, indent=2, default=str) + "\n").encode("utf-8"))


def cmd_run(args) -> dict[str, Any]:
    run_folder = getattr(args, "run_folder", None)
    stdout = bool(getattr(args, "stdout", False))
    if not run_folder and not args.out:
        raise ArgError("the following arguments are required: --out")
    with helper_writer(
        run_folder=run_folder,
        local_root=None if run_folder else local_run_dir(args.out),
        acquires=not args.internal_workspace_id,
    ) as run:
        refuse_local(run, stdout=stdout)
        out_dir: PurePosixPath | Path = (
            _verify_dir(args.out, covered=run.covered) if run.drive else Path(args.out)
        )
        summary = _run(args, run, out_dir)
    return run_result(run, summary, stdout=stdout)


def _local_scope(out: str) -> tuple[str, ...]:
    """``authorized_scope.workspace_ids`` of the local run dir ``out`` resolves into.

    ``()`` when ``out`` is in no run dir or its descriptor is unreadable: only a recorded,
    non-empty scope bounds a local verify.
    """
    root = Path(local_run_dir(Path(out).expanduser().resolve()) or "")
    try:
        doc = json.loads((root / "analysis" / "run-authorization.json").read_text(encoding="utf-8"))
        ids = doc["authorized_scope"]["workspace_ids"] or ()
        return tuple(str(i) for i in ids)
    except (OSError, ValueError, TypeError, KeyError):
        return ()


def _run_profile(run: HelperRun, profile: str | None) -> str | None:
    """The verified profile of a Drive run (default for an omitted ``--profile``).

    Raises:
        ProfileMismatchError: ``PROFILE_MISMATCH`` (exit 2) — another profile.
    """
    from starboard_core.engagement.identity import (  # lazy – kernel dep
        ProfileMismatch,
        run_profile,
    )

    try:
        return run_profile(run.descriptor(), profile)
    except ProfileMismatch as exc:
        raise ProfileMismatchError(str(exc)) from exc


def _run(args, run: HelperRun, out_dir: PurePosixPath | Path) -> dict[str, Any]:
    path, templates = load_templates(args.templates)
    template = templates.get(args.vt_id)
    if template is None:
        raise NotFoundError(
            f"unknown verify template {args.vt_id!r} in {path}; known: {', '.join(templates)}"
        )
    if args.suffix and not _SUFFIX.match(args.suffix):
        raise ArgError(f"--suffix {args.suffix!r}: letters, digits, '_', '-', '.' only")
    internal_ws = args.internal_workspace_id
    stem = f"{template.vt_id}-{args.suffix}" if args.suffix else template.vt_id
    sql_path, json_path = out_dir / f"{stem}.sql", out_dir / f"{stem}.json"
    try:
        ws = args.ws or internal_ws
        if not ws:
            raise ArgError("--ws is required (on the internal source it defaults to --internal-workspace-id)")
        if internal_ws:
            if internal_ws != ws:
                raise ArgError(f"--internal-workspace-id {internal_ws} must equal --ws {ws}")
            if args.profile or args.warehouse_id:
                raise ArgError("--internal-workspace-id cannot be combined with --profile/--warehouse-id")
        elif not args.warehouse_id:
            raise ArgError("pass --internal-workspace-id <id>, or --warehouse-id <id> [--profile p]")
        scope = run.scope_workspace_ids() if run.drive else _local_scope(args.out)
        if (run.drive or scope) and ws not in scope:
            raise StorageRefusedError(
                f"--ws {ws} is outside the run's authorized scope ({', '.join(scope) or 'none'})"
            )
        if run.drive and not internal_ws:
            args.profile = _run_profile(run, args.profile)
        _check_window(template, args.start, args.end, args.split_date, args.sets)
        params = derive_params(
            ws=ws, start=args.start, end=args.end,
            job_ids=args.job_ids, warehouse_ids=args.warehouse_ids, pipeline_ids=args.pipeline_ids,
            endpoint_ids=args.endpoint_ids,
            split_date=args.split_date, sets=args.sets,
        )
        sql = fill(template, params)
        _query._assert_read_only(sql)
        assert_workspace_filter(sql, ws)
    except StorageRefusedError:
        raise  # a scope refusal leaves nothing in the run
    except HelperError as exc:
        # Argument error once the template is known: still leave an ok:false <stem>.json
        # (no stale .sql), so the "every verify writes its json" bookkeeping holds.
        if not run.drive:
            with contextlib.suppress(OSError):
                Path(sql_path).unlink(missing_ok=True)
        _write_failure(run, json_path, {
            "vt_id": template.vt_id, "title": template.title, "templates": str(path), "suffix": args.suffix,
            "params": None, "source": "internal" if internal_ws else "public", "sql_file": None,
            "arg_error": True, "required": requirements(template), "required_flags": required_flags(template),
        }, exc.message)
        print(f"starboard-helper verify run {stem}: FAILED: {exc.message}", file=sys.stderr)
        raise

    if not run.drive:
        # Drop a stale result first so a crashed run never leaves a mismatched pair.
        # (On Drive the .json is always rewritten: a failure writes an ok:false one.)
        Path(json_path).unlink(missing_ok=True)
    try:
        run.write(sql_path, (sql + "\n").encode("utf-8"))
    except OSError as exc:
        raise ApiError(f"could not write {sql_path}: {exc}") from exc

    used = {k: params[k] for k in template.placeholders}
    # An id flag the template has no placeholder for would look like a scope it doesn't
    # apply (e.g. --job-ids on an account-wide product total): say so.
    ignored = [
        flag for flag, value, names in (
            ("--job-ids", args.job_ids, ("job_id", "job_ids")),
            ("--warehouse-ids", args.warehouse_ids, ("warehouse_id", "warehouse_ids")),
            ("--pipeline-ids", args.pipeline_ids, ("pipeline_id", "pipeline_ids")),
            ("--endpoint-ids", args.endpoint_ids, ("endpoint_id", "endpoint_ids")),
        )
        if value and not any(n in template.placeholders for n in names)
    ]
    for flag in ignored:
        print(
            f"starboard-helper verify run {stem}: warning: {flag} ignored — {template.vt_id} "
            "has no matching placeholder, so the result is not scoped by it",
            file=sys.stderr,
        )
    verify_meta = {
        "vt_id": template.vt_id,
        "title": template.title,
        "templates": str(path),
        "suffix": args.suffix,
        "params": used,
        "source": "internal" if internal_ws else "public",
        "sql_file": sql_path.name,
    }
    query_args = SimpleNamespace(
        sql=sql, warehouse_id=args.warehouse_id, profile=args.profile, limit=args.limit,
        param=None, timeout=None if internal_ws else args.timeout, rows=args.rows,
        internal_workspace_id=internal_ws, max_rows=VERIFY_ROW_LIMIT,
    )
    try:
        data = _query.cmd_sql(query_args)
        data["verify"] = verify_meta
        result_envelope = envelope(ok=True, domain="query", command="sql", data=data, meta=build_meta())
        ref = run.write(
            json_path,
            (json.dumps(result_envelope, indent=2, default=str) + "\n").encode("utf-8"),
        )
    except BaseException as exc:
        # Any failure after the .sql exists: still write the .json (ok:false) so the
        # pair is explicit, say so on stderr, and exit non-zero via HelperError. A
        # Drive failure keeps its storage code (a transient one is exit 8, retryable).
        failure = storage_failure(exc) if isinstance(exc, Exception) else None
        if isinstance(exc, HelperError):
            message = exc.message
        elif failure is not None:
            message = failure.message
        elif isinstance(exc, OSError):
            message = f"could not write {json_path}: {exc}"
        elif isinstance(exc, Exception):
            message = f"API error: {api_error_text(exc)}"
        else:
            message = f"interrupted ({type(exc).__name__})"
        _write_failure(run, json_path, verify_meta, message)
        print(f"starboard-helper verify run {stem}: FAILED: {message}", file=sys.stderr)
        if isinstance(exc, HelperError) or not isinstance(exc, Exception):
            raise
        if failure is not None:
            raise failure from exc
        raise ApiError(message) from exc

    if ref is not None:
        record_evidence(
            run,
            [(ref, f"verify:{template.vt_id}", data.get("row_count"),
              bool(data.get("limit_reached")))],
            source_kind="internal_mirror" if internal_ws else "customer_workspace",
        )
    summary: dict[str, Any] = {
        "vt_id": template.vt_id,
        "sql_path": str(sql_path),
        "json_path": str(json_path),
        "row_count": data.get("row_count"),
        "limit_reached": data.get("limit_reached"),
        "source": data["verify"]["source"],
        "params": used,
    }
    if "top_n" in data:
        summary["top_n"] = data["top_n"]  # the SQL's own LIMIT: limit_reached is false
    if "attempts" in data:
        summary["attempts"] = data["attempts"]
    if data.get("limit_capped"):
        summary["requested_limit"] = data["requested_limit"]
        summary["limit_capped"] = True
    if ignored:
        summary["ignored_flags"] = ignored
    overridden = {kv.partition("=")[0].strip() for kv in args.sets or []}
    if "qh_start" in used and "qh_start" not in overridden and used["qh_start"] != params.get("start"):
        # Query history reads at most the last 7 days ending --end: say so.
        summary["qh_window_clamped"] = {
            "requested_start": params["start"],
            "qh_start": used["qh_start"],
            "max_days": _QH_MAX_DAYS,
        }
        print(
            f"starboard-helper verify run {stem}: warning: query history reads at most "
            f"{_QH_MAX_DAYS} days, so {used['qh_start']}..{params['qh_end']} ran, not "
            f"{params['start']}..; to read an older day set --end within "
            f"{_QH_MAX_DAYS - 1} days after it",
            file=sys.stderr,
        )
    return summary
