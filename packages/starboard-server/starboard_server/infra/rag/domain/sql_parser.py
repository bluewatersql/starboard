from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import polars as pl
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from starboard_core.rag.models import (
    AggregationRecord,
    AnalysisResult,
    JoinRecord,
    PredicateRecord,
)

# ----------------------------
# Normalization configuration
# ----------------------------

TEMPORAL_COLUMN_ALIASES = {
    "coalesced_price_end_time": "price_end_time",
    "nanvld_price_end_time": "price_end_time",
    "price_end_date": "price_end_time",
    "price_start_date": "price_start_time",
    "usage_date": "usage_time",
    "usage_start_time": "usage_time",
    "usage_end_time": "usage_time",
}

AGG_NAMES = {
    # common
    "sum",
    "count",
    "avg",
    "min",
    "max",
    # distinct-ish
    "count_distinct",
    "approx_count_distinct",
    # databricks/spark-ish
    "collect_list",
    "collect_set",
    "stddev",
    "stddev_samp",
    "stddev_pop",
    "variance",
    "var_samp",
    "var_pop",
    "corr",
    "covar_samp",
    "covar_pop",
    "percentile",
    "percentile_approx",
    "skewness",
    "kurtosis",
}


# ----------------------------
# Core helpers
# ----------------------------
def normalize_column_name(table_col: str) -> str:
    if "." not in table_col:
        return table_col
    table, col = table_col.rsplit(".", 1)
    return f"{table}.{TEMPORAL_COLUMN_ALIASES.get(col, col)}"


def get_join_type_category(join_type: str) -> str:
    jt = (join_type or "").upper()
    if "LEFT" in jt:
        return "LEFT"
    if "RIGHT" in jt:
        return "RIGHT"
    if "FULL" in jt or "OUTER" in jt:
        return "FULL_OUTER"
    if "CROSS" in jt:
        return "CROSS"
    if "INNER" in jt or jt.strip() == "":
        return "INNER"
    return jt


def resolve_table_name(
    table_expr: exp.Table,
    cte_names: set[str],
    default_catalog: str = "default",
    default_schema: str = "default",
) -> str | None:
    if table_expr is None:
        return None

    table_name = (table_expr.name or "").strip()
    schema_name = (table_expr.db or "").strip()
    catalog_name = (table_expr.catalog or "").strip()

    if table_name and table_name.lower() in cte_names:
        return None

    if catalog_name and schema_name and table_name:
        return f"{catalog_name}.{schema_name}.{table_name}"
    if schema_name and table_name:
        return f"{default_catalog}.{schema_name}.{table_name}"
    if table_name:
        return f"{default_catalog}.{default_schema}.{table_name}"
    return None


def get_cte_names(parsed: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in parsed.find_all(exp.CTE):
        if cte.alias:
            names.add(cte.alias.lower())
    return names


def _safe_lower(s: str | None) -> str | None:
    return s.lower() if s else None


def _expr_is_negated(node: exp.Expression) -> bool:
    p = node.parent
    while p is not None:
        if isinstance(p, exp.Not):
            return True
        if isinstance(p, (exp.And, exp.Or)):
            return False
        p = p.parent
    return False


def extract_column_or_literal(
    expr: exp.Expression, alias_to_table: dict[str, str]
) -> tuple[str, str] | None:
    if expr is None:
        return None

    if isinstance(expr, exp.Column):
        table_ref = _safe_lower(expr.table) if expr.table else None
        col_name = _safe_lower(expr.name) if expr.name else None
        if not col_name:
            return None
        if table_ref and table_ref in alias_to_table:
            return ("column", f"{alias_to_table[table_ref]}.{col_name}")
        elif not table_ref and len(alias_to_table) == 1:
            # Unqualified column with single table - implicit reference
            single_table = list(alias_to_table.values())[0]
            return ("column", f"{single_table}.{col_name}")
        return None

    if isinstance(expr, exp.Literal):
        if expr.is_string:
            return ("literal", "<string>")
        if expr.is_number:
            return ("literal", "<number>")
        return ("literal", "<literal>")

    if isinstance(expr, exp.Boolean):
        return ("literal", "<boolean>")
    if isinstance(expr, exp.Null):
        return ("literal", "<null>")

    if isinstance(
        expr,
        (exp.CurrentDate, exp.CurrentDatetime, exp.CurrentTimestamp, exp.CurrentTime),
    ):
        return ("literal", "<datetime>")
    if isinstance(expr, exp.Interval):
        return ("literal", "<interval>")

    if isinstance(expr, exp.Cast):
        return extract_column_or_literal(expr.this, alias_to_table)

    if isinstance(expr, exp.Paren):
        return extract_column_or_literal(expr.this, alias_to_table)

    for col in expr.find_all(exp.Column):
        r = extract_column_or_literal(col, alias_to_table)
        if r:
            return r
    for lit in expr.find_all(exp.Literal):
        r = extract_column_or_literal(lit, alias_to_table)
        if r:
            return r

    return None


def extract_literal_value(expr: exp.Expression) -> str | None:
    if expr is None:
        return None

    if isinstance(expr, exp.Literal):
        return str(expr.this) if expr.this is not None else None

    if isinstance(expr, exp.Boolean):
        return str(expr.this).upper() if hasattr(expr, "this") else None

    if isinstance(expr, exp.Null):
        return "NULL"

    if isinstance(expr, exp.Cast):
        return extract_literal_value(expr.this)

    if isinstance(expr, exp.Paren):
        return extract_literal_value(expr.this)

    return None


# ----------------------------
# Scope building
# ----------------------------


@dataclass
class _StatementContext:
    cte_names: set[str]
    cte_sources: dict[str, set[str]]


def _build_statement_context(parsed: exp.Expression) -> _StatementContext:
    cte_names = get_cte_names(parsed)
    cte_sources: dict[str, set[str]] = {}

    for cte in parsed.find_all(exp.CTE):
        if not cte.alias:
            continue
        name = cte.alias.lower()
        src = set()
        for t in cte.find_all(exp.Table):
            fq = resolve_table_name(t, cte_names)
            if fq:
                src.add(fq.lower())
        cte_sources[name] = src

    for subq in parsed.find_all(exp.Subquery):
        if not subq.alias:
            continue
        alias = subq.alias.lower()
        src = set()
        for t in subq.find_all(exp.Table):
            fq = resolve_table_name(t, cte_names)
            if fq:
                src.add(fq.lower())
        if src:
            cte_sources[alias] = src

    return _StatementContext(cte_names=cte_names, cte_sources=cte_sources)


def _build_alias_map_for_select(
    select: exp.Select,
    ctx: _StatementContext,
) -> tuple[dict[str, tuple[str, bool]], dict[str, str], set[str]]:
    aliases: dict[str, tuple[str, bool]] = {}
    left_tables: set[str] = set()

    from_clause = select.find(exp.From)
    if from_clause:
        from_expr = from_clause.this

        if isinstance(from_expr, exp.Subquery) and from_expr.alias:
            a = from_expr.alias.lower()
            aliases[a] = (a, True)
            left_tables.update(ctx.cte_sources.get(a, set()))
        elif isinstance(from_expr, exp.Table):
            tbl = from_expr
            base_name = tbl.name.lower() if tbl.name else ""
            alias = tbl.alias.lower() if tbl.alias else base_name

            fq = resolve_table_name(tbl, ctx.cte_names)
            if fq:
                aliases[alias] = (fq.lower(), False)
                left_tables.add(fq.lower())
            elif base_name and base_name in ctx.cte_names:
                aliases[alias] = (base_name, True)
                left_tables.update(ctx.cte_sources.get(base_name, set()))

    for j in select.args.get("joins") or []:
        for subquery in j.find_all(exp.Subquery):
            if subquery.alias:
                sq_alias = subquery.alias.lower()
                aliases[sq_alias] = (sq_alias, True)

        join_table = j.find(exp.Table)
        if join_table:
            table_name_lower = join_table.name.lower() if join_table.name else ""
            alias = join_table.alias.lower() if join_table.alias else table_name_lower

            fq = resolve_table_name(join_table, ctx.cte_names)
            if fq:
                aliases[alias] = (fq.lower(), False)
            elif table_name_lower and table_name_lower in ctx.cte_names:
                aliases[alias] = (table_name_lower, True)

    alias_to_table: dict[str, str] = {}
    for a, (ref, is_cte) in aliases.items():
        if is_cte:
            srcs = ctx.cte_sources.get(ref, set())
            if srcs:
                rep = sorted(srcs)[0]
                alias_to_table[a] = rep.split(".")[-1]
        else:
            alias_to_table[a] = ref.split(".")[-1]

    return aliases, alias_to_table, left_tables


# ----------------------------
# Extraction
# ----------------------------

_COMPARISONS = (
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Is,
    exp.Like,
    exp.ILike,
    exp.Between,
)

_PRED_NODES = (
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Is,
    exp.Like,
    exp.ILike,
    exp.Between,
    exp.In,
)

_OP_SYMBOL = {
    exp.EQ: "=",
    exp.NEQ: "!=",
    exp.GT: ">",
    exp.GTE: ">=",
    exp.LT: "<",
    exp.LTE: "<=",
    exp.Is: "IS",
    exp.Like: "LIKE",
    exp.ILike: "ILIKE",
    exp.In: "IN",
    exp.Between: "BETWEEN",
}


def _extract_join_pairs(
    on_expr: exp.Expression | None, alias_to_table: dict[str, str]
) -> tuple[tuple[tuple[str, str], ...], str]:
    """
    Extract join key pairs from ON clause.
    Only extracts EQUALITY (=) comparisons - these are the true join keys.
    Range conditions (>, <, >=, <=, BETWEEN) are excluded as they're filters, not join keys.

    Returns:
      join_pairs: tuple of sorted pairs (canonical)
      join_condition: human-readable "a=b AND c=d"
    """
    if not on_expr:
        return (), ""

    pairs: set[tuple[str, str]] = set()

    # Only look for equality comparisons - these are the true join keys
    for comp in on_expr.find_all(exp.EQ):
        # Skip nested comparisons
        p = comp.parent
        nested = False
        while p is not None and p is not on_expr:
            if isinstance(p, exp.EQ):
                nested = True
                break
            p = p.parent
        if nested:
            continue

        lhs = extract_column_or_literal(comp.this, alias_to_table)
        rhs = extract_column_or_literal(comp.expression, alias_to_table)

        if lhs and rhs and lhs[0] == "column" and rhs[0] == "column":
            lhsn = normalize_column_name(lhs[1])
            rhsn = normalize_column_name(rhs[1])
            pairs.add(tuple(sorted([lhsn, rhsn])))  # type: ignore[arg-type]

    join_pairs = tuple(sorted(pairs))
    join_condition = " AND ".join(f"{a} = {b}" for a, b in join_pairs)
    return join_pairs, join_condition


def _extract_predicates(
    expr: exp.Expression | None, scope: str, alias_to_table: dict[str, str]
) -> list[PredicateRecord]:
    if not expr:
        return []

    out: list[PredicateRecord] = []

    node: exp.Expression
    for node in expr.find_all(_PRED_NODES):  # type: ignore[arg-type, var-annotated]
        p: exp.Expression | None = node.parent
        nested = False
        while p is not None and p is not expr:
            if isinstance(p, _PRED_NODES):
                nested = True
                break
            p = p.parent
        if nested:
            continue

        negated = _expr_is_negated(node)
        op = _OP_SYMBOL.get(type(node), type(node).__name__.upper())

        if isinstance(node, exp.Between):
            lhs = extract_column_or_literal(node.this, alias_to_table)
            low_expr: exp.Expression | None = node.args.get("low")
            high_expr: exp.Expression | None = node.args.get("high")
            low = (
                extract_column_or_literal(low_expr, alias_to_table)
                if low_expr
                else None
            )
            high = (
                extract_column_or_literal(high_expr, alias_to_table)
                if high_expr
                else None
            )
            if lhs and lhs[0] == "column":
                lhsn = normalize_column_name(lhs[1])
                if low and low_expr:
                    values = []
                    if low[0] == "literal":
                        val = extract_literal_value(low_expr)
                        if val:
                            values.append(val)
                    out.append(
                        PredicateRecord(
                            scope=scope,
                            op="BETWEEN_LOW",
                            lhs=lhsn,
                            rhs_kind=low[0],
                            rhs=low[1]
                            if low[0] == "literal"
                            else normalize_column_name(low[1]),
                            negated=negated,
                            values=tuple(values),
                        )
                    )
                if high and high_expr:
                    values = []
                    if high[0] == "literal":
                        val = extract_literal_value(high_expr)
                        if val:
                            values.append(val)
                    out.append(
                        PredicateRecord(
                            scope=scope,
                            op="BETWEEN_HIGH",
                            lhs=lhsn,
                            rhs_kind=high[0],
                            rhs=high[1]
                            if high[0] == "literal"
                            else normalize_column_name(high[1]),
                            negated=negated,
                            values=tuple(values),
                        )
                    )
            continue

        if isinstance(node, exp.In):
            lhs = extract_column_or_literal(node.this, alias_to_table)
            if lhs and lhs[0] == "column":
                lhsn = normalize_column_name(lhs[1])
                values = []
                in_expr = node.expressions if hasattr(node, "expressions") else []
                for item in in_expr:
                    val = extract_literal_value(item)
                    if val:
                        values.append(val)
                out.append(
                    PredicateRecord(
                        scope=scope,
                        op="IN",
                        lhs=lhsn,
                        rhs_kind="literal",
                        rhs="<list>",
                        negated=negated,
                        values=tuple(values),
                    )
                )
            continue

        lhs = (
            extract_column_or_literal(node.this, alias_to_table)
            if hasattr(node, "this")
            else None
        )
        rhs_expr = node.expression if hasattr(node, "expression") else None
        rhs = (
            extract_column_or_literal(rhs_expr, alias_to_table)
            if rhs_expr is not None
            else None
        )

        if lhs and rhs and lhs[0] == "column":
            lhsn = normalize_column_name(lhs[1])
            rhs_val = rhs[1] if rhs[0] == "literal" else normalize_column_name(rhs[1])

            values = []
            if rhs[0] == "literal" and rhs_expr is not None:
                val = extract_literal_value(rhs_expr)
                if val:
                    values.append(val)

            out.append(
                PredicateRecord(
                    scope=scope,
                    op=op,
                    lhs=lhsn,
                    rhs_kind=rhs[0],
                    rhs=rhs_val,
                    negated=negated,
                    values=tuple(values),
                )
            )

    return out


def _func_name(node: exp.Expression) -> str:
    n = getattr(node, "name", None)
    if n:
        return str(n).lower()
    return node.__class__.__name__.lower()


def _extract_aggregation_arg(
    fn: exp.Func, alias_to_table: dict[str, str]
) -> tuple[str, str]:
    """
    Extract the most meaningful argument representation from an aggregate function.

    Returns:
        (arg_kind, arg_value) where:
        - arg_kind: "star" | "column" | "columns" | "literal" | "expr"
        - arg_value: the representation

    Priority:
    1. * (for COUNT(*))
    2. Single column reference
    3. Multiple column references (for expressions like col1 + col2)
    4. Literal
    5. Complex expression
    """
    # Check for COUNT(*)
    if fn.find(exp.Star):
        return "star", "*"

    # Get the main argument (usually fn.this for most aggregates)
    main_arg = fn.this if hasattr(fn, "this") else None
    if main_arg is None and hasattr(fn, "expressions") and fn.expressions:
        # Check expressions array (some functions use this)
        main_arg = fn.expressions[0]

    if main_arg is None:
        return "expr", "<expr>"

    # Try to extract column(s) from the argument
    columns = []
    for col in main_arg.find_all(exp.Column):
        r = extract_column_or_literal(col, alias_to_table)
        if r and r[0] == "column":
            columns.append(normalize_column_name(r[1]))

    if columns:
        if len(columns) == 1:
            return "column", columns[0]
        else:
            # Multiple columns - show all
            return "columns", " + ".join(sorted(set(columns)))

    # Check if it's a simple literal
    literals = list(main_arg.find_all(exp.Literal))
    if literals and not main_arg.find_all(exp.Column):
        # Pure literal expression
        r = extract_column_or_literal(literals[0], alias_to_table)
        if r:
            return "literal", r[1]

    # Check for common patterns we can simplify
    if isinstance(main_arg, exp.Column):
        # Direct column reference (shouldn't get here, but just in case)
        r = extract_column_or_literal(main_arg, alias_to_table)
        if r and r[0] == "column":
            return "column", normalize_column_name(r[1])

    # For CASE statements, try to extract columns
    if isinstance(main_arg, exp.Case):
        case_cols = []
        for col in main_arg.find_all(exp.Column):
            r = extract_column_or_literal(col, alias_to_table)
            if r and r[0] == "column":
                case_cols.append(normalize_column_name(r[1]))
        if case_cols:
            return "columns", "CASE(" + ", ".join(sorted(set(case_cols))) + ")"

    # For arithmetic operations, show the columns involved
    if isinstance(main_arg, (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod)):
        arith_cols = []
        for col in main_arg.find_all(exp.Column):
            r = extract_column_or_literal(col, alias_to_table)
            if r and r[0] == "column":
                arith_cols.append(normalize_column_name(r[1]))
        if arith_cols:
            op_symbol = {
                exp.Add: "+",
                exp.Sub: "-",
                exp.Mul: "*",
                exp.Div: "/",
                exp.Mod: "%",
            }.get(type(main_arg), "")
            return "columns", f"{arith_cols[0]} {op_symbol} ..." if len(
                arith_cols
            ) > 1 else arith_cols[0]

    # For nested functions (e.g., SUM(COALESCE(col, 0)))
    nested_funcs = list(main_arg.find_all(exp.Func))
    if nested_funcs:
        # Try to get columns from nested functions
        nested_cols = []
        for nf in nested_funcs:
            for col in nf.find_all(exp.Column):
                r = extract_column_or_literal(col, alias_to_table)
                if r and r[0] == "column":
                    nested_cols.append(normalize_column_name(r[1]))
        if nested_cols:
            func_name = _func_name(nested_funcs[0])
            if len(nested_cols) == 1:
                return "column", f"{func_name.upper()}({nested_cols[0]})"
            else:
                return "columns", f"{func_name.upper()}(" + ", ".join(
                    sorted(set(nested_cols))
                ) + ")"

    # Default: return simplified expression (show type of operation)
    expr_type = type(main_arg).__name__
    return "expr", f"<{expr_type}>"


def _extract_aggregations(
    select: exp.Select, alias_to_table: dict[str, str]
) -> list[AggregationRecord]:
    out: list[AggregationRecord] = []

    for proj in select.expressions or []:
        alias: str | None = None
        node = proj

        if isinstance(proj, exp.Alias):
            alias = proj.alias
            node = proj.this

        for fn in node.find_all(exp.Func):
            name = _func_name(fn)
            if name not in AGG_NAMES:
                continue

            distinct = bool(fn.find(exp.Distinct))

            arg_kind, arg_val = _extract_aggregation_arg(fn, alias_to_table)

            out.append(
                AggregationRecord(
                    agg=name.upper(),
                    arg_kind=arg_kind,
                    arg=arg_val,
                    alias=alias,
                    distinct=distinct,
                )
            )

    return out


def _extract_joins_from_select(
    select: exp.Select,
    ctx: _StatementContext,
) -> tuple[list[JoinRecord], list[PredicateRecord], list[AggregationRecord]]:
    aliases, alias_to_table, left_tables = _build_alias_map_for_select(select, ctx)

    joins_out: list[JoinRecord] = []
    preds_out: list[PredicateRecord] = []
    aggs_out: list[AggregationRecord] = []

    preds_out.extend(
        _extract_predicates(select.args.get("where"), "WHERE", alias_to_table)
    )
    preds_out.extend(
        _extract_predicates(select.args.get("having"), "HAVING", alias_to_table)
    )
    preds_out.extend(
        _extract_predicates(select.args.get("qualify"), "QUALIFY", alias_to_table)
    )

    aggs_out.extend(_extract_aggregations(select, alias_to_table))

    previous_tables = set(left_tables)
    for j in select.args.get("joins") or []:
        join_table = j.find(exp.Table)
        if not join_table:
            continue

        table_name_lower = join_table.name.lower() if join_table.name else ""
        alias = join_table.alias.lower() if join_table.alias else table_name_lower

        to_info = aliases.get(alias)
        if not to_info:
            continue

        to_ref, to_is_cte = to_info

        join_kind = (j.kind or "").strip()
        join_side = (j.side or "").strip()
        join_type = get_join_type_category(f"{join_side} {join_kind}".strip())

        on_expr = j.args.get("on")
        join_pairs, join_condition = _extract_join_pairs(on_expr, alias_to_table)
        preds_out.extend(_extract_predicates(on_expr, "JOIN_ON", alias_to_table))

        from_tables_in_condition: set[str] = set()
        if on_expr:
            for col in on_expr.find_all(exp.Column):
                if not col.table:
                    continue
                a = col.table.lower()
                info = aliases.get(a)
                if not info:
                    continue
                ref, is_cte = info
                if ref == to_ref:
                    continue
                if is_cte:
                    from_tables_in_condition.update(ctx.cte_sources.get(ref, set()))
                else:
                    from_tables_in_condition.add(ref)

        if not from_tables_in_condition:
            from_tables_in_condition = set(previous_tables)

        to_tables = ctx.cte_sources.get(to_ref, set()) if to_is_cte else {to_ref}

        for ft in from_tables_in_condition:
            for tt in to_tables:
                if ft and tt and ft != tt:
                    joins_out.append(
                        JoinRecord(
                            from_table=ft,
                            to_table=tt,
                            join_type=join_type,
                            join_pairs=join_pairs,
                            join_condition=join_condition,
                        )
                    )

        if to_is_cte:
            previous_tables.update(ctx.cte_sources.get(to_ref, set()))
        else:
            previous_tables.add(to_ref)

    return joins_out, preds_out, aggs_out


# ----------------------------
# Single-pass aggregators
# ----------------------------


class _JoinAggregator:
    """Aggregates join records into summary format."""

    def __init__(self):
        # (from_table, to_table, join_pairs) -> {join_types, frequency}
        self.condition_data: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = (
            defaultdict(lambda: {"join_types": set(), "frequency": 0})
        )

    def add(self, join: JoinRecord):
        if not join.join_pairs:
            return
        key = (join.from_table, join.to_table, join.join_pairs)
        self.condition_data[key]["join_types"].add(join.join_type)  # type: ignore[index]
        self.condition_data[key]["frequency"] += 1  # type: ignore[index]

    def get_summary(self) -> list[dict[str, Any]]:
        # Group by (from_table, to_table)
        pair_data: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for (ft, tt, pairs), data in self.condition_data.items():
            pair_data[(ft, tt)].append(
                {
                    "pairs": set(pairs),
                    "join_types": data["join_types"],
                    "frequency": data["frequency"],
                }
            )

        result: list[dict[str, Any]] = []

        for (ft, tt), conds in pair_data.items():
            conds.sort(key=lambda x: x["frequency"], reverse=True)

            all_join_types: set[str] = set()
            total_freq = 0

            non_empty_sets = []
            for c in conds:
                all_join_types.update(c["join_types"])
                total_freq += c["frequency"]
                if c["pairs"]:
                    non_empty_sets.append(c["pairs"])

            core_pairs = set.intersection(*non_empty_sets) if non_empty_sets else set()

            # extended conditions
            ext_freq: dict[str, int] = defaultdict(int)
            for c in conds:
                ext_pairs = c["pairs"] - core_pairs
                if not ext_pairs:
                    continue
                ext_str = " AND ".join(f"{a} = {b}" for a, b in sorted(ext_pairs))
                ext_freq[ext_str] += c["frequency"]

            core_str = " AND ".join(f"{a} = {b}" for a, b in sorted(core_pairs))

            result.append(
                {
                    "from_table": ft,
                    "to_table": tt,
                    "join_types": sorted(all_join_types),
                    "core_columns": core_str,
                    "extended_conditions": [
                        {"extended_columns": k, "frequency": v}
                        for k, v in sorted(ext_freq.items(), key=lambda kv: -kv[1])
                    ],
                    "frequency": total_freq,
                }
            )

        result.sort(key=lambda x: x["frequency"], reverse=True)
        return result


class _PredicateAggregator:
    """Aggregates predicate records into summary format."""

    def __init__(self):
        self.rows: list[dict[str, Any]] = []

    def add(self, pred: PredicateRecord):
        self.rows.append(pred.model_dump())

    def get_summary(self) -> pl.DataFrame:
        if not self.rows:
            return pl.DataFrame(
                schema={
                    "scope": pl.Utf8,
                    "op": pl.Utf8,
                    "lhs": pl.Utf8,
                    "rhs_kind": pl.Utf8,
                    "rhs": pl.Utf8,
                    "negated": pl.Boolean,
                    "values": pl.Utf8,
                    "frequency": pl.Int64,
                }
            )

        df = pl.DataFrame(self.rows)
        df = (
            df.group_by(["scope", "op", "lhs", "rhs_kind", "rhs", "negated", "values"])
            .agg(pl.len().alias("frequency"))
            .sort("frequency", descending=True)
        )
        return df


class _AggregationAggregator:
    """Aggregates aggregation records into summary format."""

    def __init__(self):
        self.rows: list[dict[str, Any]] = []

    def add(self, agg: AggregationRecord):
        # Store without alias for grouping
        self.rows.append(
            {
                "agg": agg.agg,
                "arg_kind": agg.arg_kind,
                "arg": agg.arg,
                "distinct": agg.distinct,
            }
        )

    def get_summary(self) -> pl.DataFrame:
        if not self.rows:
            return pl.DataFrame(
                schema={
                    "agg": pl.Utf8,
                    "arg_kind": pl.Utf8,
                    "arg": pl.Utf8,
                    "distinct": pl.Boolean,
                    "frequency": pl.Int64,
                }
            )

        df = pl.DataFrame(self.rows)
        df = (
            df.group_by(["agg", "arg_kind", "arg", "distinct"])
            .agg(pl.len().alias("frequency"))
            .sort("frequency", descending=True)
        )
        return df


# ----------------------------
# Single-pass public API
# ----------------------------
def analyze_dataframe(
    df: pl.DataFrame,
    statement_column: str = "statement_text",
    dialect: str = "databricks",
    table_prefix: str | None = None,
) -> AnalysisResult:
    """
    Single-pass analysis of SQL statements in a DataFrame.

    Args:
        df: Polars DataFrame containing SQL statements
        statement_column: Column name with SQL statements
        dialect: SQL dialect for parsing
        table_prefix: Optional filter - only include joins where to_table starts with this
    """
    if statement_column not in df.columns:
        raise ValueError(f"Column '{statement_column}' not found in DataFrame")

    statements = df.select(pl.col(statement_column)).to_series().drop_nulls().cast(pl.Utf8).to_list()
    if not statements:
        return AnalysisResult(
            success_count=0,
            failed_count=0,
            join_summary=[],
            raw_joins=[],
            raw_predicates=[],
            raw_aggregations=[],
        )

    # Initialize aggregators
    join_agg = _JoinAggregator()

    # Optional raw storage
    raw_joins = []
    raw_preds = []
    raw_aggs = []

    success_count = 0
    failed_count = 0

    # Single pass through all statements
    for sql in statements:
        if not sql or not isinstance(sql, str) or not sql.strip():
            failed_count += 1
            continue

        try:
            parsed_list = sqlglot.parse(sql, dialect=dialect)

            for parsed in parsed_list:
                if parsed is None:
                    continue
                ctx = _build_statement_context(parsed)

                for select in parsed.find_all(exp.Select):
                    joins, preds, aggs = _extract_joins_from_select(select, ctx)

                    # Add to aggregators
                    for j in joins:
                        # Apply table_prefix filter if specified
                        if table_prefix and not j.to_table.startswith(
                            table_prefix.lower()
                        ):
                            continue
                        join_agg.add(j)
                        raw_joins.append(j)

                    for p in preds:
                        raw_preds.append(p)

                    for a in aggs:
                        raw_aggs.append(a)

            success_count += 1
        except (ParseError, Exception):
            failed_count += 1

    # Generate summaries
    join_summary = join_agg.get_summary()

    return AnalysisResult(
        success_count=success_count,
        failed_count=failed_count,
        join_summary=join_summary,
        raw_joins=raw_joins,
        raw_predicates=raw_preds,
        raw_aggregations=raw_aggs,
    )
