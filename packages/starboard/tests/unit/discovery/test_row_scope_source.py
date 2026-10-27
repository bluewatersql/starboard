# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Authorized row scope on the public discovery path (engagement spec G3).

Proves:

1. Every discovery-pack query, rendered, is rewritten so no workspace-grained
   ``system.*`` reference stays unscoped, and the output keeps balanced parens.
2. :class:`ScopedSystemTablesSource` scopes the prepared SQL; a query that cannot
   be scoped is ``Unavailable`` (skipped), never run unscoped.
3. With ``authorized_workspace_ids`` set, the engine proves the connected
   workspace's server ID is authorized BEFORE any query runs.
"""

from __future__ import annotations

import collections
import re

import polars as pl
import pytest
from starboard.discovery.engine import (
    DiscoveryEngine,
    EngineConfig,
    WorkspaceAuthorizationError,
)
from starboard.discovery.query_packs.registry import create_default_registry
from starboard.discovery.sources import (
    PreparedQuery,
    QuerySource,
    ScopedSystemTablesSource,
    SystemTablesSource,
    Unavailable,
)
from starboard_core.domain.models.discovery.query import SystemQuery
from starboard_core.engagement.row_scope import (
    NON_WORKSPACE_TABLES,
    scope_system_sql,
)

WS = ("1234567890",)


class _Exec:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def execute_sql(self, sql: str) -> pl.DataFrame:
        self.sql.append(sql)
        return pl.DataFrame({"n": [1]})


def _render(template: str) -> str:
    return template.format_map(
        collections.defaultdict(str, {"lookback_days": 30, "result_limit": 50})
    )


def _all_queries() -> list[SystemQuery]:
    return [q for p in create_default_registry().all_packs for q in p.queries]


_REF = re.compile(r"(?<![\w.`])`?system`?\.`?(\w+)`?\.`?(\w+)`?", re.IGNORECASE)
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_SCOPED = re.compile(
    r"\(SELECT \* FROM system\.\w+\.\w+ WHERE workspace_id IN \('1234567890'\)\)"
)


def _balanced(sql: str) -> bool:
    depth = 0
    for ch in re.sub(r"'(?:[^']|'')*'", "''", _COMMENT.sub(" ", sql)):
        depth += ch == "("
        depth -= ch == ")"
        if depth < 0:
            return False
    return depth == 0


@pytest.mark.unit
def test_registry_has_queries() -> None:
    assert len(_all_queries()) > 50


@pytest.mark.unit
@pytest.mark.parametrize("query", _all_queries(), ids=lambda q: q.query_id)
def test_every_pack_query_is_fully_scoped(query: SystemQuery) -> None:
    rendered = _render(query.sql_template)
    out = scope_system_sql(rendered, WS)

    assert _balanced(out), out
    # Remove the scoped subqueries; whatever system.* is left must be exempt.
    residue = _SCOPED.sub("(SCOPED)", _COMMENT.sub(" ", out))
    for schema, table in _REF.findall(residue):
        name = f"system.{schema}.{table}".lower()
        assert name in NON_WORKSPACE_TABLES or schema.lower() == "information_schema", (
            f"{query.query_id}: unscoped {name}"
        )
    # Every workspace-grained reference in the original became a scoped subquery.
    originals = [
        f"system.{s}.{t}".lower() for s, t in _REF.findall(_COMMENT.sub(" ", rendered))
    ]
    grained = [
        n
        for n in originals
        if n not in NON_WORKSPACE_TABLES and n.split(".")[1] != "information_schema"
    ]
    assert len(_SCOPED.findall(out)) >= len(grained)


@pytest.mark.unit
class TestScopedSource:
    def _q(self) -> SystemQuery:
        return SystemQuery(
            query_id="C-B01",
            name="n",
            description="d",
            sql_template="SELECT 1 FROM system.billing.usage",
            required_tables=("system.billing.usage",),
            domain="billing",
        )

    def test_prepare_scopes_sql(self) -> None:
        exe = _Exec()
        out = ScopedSystemTablesSource(exe, WS).prepare(
            self._q(), "SELECT u.x FROM system.billing.usage u"
        )
        assert isinstance(out, PreparedQuery)
        assert out.executor is exe
        assert out.sql == (
            "SELECT u.x FROM (SELECT * FROM system.billing.usage "
            "WHERE workspace_id IN ('1234567890')) u"
        )

    def test_unscopable_sql_is_unavailable(self) -> None:
        out = ScopedSystemTablesSource(_Exec(), WS).prepare(
            self._q(), "SELECT 1 FROM system.billing.usage u, system.query.history h"
        )
        assert isinstance(out, Unavailable)
        assert "row scope" in out.reason

    def test_empty_scope_is_unavailable(self) -> None:
        out = ScopedSystemTablesSource(_Exec(), ()).prepare(
            self._q(), "SELECT 1 FROM system.billing.usage"
        )
        assert isinstance(out, Unavailable)

    def test_is_a_query_source(self) -> None:
        assert isinstance(ScopedSystemTablesSource(_Exec(), WS), QuerySource)


def _probe(value: str, calls: list[int]):
    async def probe() -> str:
        calls.append(1)
        return value

    return probe


@pytest.mark.unit
class TestEngineGate:
    def test_authorized_scope_selects_scoped_source(self) -> None:
        eng = DiscoveryEngine(
            sql_executor=_Exec(),
            config=EngineConfig(authorized_workspace_ids=WS),
            workspace_id_probe=_probe(WS[0], []),
        )
        assert isinstance(eng._pack_executor._source, ScopedSystemTablesSource)

    def test_no_authorization_keeps_identity_source(self) -> None:
        eng = DiscoveryEngine(sql_executor=_Exec(), config=EngineConfig())
        src = eng._pack_executor._source
        assert type(src) is SystemTablesSource

    async def test_run_on_authorized_workspace_scopes_every_query(self) -> None:
        exe = _Exec()
        calls: list[int] = []
        eng = DiscoveryEngine(
            sql_executor=exe,
            config=EngineConfig(
                authorized_workspace_ids=WS, data_only=True, exact_packs=["billing"]
            ),
            workspace_id_probe=_probe("1234567890", calls),
        )
        result = await eng.run()
        assert calls == [1]
        assert result.errors == []
        assert exe.sql, "expected queries to run"
        for sql in exe.sql:
            assert "workspace_id IN ('1234567890')" in sql

    async def test_run_refuses_unauthorized_workspace_before_any_query(self) -> None:
        exe = _Exec()
        eng = DiscoveryEngine(
            sql_executor=exe,
            config=EngineConfig(authorized_workspace_ids=WS, data_only=True),
            workspace_id_probe=_probe("999", []),
        )
        with pytest.raises(WorkspaceAuthorizationError, match="999"):
            await eng.run()
        assert exe.sql == []

    async def test_plan_refuses_unauthorized_workspace(self) -> None:
        exe = _Exec()
        eng = DiscoveryEngine(
            sql_executor=exe,
            config=EngineConfig(authorized_workspace_ids=WS),
            workspace_id_probe=_probe("999", []),
        )
        with pytest.raises(WorkspaceAuthorizationError):
            await eng.plan()
        assert exe.sql == []

    async def test_missing_probe_refuses(self) -> None:
        exe = _Exec()
        eng = DiscoveryEngine(
            sql_executor=exe,
            config=EngineConfig(authorized_workspace_ids=WS, data_only=True),
        )
        with pytest.raises(WorkspaceAuthorizationError, match="cannot verify"):
            await eng.run()
        assert exe.sql == []

    async def test_empty_authorized_scope_refuses(self) -> None:
        exe = _Exec()
        eng = DiscoveryEngine(
            sql_executor=exe,
            config=EngineConfig(authorized_workspace_ids=(), data_only=True),
            workspace_id_probe=_probe("1", []),
        )
        with pytest.raises(WorkspaceAuthorizationError):
            await eng.run()
        assert exe.sql == []

    def test_is_permission_error(self) -> None:
        assert issubclass(WorkspaceAuthorizationError, PermissionError)
