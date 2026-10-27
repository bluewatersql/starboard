"""P2-G14 exit test 10b - writer coverage beyond the argparse inventory.

Test 10 classifies every *public* argparse path flag. This file covers the rest:

* The internal-only argparse writers (``starboard_internal.sanitize`` and
  ``starboard_internal.ticket``). Test 10 does not walk them because they are not
  public. Sanitize on a covered run reads and writes through the run sink; any local
  output is refused. Ticket only reads, so it has no output flag at all.
* The non-argparse writers from the spec's writer table, as a checklist: W6
  (discovery synthesis report), W7/W8 (query and response caches), W15 (SDK
  session store), W27/W28 (log-parser temp copy and exports) and W29 (discovery
  output helpers). Each row maps to at least one behavioural test below, and
  ``test_checklist_rows_map_to_tests`` keeps that map honest.

A writer that is not covered yet would be marked ``xfail(strict=True)`` with a
reason, so the gap is visible and fixing it fails the test until the marker is
removed. Every row is currently covered.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement.write_guard import (
    LocalWriteRefused,
    active,
    default_policy,
    guarded,
)

from ..conftest import make_drive_run
from ._support import (
    GatherEngine,
    _last_json,
    clean,
    drive_tree,
    routed,
    run_sink,
    starboard,
)

pytestmark = pytest.mark.unit

DRAFT = "# Report\n\nSpend rose 12%. [internal: triage-notes]\n"

#: Writer-table row -> the tests in this module that prove its coverage.
CHECKLIST: dict[str, tuple[str, ...]] = {
    "W6": (
        "test_w6_covered_discover_hands_the_engine_the_run_sink",
        "test_w6_report_writes_through_the_sink_only",
    ),
    "W7": ("test_w7_discovery_query_cache_is_in_memory",),
    "W8": (
        "test_w8_redis_forced_off_on_covered_discover",
        "test_w8_cache_store_is_memory_after_redis_forced_off",
    ),
    "W15": ("test_w15_sdk_sessions_stay_in_memory_on_overlay",),
    "W27": ("test_w27_dbfs_loader_parses_in_memory_under_the_guard",),
    "W28": ("test_w28_exports_refused_locally_bytes_go_through_the_sink",),
    "W29": (
        "test_w29_async_file_writers_refused_under_the_guard",
        "test_w29_reporting_writers_refused_under_the_guard",
        "test_w29_output_manager_refused_under_the_guard",
    ),
}


def _run_folder(store: Any) -> str:
    """A committed Drive run folder (descriptor written) in the phase-2 store."""
    return make_drive_run(store=store).folder_id


def _run_main(
    fn: Any, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, Any], str, str]:
    """Run an ``int``-returning ``main(argv)``: ``(exit, envelope, stdout, stderr)``."""
    try:
        code = fn(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    out = capsys.readouterr()
    return int(code or 0), _last_json(out.out), out.out, out.err


# --------------------------------------------------------------------------- #
# starboard_internal.sanitize
# --------------------------------------------------------------------------- #
class TestSanitizeWriter:
    """``python -m starboard_internal.sanitize``: sink on a run, refused locally."""

    @pytest.fixture
    def sanitize(self) -> Any:
        return pytest.importorskip("starboard_internal.sanitize")

    def test_run_folder_reads_and_writes_through_the_sink(
        self, sanitize, capsys, sandbox, store
    ) -> None:
        from starboard_internal._sanitize import strip_internal_metadata

        rf = _run_folder(store)
        run_sink(store, rf).put_text("deliverables/report.md", DRAFT, "text/markdown")
        before = sandbox.snapshot()

        code, env, raw, _err = _run_main(
            sanitize.main, ["--run-folder", rf, "--in", "deliverables/report.md"], capsys
        )

        assert code == 0, raw
        env = clean(sandbox, before, raw)
        assert env["ok"] is True and env["run_folder_id"] == rf
        assert env["summary"]["output"] == "deliverables/report.clean.md"
        tree = drive_tree(store, rf)
        assert tree["deliverables/report.clean.md"].decode() == strip_internal_metadata(
            DRAFT
        ).text
        assert DRAFT not in raw  # the text goes to Drive, never to stdout

    def test_local_out_on_a_run_is_refused(
        self, sanitize, capsys, sandbox, store, tmp_path
    ) -> None:
        rf = _run_folder(store)
        run_sink(store, rf).put_text("deliverables/report.md", DRAFT, "text/markdown")
        objects = store.object_count
        before = sandbox.snapshot()
        out = tmp_path / "cwd" / "clean.md"

        code, env, raw, err = _run_main(
            sanitize.main,
            ["--run-folder", rf, "--in", "deliverables/report.md", "--out", str(out)],
            capsys,
        )

        assert code == 2, raw
        assert env["ok"] is False
        assert env["errors"][0]["code"] == "LOCAL_STORAGE_REFUSED", raw
        assert "LOCAL_STORAGE_REFUSED" in err
        assert not out.exists()
        assert store.object_count == objects
        assert sandbox.snapshot() == before

    def test_local_run_without_run_folder_is_refused_on_overlay(
        self, sanitize, capsys, sandbox, tmp_path
    ) -> None:
        draft = tmp_path / "cwd" / "draft.md"
        draft.write_text(DRAFT, encoding="utf-8")
        out = tmp_path / "cwd" / "clean.md"
        before = sandbox.snapshot()

        code, _env, raw, err = _run_main(
            sanitize.main, ["--in", str(draft), "--out", str(out)], capsys
        )

        assert code == 2, raw
        assert "LOCAL_STORAGE_REFUSED" in err
        assert not out.exists()
        assert sandbox.snapshot() == before


# --------------------------------------------------------------------------- #
# starboard_internal.ticket
# --------------------------------------------------------------------------- #
class TestTicketWriter:
    """``python -m starboard_internal.ticket`` reads only: no output flag, no writes."""

    @pytest.fixture
    def ticket(self) -> Any:
        return pytest.importorskip("starboard_internal.ticket")

    def test_parser_has_no_output_flag(self, ticket) -> None:
        from .test_exit_10_writer_inventory import _capture

        parser = _capture(ticket.main)
        flags: set[str] = set()
        stack = [parser]
        while stack:
            p = stack.pop()
            for action in p._actions:
                flags.update(action.option_strings)
                choices = getattr(action, "choices", None)
                if isinstance(choices, dict):
                    stack.extend(choices.values())
        outputs = {f for f in flags if any(w in f for w in ("out", "dir", "save", "write"))}
        assert outputs == set(), outputs

    @pytest.mark.parametrize("argv", [
        ["parse", "see ASQ-123456789"],
        ["soql", "--key", "AR-123456789"],
        ["validate", "--key", "AR-123456789", "--input", "ASQ-123456789",
         "--records-json", "-"],
    ], ids=["parse", "soql", "validate"])
    def test_commands_write_nothing_under_the_guard(
        self, ticket, argv, capsys, sandbox, monkeypatch
    ) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"records": []})))
        before = sandbox.snapshot()

        with guarded(default_policy()):
            code, _env, raw, _err = _run_main(ticket.main, argv, capsys)

        assert code in (0, 2), raw
        assert sandbox.snapshot() == before


# --------------------------------------------------------------------------- #
# W6 - discovery synthesis report
# --------------------------------------------------------------------------- #
def test_w6_covered_discover_hands_the_engine_the_run_sink(
    capsys, monkeypatch, sandbox
) -> None:
    seen: list[Any] = []

    class Capturing(GatherEngine):
        def __init__(self, sql_executor: Any, llm_client: Any, config: Any, **kw: Any) -> None:
            super().__init__(sql_executor, llm_client, config, **kw)
            seen.append(config)

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", Capturing)
    _, route = routed(capsys)
    rf = route["run_folder_id"]
    before = sandbox.snapshot()

    starboard(capsys, "--discover", "--profile", "acme", "--run-folder", rf, "--json")

    assert seen, "the discovery engine was never built"
    assert seen[-1].sink is not None
    assert seen[-1].data_only is False
    assert sandbox.snapshot() == before
    assert not (Path.cwd() / "discovery_output").exists()


def test_w6_report_writes_through_the_sink_only(capsys, sandbox, store) -> None:
    from starboard.discovery.output.formatters import OutputFormatter
    from starboard_core.domain.models.discovery.report import (
        DiscoveryReport,
        ExecutiveSummary,
        ReportMetadata,
    )

    rf = _run_folder(store)
    report = DiscoveryReport(
        executive_summary=ExecutiveSummary(),
        domain_analyses=[],
        top_priorities=[],
        source_proofs=[],
        metadata=ReportMetadata(),
    )
    before = sandbox.snapshot()

    with guarded(default_policy()):
        written = OutputFormatter().write_to_sink(report, run_sink(store, rf))

    assert sandbox.snapshot() == before
    tree = drive_tree(store, rf)
    assert written
    assert {"analysis/discovery-report/report.md",
            "analysis/discovery-report/report.json"} <= set(tree)


# --------------------------------------------------------------------------- #
# W7 / W8 - caches
# --------------------------------------------------------------------------- #
def test_w7_discovery_query_cache_is_in_memory() -> None:
    from starboard.adapters.state.inmemory.cache_store import InMemoryCacheStore
    from starboard.discovery.executor import QueryPackExecutor

    executor = QueryPackExecutor(sql_executor=object())

    assert executor._cache is not None
    assert isinstance(executor._cache._store, InMemoryCacheStore)


def test_w8_redis_forced_off_on_covered_discover(capsys, monkeypatch, sandbox) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://cache.example:6379/0")
    _, route = routed(capsys)
    rf = route["run_folder_id"]
    before = sandbox.snapshot()

    code, _env, raw = starboard(capsys, "--discover", "--profile", "acme", "--run-folder", rf,
                                "--data-only", "--json", "--out-dir", "discovery")

    assert code == 0, raw
    assert "REDIS_URL" not in os.environ
    assert sandbox.snapshot() == before


def test_w8_cache_store_is_memory_after_redis_forced_off(capsys) -> None:
    from starboard.adapters.state.inmemory.cache_store import InMemoryCacheStore
    from starboard.cli.cli.main import _force_redis_off
    from starboard.infra.core.state_factory import create_cache_store

    config: Any = SimpleNamespace(redis_url="redis://cache.example:6379/0")
    _force_redis_off(config)

    assert config.redis_url is None
    assert isinstance(create_cache_store(config), InMemoryCacheStore)
    assert "Redis is disabled" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# W15 - SDK client session store
# --------------------------------------------------------------------------- #
def test_w15_sdk_sessions_stay_in_memory_on_overlay(monkeypatch, sandbox) -> None:
    from starboard.sdk.client import StarboardClient

    config = SimpleNamespace(databricks_host="https://h", databricks_token="t")
    monkeypatch.setattr("starboard.bootstrap.get_config", lambda: config)

    async def create(*_a: object, **_k: object) -> tuple[object, None]:
        return object(), None

    monkeypatch.setattr("starboard.cli.cli.main.create_agent_manager", create)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    before = sandbox.snapshot()

    async def db_path() -> str:
        client: Any = await StarboardClient.from_env(session_db="~/custom/sessions.db")
        try:
            return str(client._session_mgr._db_path)
        finally:
            await client._session_mgr.close()

    assert asyncio.run(db_path()) == ":memory:"
    assert sandbox.snapshot() == before


# --------------------------------------------------------------------------- #
# W27 / W28 - log parser
# --------------------------------------------------------------------------- #
class _FakeDbfs:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def dbfs_path_exists(self, dbfs_path: str) -> bool:
        return True

    def list_dbfs_files(self, dbfs_path: str, recursive: bool = True) -> list[dict[str, Any]]:
        return [{"path": p, "is_dir": False} for p in self.files]

    def read_dbfs_chunk(self, dbfs_path: str, offset: int, length: int) -> bytes:
        return self.files[dbfs_path][offset : offset + length]


@pytest.mark.parametrize("streaming", [True, False])
def test_w27_dbfs_loader_parses_in_memory_under_the_guard(
    sandbox, tmp_path, streaming
) -> None:
    from starboard_core.log_parser.loaders.dbfs import DBFSFileLinesDataLoader

    temp_dir = tmp_path / "tmp" / "never-created"
    before = sandbox.snapshot()

    with guarded(default_policy()):
        loader = DBFSFileLinesDataLoader(
            dbfs_client=_FakeDbfs({"/logs/a.json": b'{"a": 1}\n{"b": 2}\n'}),
            save_to_disk=True,
            temp_dir=temp_dir,
            streaming=streaming,
        )
        lines = [list(stream) for _path, stream in loader.load_item("dbfs:/logs")]

    assert len(lines) == 1 and len(lines[0]) == 2
    assert not temp_dir.exists()
    assert sandbox.snapshot() == before


def test_w28_exports_refused_locally_bytes_go_through_the_sink(
    capsys, sandbox, store, tmp_path
) -> None:
    import polars as pl
    from starboard_core.log_parser.domain.models.application import SparkApplication
    from starboard_core.log_parser.domain.models.metadata import (
        SparkApplicationInfo,
        SparkApplicationMetadata,
    )

    info = SparkApplicationInfo(
        timestamp_start_ms=1700000000000, timestamp_end_ms=1700001000000,
        runtime_sec=1000.0, name="MyApp", id="app-123", spark_version="3.5.0",
        emr_version_tag="", cloud_platform="standalone", cloud_provider="on-prem",
        cluster_id="",
    )
    app = SparkApplication(
        metadata=SparkApplicationMetadata(
            application_info=info, spark_params={}, exists_sql=False,
            exists_executors=False,
        ),
        job_data=pl.DataFrame({"job_id": [0]}),
        stage_data=pl.DataFrame({"stage_id": [0]}),
        task_data=pl.DataFrame({"task_id": [0]}),
        accum_data=pl.DataFrame({"accum_id": [0]}),
        sql_data=None,
        executor_data=None,
    )
    rf = _run_folder(store)
    sink = run_sink(store, rf)
    before = sandbox.snapshot()

    with guarded(default_policy()):
        with pytest.raises(LocalWriteRefused):
            app.save(str(tmp_path / "cwd" / "app"))
        sink.put_bytes("analysis/spark/app.json.gz", app.to_json_bytes(compress=True),
                       "application/gzip")

    assert sandbox.snapshot() == before
    assert drive_tree(store, rf)["analysis/spark/app.json.gz"]


# --------------------------------------------------------------------------- #
# W29 - discovery output helpers
# --------------------------------------------------------------------------- #
def _refused(coro: Any) -> None:
    with guarded(default_policy()), pytest.raises(LocalWriteRefused):
        asyncio.run(coro)
    assert not active()


@pytest.mark.parametrize("writer", ["write_text", "write_json"])
def test_w29_async_file_writers_refused_under_the_guard(sandbox, tmp_path, writer) -> None:
    from starboard.infra.io import async_file

    target = tmp_path / "cwd" / "out.txt"
    before = sandbox.snapshot()
    payload: Any = "x" if writer == "write_text" else {"a": 1}

    _refused(getattr(async_file, writer)(target, payload))

    assert not target.exists()
    assert sandbox.snapshot() == before


@pytest.mark.parametrize("writer", ["write_text_file", "write_json_file"])
def test_w29_reporting_writers_refused_under_the_guard(sandbox, tmp_path, writer) -> None:
    from starboard.infra.observability import reporting

    target = tmp_path / "cwd" / "out.txt"
    before = sandbox.snapshot()
    payload: Any = "x" if writer == "write_text_file" else {"a": 1}

    _refused(getattr(reporting, writer)(target, payload))

    assert not target.exists()
    assert sandbox.snapshot() == before


def test_w29_output_manager_refused_under_the_guard(sandbox, tmp_path) -> None:
    from starboard.infra.observability.output import OutputConfig, OutputManager

    out_dir = tmp_path / "cwd" / "out"
    manager = OutputManager(OutputConfig(output_dir=str(out_dir), formats=["markdown", "json"]))
    before = sandbox.snapshot()

    _refused(manager.save_results({"recommendations": {}}, {}))

    assert not out_dir.exists()
    assert sandbox.snapshot() == before


# --------------------------------------------------------------------------- #
# Checklist integrity
# --------------------------------------------------------------------------- #
def test_checklist_rows_map_to_tests() -> None:
    names = set(globals())
    assert set(CHECKLIST) == {"W6", "W7", "W8", "W15", "W27", "W28", "W29"}
    for row, tests in CHECKLIST.items():
        assert tests, row
        missing = [t for t in tests if t not in names]
        assert missing == [], f"{row}: {missing}"
