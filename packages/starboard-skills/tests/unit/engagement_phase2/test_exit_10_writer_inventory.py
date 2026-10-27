"""P2-G14 exit test 10 - writer inventory by introspection.

Spec item 10: "A test enumerates all argparse output/input-path flags across
CLI/helpers (introspection) and asserts each is either mapped to a relpath under
``--run-folder`` or is on an explicit public-only list."

How it works:

* Every public argparse entry point is built (no command runs) and walked
  recursively through its sub-parsers. A flag is *path-like* when its name or
  metavar looks like a path/output, or its help text talks about a path, file or
  directory.
* Every path-like flag must be classified in exactly one table below, and every
  table entry must still exist (no stale entries). A new path flag therefore fails
  this test until it is consciously classified.
* ``RUN_RELPATH`` flags must live on a parser that has ``--run-folder`` (the helper
  root ``--out`` is mapped through the fetch-domain ``--run-folder`` extraction).
* A guard test checks that no public module grew an ``ArgumentParser`` this test
  does not walk.

Deviation from the two-list wording of the spec: shipped reference inputs
(templates, ``--config``, the overlay ticket JSON) are neither customer data nor
outputs, so they sit in a third list, ``LOCAL_CONTROL``.

The behavioural half covers W30 (customer-file intake refused on overlay
installs) for the ``starboard_x`` analyzers that take a local file.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.policy import LOCAL_FILE_INTAKE_GUIDANCE
from starboard_x.diagnostic import __main__ as diagnostic_cli
from starboard_x.sparklog import __main__ as sparklog_cli
from starboard_x.uc import __main__ as uc_cli
from starboard_x.warehouse import __main__ as warehouse_cli

from ._support import _call, helper, routed

REPO = Path(__file__).resolve().parents[5]


class _Captured(Exception):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        self.parser = parser


def _capture(fn: Callable[[list[str]], Any]) -> argparse.ArgumentParser:
    """The parser a ``parse_args(argv)`` function builds, captured before it parses."""

    def raiser(self: argparse.ArgumentParser, *_a: Any, **_kw: Any) -> Any:
        raise _Captured(self)

    real = (argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args)
    argparse.ArgumentParser.parse_args = raiser  # type: ignore[method-assign]
    argparse.ArgumentParser.parse_known_args = raiser  # type: ignore[method-assign]
    try:
        fn([])
    except _Captured as cap:
        return cap.parser
    finally:
        argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args = real
    raise AssertionError(f"{fn} built no parser")


def _x(mod: str) -> Callable[[], argparse.ArgumentParser]:
    return lambda: importlib.import_module(f"starboard_x.{mod}.__main__").build_parser()


SURFACES: dict[str, Callable[[], argparse.ArgumentParser]] = {
    **{f"starboard_x.{m}": _x(m) for m in (
        "charts", "cluster", "diagnostic", "diff", "discovery", "review", "sparklog", "uc",
        "warehouse")},
    "helper": lambda: importlib.import_module(
        "starboard_skills.helpers.__main__").build_parser(),
    "starboard": lambda: _capture(importlib.import_module(
        "starboard.cli.cli.main").parse_args),
    "starboard review": lambda: importlib.import_module(
        "starboard.cli.cli.review_command")._build_parser(),
    "starboard auth": lambda: importlib.import_module(
        "starboard.cli.cli.auth_commands").build_parser(),
    "starboard-mcp": lambda: _capture(importlib.import_module("starboard.mcp.cli").parse_args),
}

# Public modules that build an ArgumentParser, and where this test reaches them.
PARSER_MODULES = {
    "packages/starboard-core/starboard_x/_cli.py": "the ArgumentParser subclass itself",
    **{f"packages/starboard-core/starboard_x/{m}/__main__.py": f"starboard_x.{m}" for m in (
        "charts", "cluster", "diagnostic", "diff", "discovery", "review", "sparklog", "uc",
        "warehouse")},
    "packages/starboard-skills/starboard_skills/helpers/__main__.py": "helper",
    "packages/starboard/starboard/cli/cli/main.py": "starboard",
    "packages/starboard/starboard/cli/cli/review_command.py": "starboard review",
    "packages/starboard/starboard/cli/cli/auth_commands.py": "starboard auth",
    "packages/starboard/starboard/mcp/cli.py": "starboard-mcp",
    # W33: install tooling, out of scope.
    "packages/starboard-skills/starboard_skills/maint/__main__.py": "out of scope (W33)",
}

Key = tuple[str, str, str]  # (surface, sub-command path, flag)

# Mapped to a run-relative path under --run-folder (writers W1-W21, intake W30).
RUN_RELPATH: dict[Key, str] = {
    ("starboard_x.discovery", "run", "--out-dir"): "W1/W2 raw + facts",
    ("starboard_x.discovery", "run", "--output-path"): "W3 envelope",
    ("starboard_x.review", "score", "--rows"): "W30 input (relpath or drive:<id>)",
    ("starboard_x.review", "score", "--out"): "analysis/review.json",
    ("starboard_x.review", "score", "--manifest-out"): "findings-manifest.json",
    ("helper", "", "--out"): "W16 fetch domains (pre-argparse --run-folder)",
    ("helper", "charts render", "--data"): "W21 input",
    ("helper", "charts render", "--out"): "W21 deliverables/charts/...",
    ("helper", "run check", "--out"): "W17 analysis/run-check.json",
    ("helper", "verify run", "--out"): "W19 analysis/verify/...",
    ("helper", "notebook render", "--backlog"): "W20 analysis/backlog.json",
    ("helper", "notebook render", "--out"): "W20 deliverables/notebooks/...",
    ("helper", "engagement put", "--path"): "host artifact relpath",
    ("helper", "engagement read", "--path"): "run artifact relpath",
    ("helper", "engagement report", "--path"): "report relpath",
    ("helper", "engagement analyze", "--manifest"): "run-relative findings manifest",
    ("starboard_x.diff", "settings", "--a"): "run-relative ref or drive:<id> (input)",
    ("starboard_x.diff", "settings", "--b"): "run-relative ref or drive:<id> (input)",
    ("starboard_x.diff", "metrics", "--a"): "run-relative ref or drive:<id> (input)",
    ("starboard_x.diff", "metrics", "--b"): "run-relative ref or drive:<id> (input)",
    ("starboard", "", "--input-file"): "W30 (relpath or drive:<id>)",
    ("starboard", "", "--output-path"): "W5/W12",
    ("starboard", "", "--out-dir"): "W4",
    ("starboard review", "", "--from-discovery"): "W30 input",
    ("starboard review", "", "--since"): "W30 input",
    ("starboard review", "", "--out"): "W9/W11",
    ("starboard review", "", "--manifest-out"): "W10",
    ("starboard review", "", "--snapshot-out"): "W10",
}

# Never mapped to a run folder: local-only (public / internal-only local runs), or
# refused outright on overlay installs.
PUBLIC_ONLY: dict[Key, str] = {
    ("starboard_x.discovery", "run", "--authorization"): "local descriptor; refused on covered",
    ("starboard_x.discovery", "plan", "--authorization"): "local descriptor",
    ("starboard_x.review", "score", "--run-dir"): "internal-only local run",
    ("starboard_x.sparklog", "parse", "--input"): "W30 local intake (or drive:<id>)",
    ("starboard_x.diagnostic", "profile", "--input"): "W30 local intake (or drive:<id>)",
    ("starboard_x.uc", "analyze", "--input"): "W30 local intake",
    ("starboard_x.warehouse", "analyze", "--history"): "W30 local intake",
    ("starboard_x.diagnostic", "triage-exit", "--text"): "W30 local intake",
    ("starboard_x.diagnostic", "extract-evidence", "--text"): "W30 local intake",
    ("starboard_x.diagnostic", "rca", "--text"): "W30 local intake",
    ("helper", "run check", "<run_dir>"): "local run dir (omit with --run-folder)",
    ("helper", "run recur", "<run_dir>"): "local run dir (omit with --run-folder)",
    ("helper", "run recur", "--workspace-root"): "refused with --run-folder",
    ("helper", "run recur", "--prior"): "local prior run (registry with --run-folder)",
    ("helper", "engagement analyze", "--prior"): "drive:<id> prior run (a warning on a local run)",
    ("helper", "notebook render", "--run-dir"): "refused with --run-folder",
    ("helper", "engagement preflight", "--reports-root"): "internal-only local runs",
    ("helper", "engagement preflight", "--run-dir"): "internal-only local runs",
    ("helper", "engagement verify-identity", "--run-dir"): "internal-only local runs",
    ("helper", "engagement route", "--run-dir"): "internal-only local runs",
    ("helper", "engagement status", "--run-dir"): "local runs (read-only)",
    ("helper", "engagement import-local", "--run-dir"): "the local -> Drive bridge",
    **{("helper", f"engagement {verb}", flag): "internal-only local runs"
       for verb in ("analyze", "case open", "case revise", "case show", "action propose",
                    "action accept", "action reject", "action execute", "action withdraw",
                    "play rank")
       for flag in ("--run-dir", "--workspace-root")},
    ("starboard", "", "--authorization"): "local descriptor",
    ("starboard", "", "--log-file"): "W13 refused on overlay",
    ("starboard", "", "--session"): "W14 refused on overlay",
    ("starboard", "", "--session-db"): "W14 refused on overlay",
    ("starboard review", "", "--run-dir"): "internal-only local run",
}

# Local reference/control inputs: shipped templates, config, overlay ticket JSON.
LOCAL_CONTROL: dict[Key, str] = {
    ("helper", "verify list", "--templates"): "shipped verify templates",
    ("helper", "verify run", "--templates"): "shipped verify templates",
    ("helper", "notebook render", "--template"): "shipped notebook template",
    ("helper", "notebook render", "--verify-templates"): "shipped verify templates",
    ("helper", "notebook render", "--source-templates"): "shipped source templates",
    ("helper", "engagement route", "--ticket-ref"): "overlay TicketRef JSON",
    ("starboard", "", "--config"): "local config file",
    ("starboard-mcp", "", "--config"): "local config file",
}

# Path-like by name or help, but not a filesystem path.
NOT_A_PATH: dict[Key, str] = {
    ("starboard_x.diagnostic", "triage-exit", "--context"): "inline text",
    ("starboard_x.discovery", "run", "--data-only"): "mode switch",
    ("starboard_x.discovery", "run", "--no-cache"): "mode switch",
    ("starboard_x.discovery", "run", "--max-seconds"): "capture budget (seconds)",
    ("starboard_x.discovery", "run", "--stdout"): "envelope shape",
    ("helper", "query sql", "--rows"): "row limit",
    ("helper", "verify run", "--rows"): "row limit",
    ("helper", "verify run", "--suffix"): "output name suffix (under --out)",
    ("helper", "charts render", "--stdout"): "envelope shape",
    ("helper", "run check", "--stdout"): "envelope shape",
    ("helper", "run recur", "--stdout"): "envelope shape",
    ("helper", "run recur", "--baseline"): "mode switch",
    ("helper", "engagement analyze", "--baseline"): "mode switch",
    ("helper", "verify run", "--stdout"): "envelope shape",
    ("helper", "notebook render", "--stdout"): "envelope shape",
    ("helper", "notebook render", "--no-update-backlog"): "mode switch",
    ("helper", "engagement route", "--shared-root-id"): "Drive ID",
    ("helper", "engagement route", "--override-folder-id"): "Drive ID",
    ("helper", "engagement read", "--jsonpath"): "JSON path expression",
    ("helper", "engagement report", "--derived-from"): "artifact IDs",
    ("helper", "engagement deliver", "--destination-folder-id"): "Drive ID",
    ("helper", "engagement receipt", "--destination-id"): "channel/destination ID",
    ("helper", "engagement rebuild-index", "--account-name"): "display name",
    ("helper", "engagement case open", "--drive-object"): "Drive ID",
    ("starboard_x.sparklog", "parse", "--path"): "remote dbfs/s3/https path (--source local removed)",
    ("starboard", "", "--json"): "envelope shape",
    ("starboard", "", "--data-only"): "mode switch",
    ("starboard", "", "--no-cache"): "mode switch",
    ("starboard", "", "--max-seconds"): "capture budget (seconds)",
    ("starboard", "", "--stdout"): "envelope shape",
    ("starboard", "", "--full-stdout"): "envelope shape",
    ("starboard review", "", "--no-cache"): "mode switch",
    ("starboard review", "", "--json"): "envelope shape",
    ("starboard auth", "status", "--json"): "envelope shape",
}

# Flag names that are never a path wherever they appear.
GENERIC_NOT_A_PATH = frozenset({
    "--run-folder", "--format", "--profile", "--host", "--token", "--timeout",
    "--timeout-retries", "--log-level", "--catalog", "--warehouse-id", "--warehouse-name",
    "--workspace", "--internal", "--domains", "--storage", "--report-id", "--sql",
    "--port", "--api-key", "--id", "--transport", "--insecure", "--set-default",
})

TABLES = {"run_relpath": RUN_RELPATH, "public_only": PUBLIC_ONLY,
          "local_control": LOCAL_CONTROL, "not_a_path": NOT_A_PATH}

_NAME = re.compile(r"out|dir|path|file|log|rows|data|template|manifest|input|from|session|"
                   r"root|baseline|save|dest|export|spool|cache|config|json|csv|png|svg|"
                   r"since|prior|history|text|ticket|folder|stdout")
_HELP = re.compile(r"\b(path|paths|file|files|dir|directory|folder)\b", re.IGNORECASE)


def _walk(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()
          ) -> Iterator[tuple[tuple[str, ...], argparse.ArgumentParser]]:
    yield path, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _walk(sub, (*path, name))


def _flag(action: argparse.Action) -> str:
    return action.option_strings[-1] if action.option_strings else f"<{action.dest}>"


def _pathlike(action: argparse.Action) -> bool:
    names = [*action.option_strings, action.dest]
    return (any(_NAME.search(n) for n in names)
            or bool(action.metavar and _NAME.search(str(action.metavar).lower()))
            or bool(_HELP.search(action.help or "")))


def _inventory() -> dict[Key, bool]:
    """``(surface, sub-command, flag) -> leaf parser has --run-folder``."""
    found: dict[Key, bool] = {}
    for surface, build in SURFACES.items():
        for path, leaf in _walk(build()):
            has_rf = any("--run-folder" in a.option_strings for a in leaf._actions)
            for action in leaf._actions:
                if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
                    continue
                flag = _flag(action)
                if flag in GENERIC_NOT_A_PATH or not _pathlike(action):
                    continue
                found[(surface, " ".join(path), flag)] = has_rf
    return found


@pytest.fixture(scope="module")
def inventory() -> dict[Key, bool]:
    return _inventory()


@pytest.mark.unit
class TestInventory:
    """Spec P2-G14 item 10: every path flag is mapped or explicitly local-only."""

    def test_the_tables_do_not_overlap(self) -> None:
        seen: dict[Key, str] = {}
        for name, table in TABLES.items():
            for key in table:
                assert key not in seen, f"{key} is in both {seen[key]} and {name}"
                seen[key] = name

    def test_every_path_flag_is_classified(self, inventory) -> None:
        classified = set().union(*TABLES.values())
        unclassified = sorted(k for k in inventory if k not in classified)
        assert unclassified == [], (
            "new path-like flags: map them to a --run-folder relpath or list them "
            f"as public-only/control/not-a-path: {unclassified}")

    def test_no_table_entry_is_stale(self, inventory) -> None:
        stale = sorted(k for t in TABLES.values() for k in t if k not in inventory)
        assert stale == []

    def test_every_mapped_flag_has_a_run_folder(self, inventory) -> None:
        from starboard_skills.helpers import __main__ as helper_main

        missing = [k for k in RUN_RELPATH if not inventory[k] and k != ("helper", "", "--out")]
        assert missing == []
        # The helper root --out is mapped through the pre-argparse --run-folder of
        # the fetch domains; the out-owning domains own their --out (mapped above).
        assert ("helper", "", "--out") in inventory
        assert helper_main._FETCH_DOMAINS.isdisjoint(helper_main._OUT_OWNING_DOMAINS)
        domains = {path for (s, path, _f) in inventory if s == "helper" and path}
        roots = {p.split()[0] for p in domains}
        assert roots <= set(helper_main._FETCH_DOMAINS) | set(
            helper_main._OUT_OWNING_DOMAINS) | {"run", "engagement"}

    def test_every_public_argparse_module_is_walked(self) -> None:
        roots = [REPO / "packages" / p for p in ("starboard", "starboard-core",
                                                 "starboard-skills")]
        builders = sorted(
            str(f.relative_to(REPO))
            for root in roots for f in root.rglob("*.py")
            if "/tests/" not in str(f) and "ArgumentParser(" in f.read_text("utf-8")
        )
        assert builders == sorted(PARSER_MODULES), (
            "a module builds an ArgumentParser this test does not walk")


# --------------------------------------------------------------------------- #
# W30: local customer-file intake on an overlay install
# --------------------------------------------------------------------------- #
_SPARK_APP = {
    "metadata": {
        "application_info": {"id": "app-1", "name": "App", "timestamp_start_ms": 1,
                             "timestamp_end_ms": 2, "runtime_sec": 1,
                             "spark_version": "3.4.0"},
        "existsSQL": False, "existsExecutors": False,
    },
    "jobData": [], "stageData": [], "taskData": [], "accumData": [],
}
_HISTORY = [{"statement_id": "s1", "warehouse_id": "wh1", "statement_type": "SELECT",
             "total_duration_ms": 1200, "waiting_in_queue_ms": 100, "read_bytes": 1000,
             "written_bytes": 0, "start_time": "2026-01-01T10:00:00Z",
             "executed_by": "alice"}]


def _intake(tmp_path: Path) -> list[tuple[str, Callable[..., Any], list[str]]]:
    d = tmp_path / "customer-files"
    d.mkdir(exist_ok=True)
    (d / "schema.json").write_text(json.dumps(
        {"table_name": "main.sales.orders", "columns": [{"name": "id", "type": "bigint"}]}))
    (d / "eventlog.json").write_text(json.dumps(_SPARK_APP))
    (d / "history.json").write_text(json.dumps(_HISTORY))
    (d / "driver.log").write_text("java.lang.OutOfMemoryError: Java heap space\n")
    return [
        ("uc analyze --input", uc_cli.main, ["analyze", "--input", str(d / "schema.json")]),
        ("sparklog parse --input", sparklog_cli.main,
         ["parse", "--input", str(d / "eventlog.json")]),
        ("warehouse analyze --history", warehouse_cli.main,
         ["analyze", "--history", str(d / "history.json")]),
        ("diagnostic extract-evidence --text", diagnostic_cli.main,
         ["extract-evidence", "--text", str(d / "driver.log")]),
        ("diagnostic rca --text", diagnostic_cli.main, ["rca", "--text", str(d / "driver.log")]),
        ("diagnostic triage-exit --text", diagnostic_cli.main,
         ["triage-exit", "--exit-code", "137", "--text", str(d / "driver.log")]),
    ]


_INTAKE_IDS = [  # the names returned by _intake(), in order
    "uc analyze --input", "sparklog parse --input", "warehouse analyze --history",
    "diagnostic extract-evidence --text", "diagnostic rca --text",
    "diagnostic triage-exit --text"]


@pytest.mark.unit
class TestLocalFileIntake:
    """W30: refused on overlay installs; accepted on a public install."""

    @pytest.mark.parametrize("index", range(len(_INTAKE_IDS)), ids=_INTAKE_IDS)
    def test_public_install_accepts_a_local_file(self, index, capsys, tmp_path, public) -> None:
        _name, fn, argv = _intake(tmp_path)[index]
        code, env, raw = _call(fn, argv, capsys)
        assert code == 0 and env["ok"] is True, raw  # the inputs are valid

    @pytest.mark.parametrize("index", range(len(_INTAKE_IDS)), ids=_INTAKE_IDS)
    def test_overlay_install_refuses_a_local_customer_file(self, index, capsys, tmp_path) -> None:
        _name, fn, argv = _intake(tmp_path)[index]
        code, env, raw = _call(fn, argv, capsys)
        assert code == 2 and env.get("ok") is False, raw
        assert env["error"].startswith("LOCAL_FILE_INTAKE_REFUSED:"), raw
        assert LOCAL_FILE_INTAKE_GUIDANCE in env["error"], raw


@pytest.mark.unit
class TestMappedFlagsRefuseLocalPaths:
    """A mapped flag given an absolute local path on a covered run is refused."""

    @pytest.mark.parametrize("argv", [
        ["charts", "render", "--kind", "spend-by-product", "--data", "{abs}/d.json",
         "--out", "deliverables/charts/c.png"],
        ["charts", "render", "--kind", "spend-by-product", "--data", "charts/d.json",
         "--out", "{abs}/c.png"],
        ["run", "check", "--out", "{abs}/run-check.json"],
    ], ids=["charts --data", "charts --out", "run check --out"])
    def test_absolute_local_path_with_run_folder_exits_2(
        self, argv, capsys, tmp_path, store
    ) -> None:
        _, route = routed(capsys)
        rf = route["run_folder_id"]
        objects = store.object_count
        code, env, raw = helper(capsys, *[a.format(abs=tmp_path) for a in argv],
                                "--run-folder", rf)
        assert code == 2 and env.get("ok") is False, raw
        assert "LOCAL_STORAGE_REFUSED" in raw or "local path" in raw, raw
        assert store.object_count == objects
        assert list(tmp_path.glob("*.json")) == [] and list(tmp_path.glob("*.png")) == []
