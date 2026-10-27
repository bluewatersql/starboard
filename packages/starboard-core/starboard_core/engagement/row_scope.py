# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Authorized row scope for customer ``system.*`` SQL (engagement spec G3).

A customer workspace's system tables carry rows for every workspace in the
account. A run authorized for specific workspaces must only read their rows, so
:func:`scope_system_sql` rewrites each ``FROM``/``JOIN system.<schema>.<table>``
reference into a scoped subquery::

    FROM system.billing.usage u
    -> FROM (SELECT * FROM system.billing.usage WHERE workspace_id IN ('123')) u

An existing alias (and ``AS``) is kept verbatim. A reference with no alias gets
the bare table name as its alias (backtick-quoted) so column references
qualified by the table name (``usage.sku_name``) keep resolving.

Tables in :data:`NON_WORKSPACE_TABLES` (no ``workspace_id`` column) and the
``system.information_schema`` schema pass unwrapped. Every other system table —
including ones this module has never seen — is wrapped: a wrong guess yields a
SQL column error, never a cross-workspace read.

Fail closed: any ``system.<schema>.<table>`` reference that is left unscoped
outside a ``FROM``/``JOIN`` position (comma joins, string literals, fully
qualified column references) raises :class:`RowScopeError` instead of being
emitted. So do references the rewrite cannot see: ``IDENTIFIER(...)`` clauses
and two-part ``FROM``/``JOIN <system-schema>.<table>`` names (which resolve
against ``system`` after ``USE CATALOG system``).

The SQL is first split by a small lexer that knows ``'...'`` / ``"..."``
strings (backslash escapes; ``R'...'`` raw strings), backtick identifiers
(doubled-backtick escape), ``--`` line comments and nested ``/* */`` comments.
Only real comments are ignored; a comment marker inside a quoted token hides
nothing. An unterminated string, identifier or comment raises.

This is a bounded lexer plus regex rewrite, not a SQL parser; it covers the
discovery-pack SQL shapes in this repo (CTEs, joins, subqueries, optional
``AS`` alias).

Standard library only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

__all__ = [
    "NON_WORKSPACE_TABLES",
    "RowScopeError",
    "WorkspaceAuthorizationError",
    "scope_system_sql",
]


class RowScopeError(ValueError):
    """The SQL cannot be limited to the authorized workspaces — refuse to run it."""


class WorkspaceAuthorizationError(PermissionError):
    """The connected workspace is not in the run's authorized scope — nothing ran."""


#: Public system tables with no ``workspace_id`` column. Global price / hardware
#: dimensions, account-grained pricing, account-grained Marketplace provider
#: events, and metastore-grained data-classification / data-quality results (the
#: discovery queries scope those to the catalogs visible from the connected
#: workspace via system.information_schema.catalogs). These cannot be filtered by
#: workspace and pass unwrapped.
NON_WORKSPACE_TABLES: frozenset[str] = frozenset(
    {
        "system.billing.list_prices",
        "system.billing.account_prices",
        "system.compute.node_types",
        "system.marketplace.listing_access_events",
        "system.marketplace.listing_funnel_events",
        "system.data_classification.results",
        "system.data_quality_monitoring.table_results",
    }
)

#: Whole schemas that are metadata views, not workspace-grained data.
_EXEMPT_SCHEMAS: frozenset[str] = frozenset({"information_schema"})

_PART = r"(?:`[A-Za-z_][A-Za-z0-9_]*`|[A-Za-z_][A-Za-z0-9_]*)"

#: ``system.<schema>.<table>`` with optional per-part backticks, or one
#: backtick-quoted ``system.<schema>.<table>`` identifier.
_TABLE = (
    rf"(?:`(?i:system)\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*`"
    rf"|(?:`(?i:system)`|(?i:system))\s*\.\s*{_PART}\s*\.\s*{_PART})"
)

#: Words that may follow a bare table reference and are not an alias.
_NOT_ALIAS = (
    "ON|WHERE|JOIN|GROUP|ORDER|LIMIT|USING|LEFT|RIGHT|INNER|FULL|CROSS|OUTER|NATURAL"
    "|SEMI|ANTI|UNION|EXCEPT|INTERSECT|MINUS|HAVING|QUALIFY|WINDOW|LATERAL|PIVOT"
    "|UNPIVOT|TABLESAMPLE|TIMESTAMP|VERSION|FOR|WITH|SELECT|CLUSTER|DISTRIBUTE|SORT"
    "|OFFSET|FETCH|AS"
)

_REF = re.compile(
    rf"""
    (?P<keyword>\bFROM\b|\bJOIN\b)
    (?P<ws>\s+)
    (?P<table>{_TABLE})
    (?![A-Za-z0-9_`.])
    (?:
        \s+
        (?P<as>AS\s+)?
        (?P<alias>(?!(?:{_NOT_ALIAS})\b)[A-Za-z_][A-Za-z0-9_]*|`[^`]+`)
    )?
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Any ``system.<schema>.<table>`` reference (for the residual fail-closed check).
_ANY = re.compile(rf"(?<![A-Za-z0-9_.`])(?P<table>{_TABLE})")

#: Schemas of the ``system`` catalog. ``FROM``/``JOIN <schema>.<table>`` with one
#: of these is refused: after ``USE CATALOG system`` it is an unscoped read.
SYSTEM_SCHEMAS: frozenset[str] = frozenset(
    {
        "access",
        "ai_gateway",
        "billing",
        "compute",
        "data_classification",
        "data_quality_monitoring",
        "lakeflow",
        "marketplace",
        "mlflow",
        "query",
        "serving",
        "sharing",
        "storage",
        "workflow",
    }
)

#: ``FROM``/``JOIN <part>.<part>`` that is not followed by a third part.
_TWO_PART = re.compile(
    rf"\b(?:FROM|JOIN)\s+(?P<schema>{_PART})\s*\.\s*{_PART}(?![A-Za-z0-9_`]|\s*\.)",
    re.IGNORECASE,
)

#: ``USE …`` / ``SET CATALOG|SCHEMA|DATABASE …`` at a statement start: a changed
#: default catalog or schema lets a one-part name resolve to a system table.
_SESSION_DEFAULT = re.compile(
    r"(?:^|;)\s*(?:USE|SET\s+(?:CATALOG|SCHEMA|DATABASE))\b", re.IGNORECASE
)

#: ``IDENTIFIER(...)`` names a table from an expression the rewrite cannot see.
_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_.])`?IDENTIFIER`?\s*\(", re.IGNORECASE)

#: Backtick identifier bodies kept verbatim in the masked text (names only).
_PLAIN_IDENT = re.compile(r"[A-Za-z0-9_.]*")

#: Filler for masked string / identifier bodies: not a word, space or quote.
_FILL = "\x01"

_IDENT_CHAR = re.compile(r"[A-Za-z0-9_]")


def _lex(sql: str) -> list[tuple[str, int, int]]:
    """Split ``sql`` into ``(kind, start, end)`` non-code tokens, in order.

    ``kind`` is ``comment``, ``string`` or ``ident``. Everything between tokens
    is code. String spans cover the quotes (a raw ``R`` prefix stays code).

    Raises:
        RowScopeError: an unterminated string, identifier or block comment.
    """
    tokens: list[tuple[str, int, int]] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = i + 2
            while j < n and sql[j] not in "\r\n":
                j += 2 if sql.startswith("\\\n", j) else 1
            tokens.append(("comment", i, min(j, n)))
            i = j
        elif sql.startswith("/*", i):
            depth, j = 1, i + 2
            while depth:
                if j >= n:
                    raise RowScopeError("unterminated /* comment — refusing to scope")
                if sql.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif sql.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            tokens.append(("comment", i, j))
            i = j
        elif c in "'\"":
            raw = (
                i > 0
                and sql[i - 1] in "rR"
                and (i < 2 or not _IDENT_CHAR.match(sql[i - 2]))
            )
            j = i + 1
            while j < n and sql[j] != c:
                j += 2 if sql[j] == "\\" and not raw else 1
            if j >= n:
                raise RowScopeError("unterminated string literal — refusing to scope")
            tokens.append(("string", i, j + 1))
            i = j + 1
        elif c == "`":
            j = i + 1
            while True:
                j = sql.find("`", j)
                if j < 0:
                    raise RowScopeError("unterminated `identifier — refusing to scope")
                if sql.startswith("``", j):
                    j += 2
                    continue
                break
            tokens.append(("ident", i, j + 1))
            i = j + 1
        else:
            i += 1
    return tokens


def _masked(sql: str, tokens: list[tuple[str, int, int]]) -> tuple[str, str]:
    """Return same-length ``(code, residual)`` views of ``sql``.

    ``code``: comments blanked, string bodies (and non-name identifier bodies)
    filled, so only real SQL structure can match. ``residual``: comments
    blanked, everything else verbatim with ``"`` read as a backtick, so a
    reference spelled in a literal or a double-quoted identifier is still seen.
    """
    code = list(sql)
    residual = list(sql)
    for kind, start, end in tokens:
        if kind == "comment":
            code[start:end] = residual[start:end] = " " * (end - start)
        elif kind == "string" or not _PLAIN_IDENT.fullmatch(sql, start + 1, end - 1):
            code[start + 1 : end - 1] = _FILL * (end - start - 2)
    return "".join(code), "".join(residual).replace('"', "`")


def _canonical(raw: str) -> str:
    """``SYSTEM.`Billing`.usage`` -> ``system.billing.usage``."""
    return re.sub(r"[`\s]", "", raw).lower()


def _exempt(table: str) -> bool:
    return table in NON_WORKSPACE_TABLES or table.split(".")[1] in _EXEMPT_SCHEMAS


def _id_list(workspace_ids: Iterable[str]) -> str:
    """Render ids as ``('1','2')`` — digits-only, de-duplicated, order kept."""
    ids: list[str] = []
    for raw in workspace_ids:
        value = raw if isinstance(raw, str) else str(raw)
        if not (value.isascii() and value.isdigit()):
            raise RowScopeError(f"workspace id must be digits only: {raw!r}")
        if value not in ids:
            ids.append(value)
    if not ids:
        raise RowScopeError(
            "no authorized workspace ids — refusing to run unscoped SQL"
        )
    return "(" + ",".join(f"'{v}'" for v in ids) + ")"


def scope_system_sql(sql: str, workspace_ids: tuple[str, ...]) -> str:
    """Limit every workspace-grained ``system.*`` reference to ``workspace_ids``.

    Raises:
        RowScopeError: ``workspace_ids`` is empty or holds a non-digit id; the
            SQL has an unterminated string, identifier or comment; it uses an
            ``IDENTIFIER(...)`` clause or a two-part ``<system-schema>.<table>``
            name; or a workspace-grained system table is referenced where it
            cannot be wrapped (it would otherwise be read unscoped).
    """
    ids = _id_list(workspace_ids)
    code, residual = _masked(sql, _lex(sql))

    if _SESSION_DEFAULT.search(code):
        raise RowScopeError(
            "statements that change the default catalog or schema cannot be "
            "limited to the authorized workspaces"
        )
    if _IDENTIFIER.search(code):
        raise RowScopeError(
            "IDENTIFIER(...) table references cannot be limited to the "
            "authorized workspaces"
        )
    for match in _TWO_PART.finditer(code):
        if _canonical(match.group("schema")) in SYSTEM_SCHEMAS:
            raise RowScopeError(
                f"{sql[match.start('schema') : match.end()].strip()!r} names a system "
                "schema without the catalog and cannot be limited to the "
                "authorized workspaces"
            )

    # Rewrite each FROM/JOIN system reference found in the code view, splicing
    # the original text; blank the rewritten table spans out of the residual.
    out: list[str] = []
    check = list(residual)
    last = 0
    for match in _REF.finditer(code):
        start, end = match.span("table")
        check[start:end] = " " * (end - start)
        table = _canonical(sql[start:end])
        if _exempt(table):
            continue
        alias = match.group("alias")
        if alias:
            alias_as = (
                sql[match.start("as") : match.end("as")] if match.group("as") else ""
            )
            suffix = f" {alias_as}{sql[match.start('alias') : match.end('alias')]}"
            stop = match.end()
        else:
            suffix = f" `{table.rsplit('.', 1)[1]}`"
            stop = end
        out.append(sql[last:start])
        out.append(f"(SELECT * FROM {table} WHERE workspace_id IN {ids}){suffix}")
        last = stop
    out.append(sql[last:])

    for match in _ANY.finditer("".join(check)):
        table = _canonical(match.group("table"))
        if not _exempt(table):
            raise RowScopeError(
                f"{table} is referenced outside a FROM/JOIN position and cannot be "
                "limited to the authorized workspaces"
            )

    return "".join(out)
