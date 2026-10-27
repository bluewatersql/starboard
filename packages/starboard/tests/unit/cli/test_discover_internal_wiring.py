# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard --discover`` is wired to the deterministic discovery pipeline and
honors the dual-source seam (regression for the "internal source unreachable"
gap — see the internal-mirror-source work).

Proves, hermetically (no live warehouse):

1. **Dispatch** — ``--discover`` routes to :func:`run_discovery_mode` (the
   deterministic pipeline), NOT the LLM goal-agent.
2. **Internal source reachable** — ``--internal-account`` threads through to an
   ``EngineConfig(source="internal", internal_account=…)`` and the run builds NO
   customer workspace client (internal runs never touch a customer workspace).
3. **External default** — with no ``--internal-*`` flag the source is
   ``"external"`` and the customer client IS constructed (byte-identical to
   before).
4. **JSON envelope** — ``--discover --json`` emits the deterministic envelope
   reporting the source and scope.
"""

from __future__ import annotations

import argparse
import json

import pytest
from rich.console import Console
from starboard.cli.cli import main as cli_main
from starboard.discovery.engine import EngineResult


class _FakeEngine:
    """Captures the ``EngineConfig`` + base executor the CLI wires up."""

    captured: dict = {}

    def __init__(self, sql_executor, llm_client, config) -> None:  # noqa: ANN001
        _FakeEngine.captured = {"config": config, "sql_executor": sql_executor}

    async def run(self, on_progress=None):  # noqa: ANN001, ANN201
        return EngineResult(trace_id="test-trace")


def _discovery_args(**overrides) -> argparse.Namespace:
    base = {
        "discover": True,
        "data_only": True,
        "no_cache": True,
        "json": False,
        "lookback_days": 30,
        "discovery_domains": None,
        "internal_account": None,
        "internal_workspace_id": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _config():
    from unittest.mock import MagicMock

    config = MagicMock()
    config.discovery_max_parallelism = 4
    config.discovery_output_dir = "/tmp/starboard-test-discovery"
    config.discovery_llm_model = None
    config.discovery_llm_temperature = 0.3
    config.discovery_min_dbu_threshold = 0
    config.discovery_internal_source_account = None
    config.discovery_internal_source_workspace_id = None
    return config


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discover_internal_account_selects_internal_source(monkeypatch):
    called = {"client": 0}

    def _client_factory(*a, **k):  # noqa: ANN002, ANN003
        called["client"] += 1
        raise AssertionError("internal run must NOT build a customer client")

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _client_factory)

    args = _discovery_args(internal_account="acct-123")
    await cli_main.run_discovery_mode(args, _config(), Console())

    cfg = _FakeEngine.captured["config"]
    assert cfg.source == "internal"
    assert cfg.internal_account == "acct-123"
    # No customer workspace client was constructed …
    assert called["client"] == 0
    # … and the base executor is the internal guard (never a real SQL executor).
    assert type(_FakeEngine.captured["sql_executor"]).__name__ == "_InternalUnusedExecutor"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discover_internal_workspace_selects_internal_source(monkeypatch):
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    args = _discovery_args(internal_workspace_id="1444828305810485")
    await cli_main.run_discovery_mode(args, _config(), Console())

    cfg = _FakeEngine.captured["config"]
    assert cfg.source == "internal"
    assert cfg.internal_workspace_ids == ("1444828305810485",)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discover_external_default_builds_customer_client(monkeypatch):
    from unittest.mock import MagicMock

    built = {"client": 0}

    class _FakeClient:
        def __init__(self, *a, **k) -> None:  # noqa: ANN002, ANN003
            built["client"] += 1

        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, *a):  # noqa: ANN002, ANN204
            return False

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", MagicMock())

    args = _discovery_args()  # no internal flags
    await cli_main.run_discovery_mode(args, _config(), Console())

    cfg = _FakeEngine.captured["config"]
    assert cfg.source == "external"
    assert built["client"] == 1  # external path DOES build the customer client


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discover_json_envelope_reports_source_and_scope(monkeypatch, capsys):
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    args = _discovery_args(internal_account="acct-xyz", json=True)
    await cli_main.run_discovery_mode(args, _config(), Console())

    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is True
    assert envelope["domain"] == "discovery"
    assert envelope["data"]["source"] == "internal"
    assert envelope["data"]["scope"]["account"] == "acct-xyz"
    # Lookback window is reported in the envelope (analyst can confirm from JSON).
    assert envelope["data"]["lookback_days"] == 30


@pytest.mark.unit
def test_discovery_envelope_classifies_skipped_vs_failed():
    """A coverage-skip (unavailable on source) is reported as ``skipped``, NOT
    ``failed`` — succeeded / skipped / failed are three distinct outcomes.
    Also validates D5: pack_count, limit_reached_ids, and top-level skipped
    are present in the full envelope."""
    import polars as pl
    from starboard.cli.cli.main import _discovery_json_envelope
    from starboard_core.domain.models.discovery.query import PackResult, QueryResult

    ok = QueryResult(
        query_id="C-B01", domain="billing", data=pl.DataFrame({"x": [1]}), row_count=1
    )
    skip = QueryResult(
        query_id="N-L01",
        domain="governance",
        data=None,
        error="unavailable on internal source: table X not mirrored",
        skipped=True,
    )
    fail = QueryResult(query_id="Q-ERR", domain="billing", data=None, error="boom")
    pack = PackResult(pack_id="p", domain="billing", results=(ok, skip, fail))
    result = EngineResult(trace_id="t", pack_results=[pack])

    env = _discovery_json_envelope(result, "internal", None, ("111",))

    assert env["data"]["counts"] == {
        "total": 3,
        "succeeded": 1,
        "skipped": 1,
        "failed": 1,
        "filtered": 0,
    }
    # Converged shape: rows are grouped by pack under data.packs[].results[]
    # (identical to `python -m starboard_x.discovery`), so a host has ONE parse
    # path for both entry points. The internal-only three-state `status` per
    # query is layered on top so a coverage skip stays distinct from a failure.
    assert env["data"]["pack_count"] == 1
    all_q = [q for pk in env["data"]["packs"] for q in pk["results"]]
    by_id = {q["query_id"]: q["status"] for q in all_q}
    assert by_id == {"C-B01": "succeeded", "N-L01": "skipped", "Q-ERR": "failed"}
    # Succeeded queries carry their actual rows so the host can analyze the raw
    # data — --data-only --json returns the data itself, not just a summary.
    c_b01 = next(q for q in all_q if q["query_id"] == "C-B01")
    assert c_b01["rows"] == [{"x": 1}]
    assert c_b01["row_count"] == 1
    assert c_b01["status"] == "succeeded"

    # D5: top-level limit_reached_ids and skipped must be in the full envelope.
    assert "limit_reached_ids" in env["data"]
    assert env["data"]["limit_reached_ids"] == []  # none hit their cap
    assert "skipped" in env["data"]
    skipped_ids = {e.get("query_id") for e in env["data"]["skipped"]}
    assert "N-L01" in skipped_ids


@pytest.mark.unit
def test_discovery_envelope_has_coverage_and_coverage_caveats():
    """W32: envelope carries per-pack coverage summary and coverage_caveats list."""
    import polars as pl
    from starboard.cli.cli.main import _discovery_json_envelope
    from starboard_core.domain.models.discovery.query import PackResult, QueryResult

    ok = QueryResult(
        query_id="C-B01", domain="billing", data=pl.DataFrame({"x": [1]}), row_count=1
    )
    skip = QueryResult(
        query_id="N-L01",
        domain="governance",
        data=None,
        error="unavailable on internal source: table X not mirrored",
        skipped=True,
    )
    fail = QueryResult(query_id="Q-ERR", domain="billing", data=None, error="boom")
    pack = PackResult(pack_id="billing", domain="billing", results=(ok, skip, fail))
    result = EngineResult(trace_id="t", pack_results=[pack])

    env = _discovery_json_envelope(result, "internal", None, ("111",))

    # Per-pack coverage summary.
    coverage = env["data"]["coverage"]
    assert "billing" in coverage
    billing = coverage["billing"]
    assert billing["succeeded"] == 1
    assert billing["skipped"] == 1
    assert billing["failed"] == 1
    assert "unavailable on internal source: table X not mirrored" in billing["skipped_reasons"]

    # coverage_caveats defaults to empty list (no source_obj provided).
    assert env["data"]["coverage_caveats"] == []


@pytest.mark.unit
def test_discovery_envelope_coverage_caveats_from_source_obj():
    """W32: coverage_caveats are taken from source_obj.coverage_caveats."""

    from starboard.cli.cli.main import _discovery_json_envelope

    class _FakeSrc:
        coverage_caveats = ("identity columns null in mirror", "statement_text null")

    result = EngineResult(trace_id="t")
    env = _discovery_json_envelope(
        result, "internal", None, (), source_obj=_FakeSrc()
    )

    assert env["data"]["coverage_caveats"] == [
        "identity columns null in mirror",
        "statement_text null",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_main_routes_discover_to_pipeline_not_agent(monkeypatch):
    """The dead-code regression: ``--discover`` must call run_discovery_mode and
    NOT fall through to the goal-agent path."""
    from unittest.mock import AsyncMock

    ran = AsyncMock()
    monkeypatch.setattr(cli_main, "run_discovery_mode", ran)

    cfg = _config()
    cfg.offline_mode = False
    cfg._auth_resolvable = lambda: True
    cfg.llm_api_key = None
    monkeypatch.setattr(cli_main, "merge_env_config", lambda *a, **k: cfg)
    # Fail loudly if the agent path is taken instead of the discovery pipeline.
    monkeypatch.setattr(
        cli_main,
        "create_agent_manager",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("--discover must not reach the agent path")
        ),
    )

    args = _discovery_args(
        config=None,
        goal=None,
        input_file=None,
        quiet=True,
        json=False,
        no_color=True,
        debug=False,
        log_level="ERROR",
        log_file=None,
    )
    await cli_main.async_main(args)
    ran.assert_awaited_once()


# ---------------------------------------------------------------------------
# D2: connection error gives a clean one-line message (no traceback/locals)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connection_error_gives_clean_one_line_error(monkeypatch, capsys):
    """D2: a ConnectionError during engine init (e.g. InternalPreflightError from
    _preflight_once) must exit with a clean one-line message to stderr and no
    Python traceback or locals in either stream."""
    from rich.console import Console

    def _bad_engine(*a, **k):  # noqa: ANN002, ANN003
        raise ConnectionError(
            "cannot reach fleet-endpoint.databricks.com — check network / VPN"
        )

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _bad_engine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    args = _discovery_args(internal_account="acct-fail")
    with pytest.raises(SystemExit) as exc_info:
        await cli_main.run_discovery_mode(args, _config(), Console())

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    # No Python traceback in either stream
    for stream_text in (captured.out, captured.err):
        assert "Traceback" not in stream_text, "traceback leaked to output"
        assert "locals" not in stream_text.lower(), "locals leaked to output"
    # Error message must appear somewhere on stderr
    assert "cannot reach" in captured.err or "Connection" in captured.err


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connection_error_json_mode_emits_error_envelope(monkeypatch, capsys):
    """D2: in --json mode a ConnectionError during engine init must emit a JSON
    error envelope on stdout (not a traceback) and exit non-zero."""
    from rich.console import Console

    def _bad_engine(*a, **k):  # noqa: ANN002, ANN003
        raise ConnectionError("fleet host unreachable")

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _bad_engine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    args = _discovery_args(internal_account="acct-fail", json=True)
    with pytest.raises(SystemExit) as exc_info:
        await cli_main.run_discovery_mode(args, _config(), Console())

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert "error" in payload
    assert "Traceback" not in captured.out


# ---------------------------------------------------------------------------
# D3: in --json mode stdout is exactly one JSON document
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_json_mode_stdout_is_exactly_one_json_document(monkeypatch, capsys):
    """D3: --json mode must emit ONLY the envelope JSON on stdout; all
    banner/progress output must go to stderr so stdout is always parseable."""
    from rich.console import Console

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    args = _discovery_args(internal_account="acct-d3", json=True)
    await cli_main.run_discovery_mode(args, _config(), Console())

    out, err = capsys.readouterr()
    # stdout must be exactly one valid JSON document — json.loads is strict:
    # it rejects trailing non-whitespace, so a successful parse proves stdout
    # is purely the envelope (no banner lines leaked before or after it).
    envelope = json.loads(out)
    assert envelope["ok"] is True
    # The single JSON object must start and end cleanly
    out_stripped = out.strip()
    assert out_stripped.startswith("{"), "stdout must start with JSON object"
    assert out_stripped.endswith("}"), "stdout must end with JSON object"
    # Banner must NOT be on stdout
    assert "Starboard" not in out
    # Something must have gone to stderr (banner/progress)
    assert len(err) > 0, "expected banner/progress on stderr"


# ---------------------------------------------------------------------------
# D4: per-query liveness progress events
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_query_progress_event_fires_every_10_queries():
    """D4: engine emits query_progress events every 10 completed queries."""
    import asyncio

    import polars as pl
    from starboard.discovery.engine import DiscoveryEngine, EngineConfig
    from starboard_core.domain.models.discovery.query import (
        QueryPack,
        SystemQuery,
    )

    class _FastExecutor:
        async def execute_sql(self, sql: str) -> pl.DataFrame:
            if "usage_unit" in sql:
                return pl.DataFrame(
                    {"billing_origin_product": ["JOBS"], "total_usage": [1000.0]}
                )
            return pl.DataFrame()

    queries = tuple(
        SystemQuery(
            query_id=f"T-{i:02d}",
            name=f"q{i}",
            description="t",
            sql_template="SELECT 1",
            required_tables=("system.billing.usage",),
            domain="jobs",
        )
        for i in range(20)
    )
    jobs_pack = QueryPack(
        pack_id="jobs",
        domain="jobs",
        name="Jobs",
        description="test",
        queries=queries,
        gating_products=frozenset({"JOBS"}),
    )
    audit_pack = QueryPack(
        pack_id="audit",
        domain="audit",
        name="Audit",
        description="audit",
        queries=(
            SystemQuery(
                query_id="P-AUDIT01",
                name="audit",
                description="audit",
                sql_template=(
                    "SELECT billing_origin_product, "
                    "sum(usage_quantity) as total_usage, usage_unit "
                    "FROM system.billing.usage "
                    "GROUP BY billing_origin_product, usage_unit"
                ),
                required_tables=("system.billing.usage",),
                domain="audit",
            ),
        ),
    )

    class _Reg:
        _registered = {"audit", "jobs"}

        @property
        def all_packs(self):
            return [audit_pack, jobs_pack]

        def get_packs_for_products(self, active_products, **_kw):  # noqa: ANN001
            return [jobs_pack]

        def products_without_coverage(
            self, active_products, min_dbu_threshold=0.0
        ):  # noqa: ANN001
            # Mirror the real registry algorithm against this fake's registered
            # packs: JOBS -> ["jobs", ...] (registered) = covered; a product whose
            # mapped pack ids are all unregistered here = uncovered.
            from starboard.discovery.query_packs.registry import (
                PRODUCT_TO_DOMAIN_PACKS,
            )

            if isinstance(active_products, dict):
                names = {
                    p for p, d in active_products.items() if d >= min_dbu_threshold
                }
            else:
                names = set(active_products)
            return sorted(
                p
                for p in names
                if not any(
                    pid in self._registered
                    for pid in PRODUCT_TO_DOMAIN_PACKS.get(p, [])
                )
            )

        def select_for_plan(self, **_kw):  # noqa: ANN001
            from starboard.discovery.query_packs.registry import PlanSelection

            return PlanSelection(domains=[], packs=[])

    engine = DiscoveryEngine(
        sql_executor=_FastExecutor(),
        config=EngineConfig(data_only=True, enable_cache=False),
        query_registry=_Reg(),
    )

    progress_events: list[dict] = []

    def _on_progress(phase: str, info: dict) -> None:
        if phase == "query_progress":
            progress_events.append(info)

    asyncio.run(engine.run(on_progress=_on_progress))

    assert len(progress_events) == 2, f"expected 2 progress events, got {progress_events}"
    assert progress_events[0]["done"] == 10
    assert progress_events[1]["done"] == 20
    assert progress_events[1]["total"] == 20


def _slow_engine(n_queries: int, delay_s: float):
    """Engine with one 'jobs' pack of ``n_queries`` that each sleep ``delay_s``."""
    import asyncio

    import polars as pl
    from starboard.discovery.engine import DiscoveryEngine, EngineConfig
    from starboard_core.domain.models.discovery.query import QueryPack, SystemQuery

    class _SlowExecutor:
        async def execute_sql(self, sql: str) -> pl.DataFrame:
            if "usage_unit" in sql:
                return pl.DataFrame(
                    {"billing_origin_product": ["JOBS"], "total_usage": [1000.0]}
                )
            await asyncio.sleep(delay_s)
            return pl.DataFrame()

    def _q(qid: str, sql: str, domain: str) -> SystemQuery:
        return SystemQuery(
            query_id=qid,
            name=qid,
            description="t",
            sql_template=sql,
            required_tables=("system.billing.usage",),
            domain=domain,
        )

    jobs_pack = QueryPack(
        pack_id="jobs",
        domain="jobs",
        name="Jobs",
        description="test",
        queries=tuple(_q(f"T-{i:02d}", f"SELECT {i}", "jobs") for i in range(n_queries)),
        gating_products=frozenset({"JOBS"}),
    )
    audit_pack = QueryPack(
        pack_id="audit",
        domain="audit",
        name="Audit",
        description="audit",
        queries=(
            _q(
                "P-AUDIT01",
                "SELECT billing_origin_product, sum(usage_quantity) as total_usage, "
                "usage_unit FROM system.billing.usage GROUP BY 1, 3",
                "audit",
            ),
        ),
    )

    class _Reg:
        @property
        def all_packs(self):
            return [audit_pack, jobs_pack]

        def get_packs_for_products(self, active_products, **_kw):  # noqa: ANN001
            return [jobs_pack]

        def products_without_coverage(self, active_products, min_dbu_threshold=0.0):  # noqa: ANN001
            return []

    return DiscoveryEngine(
        sql_executor=_SlowExecutor(),
        config=EngineConfig(data_only=True, enable_cache=False, max_parallelism=2),
        query_registry=_Reg(),
    )


@pytest.mark.unit
def test_heartbeat_fires_without_completions_and_stops_cleanly():
    """Round-3 D3: a timed heartbeat (done/total/in-flight) fires even while no
    query completes, and is cancelled when Phase 2 ends (no beats afterwards)."""
    import asyncio

    engine = _slow_engine(n_queries=2, delay_s=0.35)
    engine._HEARTBEAT_INTERVAL_S = 0.05
    events: list[tuple[str, dict]] = []

    async def _run():
        await engine.run(on_progress=lambda p, i: events.append((p, i)))
        beats_at_end = sum(1 for p, _ in events if p == "query_heartbeat")
        await asyncio.sleep(0.2)  # heartbeat task must be gone
        return beats_at_end

    beats_at_end = asyncio.run(_run())

    beats = [i for p, i in events if p == "query_heartbeat"]
    assert beats, "expected heartbeat events during a quiet Phase 2"
    first = beats[0]
    assert first["done"] == 0 and first["total"] == 2
    assert first["in_flight"] == 2  # both queries executing, none done yet
    assert {"elapsed_s", "packs_done", "packs_total"} <= first.keys()
    assert sum(1 for p, _ in events if p == "query_heartbeat") == beats_at_end
    # Heartbeats only between queries_start and queries_done.
    phases = [p for p, _ in events]
    last_beat = max(i for i, p in enumerate(phases) if p == "query_heartbeat")
    assert phases.index("queries_start") < phases.index("query_heartbeat")
    assert last_beat < phases.index("queries_done")


@pytest.mark.unit
def test_pack_done_event_per_pack():
    """Round-3 D3: one pack_done event per finished pack with its counts."""
    import asyncio

    engine = _slow_engine(n_queries=3, delay_s=0.0)
    events: list[tuple[str, dict]] = []
    asyncio.run(engine.run(on_progress=lambda p, i: events.append((p, i))))

    done = [i for p, i in events if p == "pack_done"]
    assert len(done) == 1
    assert done[0]["pack_id"] == "jobs"
    assert done[0]["succeeded"] == 3
    assert done[0]["failed"] == 0
    assert done[0]["packs_done"] == 1 and done[0]["packs_total"] == 1
    assert engine._pack_executor.in_flight == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_heartbeat_and_pack_done_render_to_stderr_only(monkeypatch, capsys):
    """Round-3 D3: the CLI renders heartbeat/pack lines on stderr; stdout stays JSON."""

    class _ProgressEngine(_FakeEngine):
        async def run(self, on_progress=None):  # noqa: ANN001, ANN201
            on_progress("queries_start", {"pack_count": 1, "query_count": 4})
            on_progress(
                "query_heartbeat",
                {"done": 1, "total": 4, "in_flight": 3, "elapsed_s": 31.0},
            )
            on_progress(
                "pack_done",
                {"pack_id": "jobs", "succeeded": 3, "skipped": 1, "failed": 0,
                 "packs_done": 1, "packs_total": 1, "elapsed_s": 40.0},
            )
            return EngineResult(trace_id="t")

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _ProgressEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )
    args = _discovery_args(internal_account="acct-hb", json=True)
    await cli_main.run_discovery_mode(args, _config(), Console())

    out, err = capsys.readouterr()
    json.loads(out)  # stdout is exactly one JSON document
    assert "still running" not in out and "pack jobs done" not in out
    assert "1/4 queries done, 3 in flight" in err
    assert "pack jobs done (3 ok, 1 skipped)" in err
    assert "1/1 packs" in err


@pytest.mark.unit
def test_heartbeat_lists_in_flight_query_ids_and_pack_done_carries_result():
    """Round-4 B3: the heartbeat names the still-running query ids; pack_done
    carries the finished PackResult so the CLI can persist it immediately."""
    import asyncio

    engine = _slow_engine(n_queries=2, delay_s=0.35)
    engine._HEARTBEAT_INTERVAL_S = 0.05
    events: list[tuple[str, dict]] = []
    asyncio.run(engine.run(on_progress=lambda p, i: events.append((p, i))))

    first = next(i for p, i in events if p == "query_heartbeat")
    assert len(first["in_flight_ids"]) == 2
    assert first["in_flight_more"] == 0
    done = next(i for p, i in events if p == "pack_done")
    assert done["pack_result"].pack_id == "jobs"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_heartbeat_ids_rendered_and_truncated(monkeypatch, capsys):
    class _ProgressEngine(_FakeEngine):
        async def run(self, on_progress=None):  # noqa: ANN001, ANN201
            on_progress(
                "query_heartbeat",
                {"done": 1, "total": 20, "in_flight": 10, "elapsed_s": 31.0,
                 "in_flight_ids": [f"Q-{i}" for i in range(8)], "in_flight_more": 2},
            )
            return EngineResult(trace_id="t")

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _ProgressEngine)
    args = _discovery_args(internal_account="acct-hb", json=True)
    await cli_main.run_discovery_mode(args, _config(), Console())
    _out, err = capsys.readouterr()
    assert "10 in flight: Q-0, Q-1" in err
    assert "Q-7 (+2 more)" in err


@pytest.mark.unit
@pytest.mark.asyncio
async def test_out_dir_writes_raw_pack_and_facts_as_packs_finish(monkeypatch, tmp_path):
    """Round-4 B3: with --out-dir, raw/<pack>.json (and facts.json for the facts
    pack) exist on disk as soon as pack_done fires — before run() returns."""
    import polars as pl
    from starboard_core.domain.models.discovery.query import PackResult, QueryResult

    seen_mid_run: dict[str, bool] = {}
    out_dir = tmp_path / "discovery"

    def _pack(pack_id: str, qid: str) -> PackResult:
        qr = QueryResult(query_id=qid, domain=pack_id, data=pl.DataFrame({"x": [1]}),
                         row_count=1)
        return PackResult(pack_id=pack_id, domain=pack_id, results=(qr,))

    class _ProgressEngine(_FakeEngine):
        async def run(self, on_progress=None):  # noqa: ANN001, ANN201
            jobs, facts = _pack("jobs", "C-J01"), _pack("facts", "F-01")
            on_progress("pack_done", {"pack_id": "jobs", "pack_result": jobs})
            seen_mid_run["raw_jobs"] = (out_dir / "raw" / "jobs.json").exists()
            seen_mid_run["facts_before_facts_pack"] = (out_dir / "facts.json").exists()
            on_progress("pack_done", {"pack_id": "facts", "pack_result": facts})
            seen_mid_run["facts"] = (out_dir / "facts.json").exists()
            seen_mid_run["discovery_json"] = (out_dir / "discovery.json").exists()
            return EngineResult(trace_id="t", pack_results=[jobs, facts])

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _ProgressEngine)
    args = _discovery_args(internal_account="acct-b3", json=True, out_dir=str(out_dir))
    await cli_main.run_discovery_mode(args, _config(), Console())

    assert seen_mid_run == {
        "raw_jobs": True,
        "facts_before_facts_pack": False,
        "facts": True,
        "discovery_json": False,  # final files only at the end
    }
    assert (out_dir / "discovery.json").exists()
    assert (out_dir / "manifest.json").exists()
    assert json.loads((out_dir / "manifest.json").read_text())["facts_path"] == "facts.json"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(("flag", "expected"), [(None, 2), (0, 0), (5, 5), (-1, 0)])
async def test_timeout_retries_flag_reaches_engine_config(monkeypatch, flag, expected):
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    args = _discovery_args(internal_account="acct-tr", timeout_retries=flag)
    await cli_main.run_discovery_mode(args, _config(), Console())
    assert _FakeEngine.captured["config"].timeout_retries == expected


@pytest.mark.unit
def test_timeout_retries_cli_flag_parses():
    assert cli_main.parse_args(["--discover", "--timeout-retries", "1"]).timeout_retries == 1
    assert cli_main.parse_args(["--discover"]).timeout_retries is None


# ---------------------------------------------------------------------------
# D5: full envelope carries limit_reached_ids populated
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discovery_envelope_d5_limit_reached_ids():
    """D5: queries whose row_count == result_limit are listed in limit_reached_ids."""
    import polars as pl
    from starboard.cli.cli.main import _discovery_json_envelope
    from starboard_core.domain.models.discovery.query import PackResult, QueryResult

    capped = QueryResult(
        query_id="C-J01",
        domain="jobs",
        data=pl.DataFrame({"x": list(range(50))}),
        row_count=50,
        result_limit=50,
    )
    ok = QueryResult(
        query_id="C-J02",
        domain="jobs",
        data=pl.DataFrame({"x": [1, 2]}),
        row_count=2,
        result_limit=50,
    )
    pack = PackResult(pack_id="jobs", domain="jobs", results=(capped, ok))
    result = EngineResult(trace_id="t", pack_results=[pack])

    env = _discovery_json_envelope(result, "external", None, None)

    assert "C-J01" in env["data"]["limit_reached_ids"]
    assert "C-J02" not in env["data"]["limit_reached_ids"]


# ---------------------------------------------------------------------------
# D10: products without packs appear in data.skipped
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discovery_envelope_d10_products_without_packs():
    """D10: products detected by P-AUDIT01 with no query pack appear in
    data.skipped with a coverage-gap reason."""
    from starboard.cli.cli.main import _discovery_json_envelope

    result = EngineResult(
        trace_id="t",
        products_without_packs=["AI_GATEWAY", "VECTOR_SEARCH"],
    )
    env = _discovery_json_envelope(result, "internal", None, ("ws1",))

    product_skips = [e for e in env["data"]["skipped"] if "product" in e]
    products_listed = {e["product"] for e in product_skips}
    assert "AI_GATEWAY" in products_listed
    assert "VECTOR_SEARCH" in products_listed
    for entry in product_skips:
        assert "no query pack" in entry["reason"]


@pytest.mark.unit
def test_discovery_engine_records_products_without_packs():
    """D10: EngineResult.products_without_packs is populated for products that
    have no query-pack coverage.

    Coverage is derived from the single routing source of truth
    (PRODUCT_TO_DOMAIN_PACKS ∩ registered packs) via
    ``registry.products_without_coverage`` — filter-independent, NOT from per-pack
    gating_products (issue #17). A product whose mapped pack ids are all
    unregistered is a coverage gap; a product whose mapped pack is registered is
    covered even if a run-level filter would exclude it."""
    import asyncio

    import polars as pl
    from starboard.discovery.engine import DiscoveryEngine, EngineConfig
    from starboard_core.domain.models.discovery.query import (
        QueryPack,
        SystemQuery,
    )

    class _Ex:
        async def execute_sql(self, sql: str) -> pl.DataFrame:
            if "usage_unit" in sql:
                return pl.DataFrame({
                    "billing_origin_product": ["JOBS", "AI_GATEWAY"],
                    "total_usage": [1000.0, 500.0],
                    "usage_unit": ["DBU", "DBU"],
                })
            return pl.DataFrame()

    jobs_pack = QueryPack(
        pack_id="jobs",
        domain="jobs",
        name="Jobs",
        description="jobs",
        queries=(
            SystemQuery(
                query_id="C-J01",
                name="q",
                description="d",
                sql_template="SELECT 1",
                required_tables=("system.billing.usage",),
                domain="jobs",
            ),
        ),
        gating_products=frozenset({"JOBS"}),
    )
    audit_pack = QueryPack(
        pack_id="audit",
        domain="audit",
        name="Audit",
        description="audit",
        queries=(
            SystemQuery(
                query_id="P-AUDIT01",
                name="audit",
                description="audit",
                sql_template=(
                    "SELECT billing_origin_product, "
                    "sum(usage_quantity) as total_usage, usage_unit "
                    "FROM system.billing.usage "
                    "GROUP BY billing_origin_product, usage_unit"
                ),
                required_tables=("system.billing.usage",),
                domain="audit",
            ),
        ),
    )

    class _Reg:
        _registered = {"audit", "jobs"}

        @property
        def all_packs(self):
            return [audit_pack, jobs_pack]

        def get_packs_for_products(self, active_products, **_kw):  # noqa: ANN001
            return [jobs_pack]

        def products_without_coverage(
            self, active_products, min_dbu_threshold=0.0
        ):  # noqa: ANN001
            # Mirror the real registry algorithm against this fake's registered
            # packs: JOBS -> ["jobs", ...] (registered) = covered; a product whose
            # mapped pack ids are all unregistered here = uncovered.
            from starboard.discovery.query_packs.registry import (
                PRODUCT_TO_DOMAIN_PACKS,
            )

            if isinstance(active_products, dict):
                names = {
                    p for p, d in active_products.items() if d >= min_dbu_threshold
                }
            else:
                names = set(active_products)
            return sorted(
                p
                for p in names
                if not any(
                    pid in self._registered
                    for pid in PRODUCT_TO_DOMAIN_PACKS.get(p, [])
                )
            )

        def select_for_plan(self, **_kw):  # noqa: ANN001
            from starboard.discovery.query_packs.registry import PlanSelection

            return PlanSelection(domains=[], packs=[])

    engine = DiscoveryEngine(
        sql_executor=_Ex(),
        config=EngineConfig(data_only=True, enable_cache=False),
        query_registry=_Reg(),
    )
    result = asyncio.run(engine.run())

    assert "AI_GATEWAY" in result.products_without_packs
    assert "JOBS" not in result.products_without_packs
