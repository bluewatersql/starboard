# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Query and warehouse data transformation functions.

This module provides functions to transform Databricks SQL warehouse configurations,
query history, and EXPLAIN plan outputs into compact, LLM-optimized formats for analysis.
"""

from __future__ import annotations

import re
import statistics as stats
from collections import Counter
from typing import Any

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _split_comma_list(s: str) -> list[str]:
    """Split comma-separated string into list, stripping whitespace."""
    if not s or not s.strip():
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _strip_nulls(data: Any) -> Any:
    """Recursively remove None, empty strings, dicts, and lists from data structure."""
    if isinstance(data, dict):
        cleaned_dict = {}
        for key, value in data.items():
            cleaned_value = _strip_nulls(value)
            if cleaned_value not in (None, "", {}, []):
                cleaned_dict[key] = cleaned_value
        return cleaned_dict

    if isinstance(data, list):
        cleaned_list = [
            _strip_nulls(item) for item in data if item not in (None, "", {}, [])
        ]
        return [item for item in cleaned_list if item not in (None, "", {}, [])]

    return data


# =============================================================================
# Warehouse Transform Functions
# =============================================================================


def transform_warehouse_configuration(
    configuration: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Transform warehouse configuration into a compact, LLM-optimized format.

    Args:
        configuration: Warehouse configuration

    Returns:
        Transformed warehouse configuration or None if no configuration
    """
    if not configuration:
        return None

    keys = [
        "auto_stop_mins",
        "cluster_size",
        "enable_photon",
        "enable_serverless_compute",
        "id",
        "max_num_clusters",
        "min_num_cluster",
        "name",
        "spot_instance_policy",
        "warehouse_type",
    ]
    return {k: v for k, v in configuration.items() if k in keys}


def transform_query_history(history: dict[str, Any] | None) -> dict[str, Any] | None:
    """Transform query history into a compact, LLM-optimized format.

    Args:
        history: Query history

    Returns:
        Transformed query history or None if no history
    """
    if not history:
        return None

    keys = [
        "duration",
        "execution_end_time_ms",
        "lookup_key",
        "metrics",
        "plan_state",
        "query_id",
        "query_start_time_ms",
        "rows_produced",
        "statement_type",
        "status",
        "warehouse_id",
    ]
    return {k: v for k, v in history.items() if k in keys}


# =============================================================================
# Query Plan and Metrics Transformers (BB-06)
# =============================================================================


def transform_query_plan(
    plan_text: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Transform query plan from query history API into LLM-optimized format.

    The plan_text from /api/2.0/sql/history/queries/{id}?include_plans=true
    returns a list of plan entries. This transformer extracts key insights.

    Args:
        plan_text: List of plan entries from query history API

    Returns:
        Transformed plan summary for LLM consumption or None if no plan
    """
    if not plan_text or not isinstance(plan_text, list):
        return None

    result: dict[str, Any] = {
        "plan_count": len(plan_text),
        "plans": [],
    }

    for _, plan in enumerate(plan_text[:5]):  # Limit to 5 plans
        if not isinstance(plan, dict):
            continue

        plan_summary: dict[str, Any] = {}

        # Extract key plan fields
        if "plan" in plan:
            plan_content = plan["plan"]
            if isinstance(plan_content, str):
                # Count lines and key operations
                lines = plan_content.split("\n")
                plan_summary["line_count"] = len(lines)
                plan_summary["preview"] = "\n".join(lines[:20])  # First 20 lines

                # Check for common operations
                plan_lower = plan_content.lower()
                plan_summary["has_scan"] = "scan" in plan_lower
                plan_summary["has_join"] = "join" in plan_lower
                plan_summary["has_shuffle"] = (
                    "shuffle" in plan_lower or "exchange" in plan_lower
                )
                plan_summary["has_sort"] = "sort" in plan_lower
                plan_summary["has_aggregate"] = (
                    "aggregate" in plan_lower or "hashaggregate" in plan_lower
                )
                plan_summary["has_filter"] = "filter" in plan_lower

        # Extract plan state
        if "plan_state" in plan:
            plan_summary["state"] = plan["plan_state"]

        if plan_summary:
            result["plans"].append(plan_summary)

    return _strip_nulls(result) if result["plans"] else None


def transform_query_metrics(metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    """Transform query metrics from query history API into LLM-optimized format.

    The metrics from /api/2.0/sql/history/queries/{id}?include_metrics=true
    provides detailed execution statistics. This transformer extracts key insights.

    Args:
        metrics: Metrics dictionary from query history API

    Returns:
        Transformed metrics summary for LLM consumption or None if no metrics
    """
    if not metrics or not isinstance(metrics, dict):
        return None

    result: dict[str, Any] = {}

    # Time metrics (converted to milliseconds for consistency)
    time_keys = [
        "total_time_ms",
        "compilation_time_ms",
        "execution_time_ms",
        "result_fetch_time_ms",
        "metadata_time_ms",
        "planning_time_ms",
    ]
    for key in time_keys:
        if key in metrics:
            result[key] = metrics[key]

    # I/O metrics
    io_keys = [
        "read_bytes",
        "write_bytes",
        "read_rows",
        "write_rows",
        "rows_produced_count",
        "read_files_count",
        "read_partitions_count",
        "pruned_files_count",
        "pruned_bytes",
        "spill_to_disk_bytes",
    ]
    for key in io_keys:
        if key in metrics:
            result[key] = metrics[key]

    # Compute metrics
    compute_keys = [
        "photon_total_time_ms",
        "task_total_time_ms",
        "peak_execution_memory_bytes",
    ]
    for key in compute_keys:
        if key in metrics:
            result[key] = metrics[key]

    # Add derived insights
    if result:
        # Calculate Photon coverage if available
        if "photon_total_time_ms" in result and "task_total_time_ms" in result:
            photon = result["photon_total_time_ms"]
            total = result["task_total_time_ms"]
            if total > 0:
                result["photon_coverage_pct"] = round((photon / total) * 100, 1)

        # Calculate read efficiency if available
        if "read_bytes" in result and "pruned_bytes" in result:
            read = result["read_bytes"]
            pruned = result["pruned_bytes"]
            if read + pruned > 0:
                result["pruning_efficiency_pct"] = round(
                    (pruned / (read + pruned)) * 100, 1
                )

        # Flag potential issues
        result["flags"] = {}
        if result.get("spill_to_disk_bytes", 0) > 0:
            result["flags"]["has_disk_spill"] = True
        if result.get("pruning_efficiency_pct", 100) < 50:
            result["flags"]["low_pruning_efficiency"] = True

    return _strip_nulls(result) if result else None


def transform_resolve_query_result(
    result: dict[str, Any],
    include_plan_summary: bool = True,
    include_metrics_summary: bool = True,
) -> dict[str, Any]:
    """Transform resolve_query result to include distilled plan and metrics.

    BB-06: This allows the LLM to see key insights from plan and metrics
    without needing separate tool calls.

    Args:
        result: Raw resolve_query result with sql_text, plan_text, metrics
        include_plan_summary: Whether to add plan summary
        include_metrics_summary: Whether to add metrics summary

    Returns:
        Enhanced result with plan_summary and metrics_summary fields
    """
    enhanced = dict(result)

    if include_plan_summary and result.get("plan_text"):
        plan_summary = transform_query_plan(result["plan_text"])
        if plan_summary:
            enhanced["plan_summary"] = plan_summary

    if include_metrics_summary and result.get("metrics"):
        metrics_summary = transform_query_metrics(result["metrics"])
        if metrics_summary:
            enhanced["metrics_summary"] = metrics_summary

    return enhanced


# =============================================================================
# SQL EXPLAIN Constants and Patterns
# =============================================================================

# Section header pattern
SEC_HDR = re.compile(r"^\s*==\s*(.+?)\s*==\s*$")

# Section key mappings
SEC_KEYS = {
    "Parsed Logical Plan": "parsed_logical",
    "Analyzed Logical Plan": "analyzed_logical",
    "Optimized Logical Plan": "optimized_logical",
    "Physical Plan": "physical",
    "Photon Explanation": "photon_expl",
    "Optimizer Statistics (table names per statistics state)": "optimizer_stats",
}

# Operator patterns
_PHOTON_OP = re.compile(r"\bPhoton([A-Z][A-Za-z0-9_]*)")
_ID_PAT = re.compile(r"#\d+[Ll]?")
_BQ_PAT = re.compile(r"`([^`]+)`")
_UUID_PAT = re.compile(r"[0-9a-f]{8}-[0-9a-f\-]{13,}")
_PATH_PAT = re.compile(r"(?:file|s3a|abfss|dbfs|hdfs)[:][^\s\]]+", re.IGNORECASE)
_SKIP_PAT = re.compile(
    r"^(AdaptiveSparkPlan|WholeStageCodegen|Arguments:|== Initial Plan ==|ColumnarToRow|RowToColumnar)$",
    re.IGNORECASE,
)

# Operator type patterns
JOIN = re.compile(
    r"(?i)(BroadcastHashJoin|ShuffledHashJoin|SortMergeJoin|NestedLoopJoin|HashJoin)"
)
SCAN = re.compile(r"(?i)(Scan|BatchScan|FileScan|DataSourceV2ScanRelation)")
EXCH = re.compile(
    r"(?i)(Exchange|BroadcastExchange|ShuffleExchange|ShuffleExchangeSink|ShuffleExchangeSource)"
)

# Schema and filter patterns
READ_SCHEMA = re.compile(r"(?i)\bReadSchema:\s*struct<([^>]+)>")
DATA_FILTERS = re.compile(r"(?i)\bDataFilters:\s*\[([^\]]*)\]")
REQ_FILTERS = re.compile(r"(?i)\bRequiredDataFilters:\s*\[([^\]]*)\]")
OPT_FILTERS = re.compile(r"(?i)\bOptionalDataFilters:\s*\[([^\]]*)\]")
DICT_FILTERS = re.compile(r"(?i)\bDictionaryFilters:\s*\[([^\]]*)\]")

# Partitioning pattern
PARTITIONING = re.compile(
    r"(?i)\b(HashPartitioning|hashpartitioning|RoundRobinPartitioning|SinglePartition)\s*(?:\(([^)]*)\))?"
)


# =============================================================================
# SQL EXPLAIN Section Parsing Functions
# =============================================================================


def split_explain_sections(explain_text: str) -> dict[str, list[str]]:
    """Split EXPLAIN text into logical sections.

    Parses section headers (e.g., "== Physical Plan ==") and groups lines
    into their respective sections.

    Args:
        explain_text: Full EXPLAIN output text from Spark/Databricks

    Returns:
        Dictionary mapping section keys to lists of lines
    """
    cur_key: str | None = None
    buckets: dict[str, list[str]] = {v: [] for v in SEC_KEYS.values()}
    for line in explain_text.splitlines():
        m = SEC_HDR.match(line)
        if m:
            title = m.group(1).strip()
            cur_key = SEC_KEYS.get(title)
            continue
        if cur_key:
            buckets[cur_key].append(line.rstrip("\n"))
    return buckets


# =============================================================================
# Line Cleaning and Normalization Functions
# =============================================================================


def _clean_line(line: str, normalize_photon: bool) -> str | None:
    """Clean and normalize a single line from the physical plan."""
    t = line.strip()
    if not t:
        return None
    if _SKIP_PAT.match(t):
        return None
    s = line.replace("|", "").replace("+-", "").replace(":-", "").strip()
    if not s:
        return None
    s = _BQ_PAT.sub(r"\1", s)
    s = _ID_PAT.sub("", s)
    s = _UUID_PAT.sub("<uuid>", s)
    s = _PATH_PAT.sub("<path>", s)
    s = re.sub(r"\s+", " ", s).strip()
    if normalize_photon:
        s = _PHOTON_OP.sub(r"\1", s)
    s = s.lstrip(": -")
    return s or None


def _extract_physical_lines(
    physical_lines: list[str], normalize_photon: bool
) -> tuple[list[str], list[str]]:
    """Extract and clean physical plan lines."""
    raw: list[str] = []
    norm: list[str] = []
    for ln in physical_lines:
        if _SKIP_PAT.match(ln.strip()):
            continue
        raw.append(ln.rstrip("\n"))
        c = _clean_line(ln, normalize_photon=normalize_photon)
        if c:
            norm.append(c)
    return raw, norm


# =============================================================================
# Physical Plan Analysis Functions
# =============================================================================


def _is_photon_line(raw_line: str) -> bool:
    """Check if a raw line contains Photon operators."""
    return "Photon" in raw_line


def _op_token(line: str) -> str | None:
    """Extract the operator token from a normalized line."""
    tok = re.split(r"[ \t(]", line, maxsplit=1)[0].strip(": -")
    return tok or None


def _read_schema_field_count(line: str) -> int:
    """Count the number of fields in a ReadSchema struct."""
    m = READ_SCHEMA.search(line)
    if not m:
        return 0
    schema = m.group(1)
    depth = 0
    fields = 1 if schema else 0
    for ch in schema:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            fields += 1
    return fields


def _parse_partitioning(line: str) -> dict[str, Any]:
    """Parse partitioning information from a physical plan line."""
    pm = PARTITIONING.search(line)
    if not pm:
        return {}
    kind = pm.group(1)
    args = (pm.group(2) or "").strip()
    num = None
    exprs: list[str] | None = None
    if kind and kind.lower() == "singlepartition":
        num = 1
        exprs = []
    else:
        parts = _split_comma_list(args) if args else []
        if parts and parts[-1].isdigit():
            num = int(parts[-1])
            exprs = parts[:-1]
        else:
            exprs = parts
    return {"type": kind, "exprs": exprs, "num_partitions": num}


def summarize_physical(raw_lines: list[str], norm_lines: list[str]) -> dict[str, Any]:
    """Analyze physical plan lines and extract key optimization insights.

    Tracks operators, joins, scans, exchanges, Photon coverage, and identifies
    performance anti-patterns like single-partition bottlenecks.

    Args:
        raw_lines: Raw physical plan lines (for Photon detection)
        norm_lines: Normalized/cleaned physical plan lines

    Returns:
        Dictionary with operator flow, counts, flags, and rollup metrics
    """
    hist: dict[str, int] = {}
    joins: list[dict[str, Any]] = []
    scans: list[dict[str, Any]] = []
    exch: list[dict[str, Any]] = []

    photon_lines = 0
    total_ops = 0

    table_scan_counts: dict[str, int] = {}
    format_counts: dict[str, int] = {}
    shuffle_partition_counts: list[int] = []
    shuffle_partition_kinds: list[str] = []
    total_scan_fields = 0
    total_filter_tokens = 0

    for raw, line in zip(raw_lines, norm_lines):
        op = _op_token(line)
        if not op:
            continue
        total_ops += 1
        is_photon = _is_photon_line(raw)
        if is_photon:
            photon_lines += 1

        hist[op] = hist.get(op, 0) + 1

        # JOINS
        if JOIN.search(line):
            jt = re.search(r"(?i)\b(inner|left|right|full|cross|semi|anti)\b", line)
            joins.append(
                {
                    "op": op,
                    "join_type": jt.group(1).lower() if jt else None,
                    "cartesian": "cross" in line.lower(),
                    "photon": is_photon,
                }
            )

        # SCANS
        if SCAN.search(line):
            fmt = re.search(r"(?i)\b(delta|parquet|csv|orc|json|jdbc)\b", line)
            tbl = re.search(r"(?i)(?:table|relation)\s*[:=]\s*([a-zA-Z0-9_.]+)", line)

            data_match = DATA_FILTERS.search(line)
            req_match = REQ_FILTERS.search(line)
            opt_match = OPT_FILTERS.search(line)
            dict_match = DICT_FILTERS.search(line)

            data_filters = _split_comma_list(data_match.group(1)) if data_match else []
            req_filters = _split_comma_list(req_match.group(1)) if req_match else []
            opt_filters = _split_comma_list(opt_match.group(1)) if opt_match else []
            dict_filters = _split_comma_list(dict_match.group(1)) if dict_match else []
            fields_count = _read_schema_field_count(line)

            scans.append(
                {
                    "op": op,
                    "format": (fmt.group(1).lower() if fmt else None),
                    "table": (tbl.group(1) if tbl else None),
                    "photon": is_photon,
                    "read_schema_fields": fields_count,
                    "data_filters": data_filters[:20],
                    "required_filters": req_filters[:20],
                    "optional_filters": opt_filters[:20],
                    "dictionary_filters": dict_filters[:10],
                }
            )

            if fmt:
                f = fmt.group(1).lower()
                format_counts[f] = format_counts.get(f, 0) + 1
            if tbl:
                t = tbl.group(1)
                table_scan_counts[t] = table_scan_counts.get(t, 0) + 1

            total_scan_fields += fields_count
            total_filter_tokens += (
                len(data_filters) + len(req_filters) + len(opt_filters)
            )

        # EXCHANGES
        if EXCH.search(line):
            part = _parse_partitioning(line)
            if part:
                kind = part.get("type")
                width = part.get("num_partitions")
                if kind:
                    shuffle_partition_kinds.append(kind)
                if width is not None:
                    shuffle_partition_counts.append(width)
            exch.append({"op": op, "photon": is_photon, "partitioning": part or None})

    flags = {
        "cartesian_join": any(j["cartesian"] for j in joins),
        "many_exchanges": len(exch) > 3,
        "python_udf": any("PythonUDF" in line for line in norm_lines),
        "adaptive": any("AdaptiveSparkPlan" in raw for raw in raw_lines),
    }

    effective_width = (
        max(shuffle_partition_counts) if shuffle_partition_counts else None
    )
    dominant_width = None
    width_variance = None
    single_partition_ct = shuffle_partition_counts.count(1)

    if shuffle_partition_counts:
        c = Counter(shuffle_partition_counts)
        dominant_width, _ = c.most_common(1)[0]
        if len(set(shuffle_partition_counts)) >= 2:
            try:
                width_variance = stats.pvariance(shuffle_partition_counts)
            except (TypeError, ValueError):
                width_variance = None

    single_partition_bottleneck = (single_partition_ct > 0) and (len(joins) > 0)
    low_width_for_large_join = (
        (len(joins) > 0) and (effective_width is not None) and (effective_width < 32)
    )
    high_width_variance = False
    if shuffle_partition_counts and len(set(shuffle_partition_counts)) > 1:
        mx, mn = max(shuffle_partition_counts), min(shuffle_partition_counts)
        if mn > 0 and mx / mn >= 8 or (width_variance or 0) > 10_000:
            high_width_variance = True

    repartition_opportunity = (
        single_partition_bottleneck or low_width_for_large_join or high_width_variance
    ) and (len(table_scan_counts) >= 2 or len(scans) >= 2)

    flags.update(
        {
            "single_partition_bottleneck": single_partition_bottleneck,
            "low_width_for_large_join": low_width_for_large_join,
            "high_width_variance": high_width_variance,
            "repartition_opportunity": repartition_opportunity,
        }
    )

    flow = " -> ".join(list(hist.keys()))[:900]
    photon_cov = round((photon_lines / total_ops) * 100, 1) if total_ops else 0.0

    rollups = {
        "distinct_tables": len(table_scan_counts),
        "scans_by_table": table_scan_counts,
        "scans_by_format": format_counts,
        "total_scan_fields": total_scan_fields,
        "total_filter_tokens": total_filter_tokens,
        "shuffle_partition_widths": shuffle_partition_counts,
        "shuffle_partition_kinds": shuffle_partition_kinds,
        "effective_shuffle_width": effective_width,
        "dominant_shuffle_width": dominant_width,
        "shuffle_width_variance": width_variance,
        "max_shuffle_partitions": max(shuffle_partition_counts)
        if shuffle_partition_counts
        else None,
        "min_shuffle_partitions": min(shuffle_partition_counts)
        if shuffle_partition_counts
        else None,
        "single_partition_exchanges": single_partition_ct,
    }

    return {
        "flow": flow,
        "operators": hist,
        "joins": joins,
        "scans": scans,
        "exchanges": exch,
        "flags": flags,
        "photon": {
            "present": photon_lines > 0,
            "coverage_pct": photon_cov,
            "op_lines_photon": photon_lines,
            "op_lines_total": total_ops,
        },
        "rollups": rollups,
        "lines": len(norm_lines),
    }


# =============================================================================
# Photon and Optimizer Statistics Parsers
# =============================================================================


def parse_photon_explanation(lines: list[str]) -> dict[str, Any]:
    """Parse the Photon Explanation section."""
    text = "\n".join([ln.strip() for ln in lines if ln.strip()])
    supported: bool | None = None
    if "fully supported by Photon" in text:
        supported = True
    elif "not supported" in text or "partially supported" in text:
        supported = False
    return {"raw": text, "supported": supported}


def parse_optimizer_stats(lines: list[str]) -> dict[str, Any]:
    """Parse the Optimizer Statistics section."""
    missing: list[str] = []
    partial: list[str] = []
    full: list[str] = []
    recommendation: str | None = None

    for ln in lines:
        s = ln.strip()
        low = s.lower()
        if low.startswith("missing"):
            missing = _split_comma_list(s.split("=", 1)[1]) if "=" in s else []
        elif low.startswith("partial"):
            partial = _split_comma_list(s.split("=", 1)[1]) if "=" in s else []
        elif low.startswith("full"):
            full = _split_comma_list(s.split("=", 1)[1]) if "=" in s else []
        elif low.startswith("corrective actions"):
            recommendation = s
        elif low.startswith("analyze table"):
            recommendation = (recommendation + "\n" if recommendation else "") + s

    out: dict[str, Any] = {
        "missing": [t for t in missing if t],
        "partial": [t for t in partial if t],
        "full": [t for t in full if t],
        "recommendation": recommendation,
    }
    return _strip_nulls(out)


# =============================================================================
# Public Transformation Functions
# =============================================================================


def transform_explain_text(
    explain_text: str, normalize_photon: bool = True
) -> dict[str, Any]:
    """Transform Databricks SQL EXPLAIN output into compact LLM-optimized format.

    Main entry point for processing EXPLAIN text from Spark/Databricks. Parses
    sections, analyzes physical plan, extracts Photon info, and identifies
    optimization opportunities.

    Args:
        explain_text: Full EXPLAIN output text from Databricks
        normalize_photon: If True, strip 'Photon' prefix from operator names

    Returns:
        Dictionary with physical_plan, photon_explanation, optimizer_statistics,
        and logical_sections summaries
    """
    secs = split_explain_sections(explain_text)
    raw_phys, norm_phys = _extract_physical_lines(
        secs.get("physical", []), normalize_photon=normalize_photon
    )
    phys_summary = summarize_physical(raw_phys, norm_phys) if norm_phys else {}

    photon_info = (
        parse_photon_explanation(secs.get("photon_expl", []))
        if secs.get("photon_expl")
        else {}
    )
    opt_stats = (
        parse_optimizer_stats(secs.get("optimizer_stats", []))
        if secs.get("optimizer_stats")
        else {}
    )

    result = {
        "physical_plan": phys_summary,
        "photon_explanation": photon_info,
        "optimizer_statistics": opt_stats,
        "logical_sections": {
            "parsed_lines": len(
                [ln for ln in secs.get("parsed_logical", []) if ln.strip()]
            ),
            "analyzed_lines": len(
                [ln for ln in secs.get("analyzed_logical", []) if ln.strip()]
            ),
            "optimized_lines": len(
                [ln for ln in secs.get("optimized_logical", []) if ln.strip()]
            ),
        },
    }
    return _strip_nulls(result)
