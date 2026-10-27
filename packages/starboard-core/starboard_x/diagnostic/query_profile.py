# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Stdlib-only Databricks query-profile parser (D3-22).

:func:`parse_profile` reads a query profile JSON into a :class:`QueryProfileSummary`:
the operators, the top operators by time / rows / bytes, spill, scan stats and
deterministic warning codes. Two shapes are read:

* Liquid: ``query`` (metadata + metrics) and ``graphs[].nodes[]`` (``id`` / ``name`` /
  ``tag``, metrics and metadata as ``[{key, value}]`` arrays, ``stageData``).
* Standard: an ``operatorID`` / ``operatorName`` tree (``children``), or an array of
  such trees.

Anything else is scanned recursively for operator-shaped objects. The heavy
``starboard.tools.domain.diagnostic.QueryProfileExplorer`` wraps this parser and
renders the summary as focused markdown.

This module imports the standard library only (no SDK, no pydantic, no yaml).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from starboard_x import contract as _contract

logger = logging.getLogger(__name__)

#: Operators kept in :attr:`QueryProfileSummary.operators` by default (the
#: aggregates always cover every operator).
DEFAULT_MAX_OPERATORS = 50
#: Entries in each ``top_by_*`` list.
TOP_N = 10
#: Characters of ``queryText`` kept in :meth:`QueryProfileSummary.to_dict`.
MAX_QUERY_TEXT_CHARS = 4000

JOIN_TAGS = frozenset(
    {
        "PHOTON_BROADCAST_HASH_JOIN_EXEC",
        "PHOTON_SHUFFLED_HASH_JOIN_EXEC",
        "PHOTON_BROADCAST_NESTED_LOOP_JOIN_EXEC",
        "PHOTON_SORT_MERGE_JOIN_EXEC",
        "BROADCAST_HASH_JOIN_EXEC",
        "SHUFFLED_HASH_JOIN_EXEC",
        "SORT_MERGE_JOIN_EXEC",
        "BROADCAST_NESTED_LOOP_JOIN_EXEC",
        "CARTESIAN_PRODUCT_EXEC",
    }
)
SHUFFLE_TAGS = frozenset(
    {
        "PHOTON_SHUFFLE_EXCHANGE_SINK_EXEC",
        "PHOTON_SHUFFLE_MAP_STAGE_EXEC",
        "SHUFFLE_EXCHANGE_EXEC",
        "REUSED_EXCHANGE_EXEC",
    }
)
SCAN_TAGS = frozenset(
    {
        "UNKNOWN_DATA_SOURCE_SCAN_EXEC",
        "DATA_SOURCE_SCAN_EXEC",
        "BATCH_SCAN_EXEC",
        "FILE_SCAN_EXEC",
        "PARQUET_SCAN_EXEC",
        "LOCAL_TABLE_SCAN_EXEC",
    }
)

#: Query-level metrics copied from a Liquid ``query.metrics`` (key -> default).
_QUERY_METRICS: tuple[tuple[str, Any], ...] = (
    ("totalTimeMs", 0),
    ("compilationTimeMs", 0),
    ("executionTimeMs", 0),
    ("resultFetchTimeMs", 0),
    ("metadataTimeMs", 0),
    ("planningTimeMs", None),
    ("queuedProvisioningTimeMs", None),
    ("queuedOverloadTimeMs", None),
    ("photonTotalTimeMs", 0),
    ("taskTotalTimeMs", 0),
    ("readBytes", 0),
    ("readRemoteBytes", 0),
    ("readCacheBytes", 0),
    ("writeRemoteBytes", 0),
    ("networkSentBytes", 0),
    ("spillToDiskBytes", 0),
    ("rowsReadCount", 0),
    ("rowsProducedCount", 0),
    ("readFilesCount", 0),
    ("prunedFilesCount", 0),
    ("totalFilesCount", None),
    ("prunedBytes", 0),
    ("readPartitionsCount", 0),
    ("totalPartitionsCount", None),
    ("resultFromCache", False),
    ("bytesReadFromCachePercentage", 0),
)
_QUERY_SOURCE_KEYS = ("scheduledBy", "dashboardId", "jobId", "notebookId", "pipelineId")

#: Operator metric keys, in lookup order. A ``Nanos`` key is converted to ms.
_TIME_KEYS = ("wallClockTimeNanos", "WALL_CLOCK_TIME", "totalTimeMs")
_ROW_KEYS = ("NUMBER_OUTPUT_ROWS", "numOutputRows")
_BYTE_KEYS = (
    "NUMBER_OUTPUT_BYTES",
    "numOutputBytes",
    "SIZE_OF_FILES_READ",
    "bytesRead",
)
_SPILL_KEYS = ("SPILL_SIZE", "spillSize", "spilledBytes", "spillToDiskBytes")

_RANGE_HINTS = ("range_join", "rangejoin", "range join")
_INEQUALITIES = (">=", "<=", ">", "<", "BETWEEN")
_SCAN_TABLE = re.compile(r"Scan\s+(\S+)")

# Warning codes (sorted in the summary).
WARN_CARTESIAN = "cartesian_product"
WARN_FAILED_STAGES = "failed_stages"
WARN_NESTED_LOOP = "nested_loop_join"
WARN_RANGE_JOIN = "range_join_candidate"
WARN_SPILL = "spill_to_disk"


def _pairs(raw: Any, *, multi: bool) -> dict[str, Any]:
    """A ``[{key|label, value[, values]}]`` array (or a dict) as a dict."""
    if isinstance(raw, dict):
        return raw
    out: dict[str, Any] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key: Any = item.get("key", item.get("label", "unknown"))
            if multi and item.get("values"):
                out[key] = item["values"]
            else:
                out[key] = item.get("value", "" if multi else 0)
    return out


@dataclass
class OperatorInfo:
    """One query-plan operator."""

    id: str
    name: str
    tag: str
    metrics: dict[str, Any]
    metadata: dict[str, Any]
    children_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_liquid_node(cls, node: dict[str, Any]) -> OperatorInfo:
        """A Liquid node: ``id``/``name``/``tag`` with array-form metrics/metadata."""
        return cls(
            id=node.get("id", "?"),
            name=node.get("name", "unknown"),
            tag=node.get("tag", "UNKNOWN"),
            metrics=_pairs(node.get("metrics", []), multi=False),
            metadata=_pairs(node.get("metadata", []), multi=True),
            children_ids=[],
        )

    @classmethod
    def from_standard_node(cls, node: dict[str, Any]) -> OperatorInfo:
        """A standard node: ``operatorID``/``operatorName``, metrics as a dict."""
        name = node.get("operatorName", node.get("name", "unknown"))
        metrics_raw = node.get("metrics", {})
        metrics = (
            _pairs(metrics_raw, multi=False)
            if isinstance(metrics_raw, (dict, list))
            else {}
        )
        return cls(
            id=str(node.get("operatorID", node.get("id", "?"))),
            name=name,
            tag=node.get("tag", cls._infer_tag(name)),
            metrics=metrics,
            metadata={},
            children_ids=[],
        )

    @staticmethod
    def _infer_tag(name: str) -> str:
        """Infer an operator tag from its name."""
        lower = name.lower()
        if "broadcast" in lower and "hash" in lower and "join" in lower:
            return "PHOTON_BROADCAST_HASH_JOIN_EXEC"
        if "shuffled" in lower and "hash" in lower and "join" in lower:
            return "PHOTON_SHUFFLED_HASH_JOIN_EXEC"
        if "sort" in lower and "merge" in lower and "join" in lower:
            return "PHOTON_SORT_MERGE_JOIN_EXEC"
        if "nested" in lower and "loop" in lower:
            return "PHOTON_BROADCAST_NESTED_LOOP_JOIN_EXEC"
        if "join" in lower:
            return "JOIN_EXEC"
        if "shuffle" in lower or "exchange" in lower:
            return "SHUFFLE_EXCHANGE_EXEC"
        if "scan" in lower:
            return "DATA_SOURCE_SCAN_EXEC"
        return "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tag": self.tag,
            "metrics": dict(self.metrics),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class OperatorStat:
    """One ``top_by_*`` entry: an operator and its metric value."""

    id: str
    name: str
    tag: str
    value: float

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "tag": self.tag, "value": self.value}


@dataclass(frozen=True)
class SpillStats:
    """Spill: the query-level bytes and the operators reporting spill."""

    spill_to_disk_bytes: int
    operators_with_spill: int


@dataclass(frozen=True)
class ScanStats:
    """Scans: the scanned tables (by scan count) and the query-level read stats."""

    scan_count: int
    tables: tuple[tuple[str, int], ...]
    read_bytes: int
    rows_read: int
    files_read: int
    files_pruned: int
    bytes_pruned: int


@dataclass(frozen=True)
class QueryProfileSummary:
    """A parsed query profile (the ``starboard_x`` result type; D3-22)."""

    format: str
    query: Mapping[str, Any]
    stages: tuple[Mapping[str, Any], ...]
    operator_count: int
    operators: tuple[OperatorInfo, ...]
    tag_counts: tuple[tuple[str, int], ...]
    join_algorithms: tuple[tuple[str, int], ...]
    top_by_time: tuple[OperatorStat, ...]
    top_by_rows: tuple[OperatorStat, ...]
    top_by_bytes: tuple[OperatorStat, ...]
    spill: SpillStats
    scans: ScanStats
    warnings: tuple[str, ...]
    truncated: bool

    def stage_stats(self) -> dict[str, Any]:
        stages = self.stages
        failed = [s for s in stages if s.get("status") == "FAILED"]
        return {
            "count": len(stages),
            "completed": sum(1 for s in stages if s.get("status") == "COMPLETE"),
            "failed": len(failed),
            "total_tasks": int(sum(_num(s.get("numTasks")) or 0 for s in stages)),
            "failed_stage_ids": [str(s.get("stageId", "?")) for s in failed],
        }

    def to_dict(self) -> dict[str, Any]:
        """The JSON form (the ``diagnostic profile`` verb's ``data``)."""
        query = dict(self.query)
        text = query.get("queryText")
        if isinstance(text, str) and len(text) > MAX_QUERY_TEXT_CHARS:
            query["queryText"] = text[:MAX_QUERY_TEXT_CHARS]
            query["queryTextTruncated"] = True
        return {
            "format": self.format,
            "query": query,
            "stages": self.stage_stats(),
            "operator_count": self.operator_count,
            "operators": [op.to_dict() for op in self.operators],
            "truncated": self.truncated,
            "tag_counts": dict(self.tag_counts),
            "join_algorithms": dict(self.join_algorithms),
            "top_by_time": [s.to_dict() for s in self.top_by_time],
            "top_by_rows": [s.to_dict() for s in self.top_by_rows],
            "top_by_bytes": [s.to_dict() for s in self.top_by_bytes],
            "spill": {
                "spill_to_disk_bytes": self.spill.spill_to_disk_bytes,
                "operators_with_spill": self.spill.operators_with_spill,
            },
            "scans": {
                "scan_count": self.scans.scan_count,
                "tables": [{"table": t, "scans": n} for t, n in self.scans.tables],
                "read_bytes": self.scans.read_bytes,
                "rows_read": self.scans.rows_read,
                "files_read": self.scans.files_read,
                "files_pruned": self.scans.files_pruned,
                "bytes_pruned": self.scans.bytes_pruned,
            },
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------- #
# Shape readers
# --------------------------------------------------------------------------- #
def _liquid_query_meta(q: Mapping[str, Any]) -> dict[str, Any]:
    text = q.get("queryText", "")
    meta: dict[str, Any] = {
        "id": q.get("id", "unknown"),
        "status": q.get("status", "unknown"),
        "queryText": _contract.redact_emails(text) if isinstance(text, str) else text,
        "statementType": q.get("statementType", ""),
    }
    metrics = q.get("metrics")
    if isinstance(metrics, Mapping):
        for key, default in _QUERY_METRICS:
            meta[key] = metrics.get(key, default)
    source = q.get("internalQuerySource")
    if isinstance(source, Mapping):
        meta["querySource"] = {k: source.get(k) for k in _QUERY_SOURCE_KEYS}
    return meta


def _parse_liquid(
    data: Mapping[str, Any],
) -> tuple[list[OperatorInfo], dict[str, Any], list[Mapping[str, Any]]]:
    query = data.get("query")
    meta = _liquid_query_meta(query) if isinstance(query, Mapping) else {}
    operators: list[OperatorInfo] = []
    stages: list[Mapping[str, Any]] = []
    graphs = data.get("graphs")
    for graph in graphs if isinstance(graphs, list) else []:
        if not isinstance(graph, Mapping):
            continue
        for node in graph.get("nodes", []) or []:
            if not isinstance(node, dict):
                continue
            op = OperatorInfo.from_liquid_node(node)
            # Keep a meaningful tag, or a scan / join by name.
            if (
                not op.tag.startswith("UNKNOWN")
                or "Scan" in op.name
                or "Join" in op.name
            ):
                operators.append(op)
        stages.extend(
            s for s in graph.get("stageData", []) or [] if isinstance(s, Mapping)
        )
    return operators, meta, stages


def _flatten_standard(node: Any, out: list[OperatorInfo]) -> None:
    if not isinstance(node, dict):
        return
    if "operatorID" in node or "operatorName" in node:
        out.append(OperatorInfo.from_standard_node(node))
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            _flatten_standard(child, out)


def _scan_recursive(data: Any, out: list[OperatorInfo]) -> None:
    if isinstance(data, dict):
        if "operatorID" in data or "operatorName" in data:
            out.append(OperatorInfo.from_standard_node(data))
        elif "id" in data and "name" in data and "tag" in data:
            out.append(OperatorInfo.from_liquid_node(data))
        for value in data.values():
            _scan_recursive(value, out)
    elif isinstance(data, list):
        for item in data:
            _scan_recursive(item, out)


def _is_standard(node: Any) -> bool:
    return isinstance(node, dict) and ("operatorID" in node or "operatorName" in node)


def _read_shape(
    data: Any,
) -> tuple[str, list[OperatorInfo], dict[str, Any], list[Mapping[str, Any]]]:
    """``(format, operators, query meta, stages)`` for a decoded profile."""
    operators: list[OperatorInfo] = []
    if isinstance(data, dict) and "graphs" in data:
        ops, meta, stages = _parse_liquid(data)
        return "liquid", ops, meta, stages
    if _is_standard(data):
        _flatten_standard(data, operators)
        return "standard", operators, {}, []
    if isinstance(data, list) and data:
        if _is_standard(data[0]):
            for item in data:
                _flatten_standard(item, operators)
            return "standard_array", operators, {}, []
        nodes = [OperatorInfo.from_liquid_node(n) for n in data if isinstance(n, dict)]
        return "liquid_nodes", nodes, {}, []
    _scan_recursive(data, operators)
    return "nested", operators, {}, []


# --------------------------------------------------------------------------- #
# Aggregates
# --------------------------------------------------------------------------- #
def _num(value: Any) -> float | None:
    """A metric value as a number (numeric strings included); ``None`` otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _metric(op: OperatorInfo, keys: Iterable[str]) -> float | None:
    for key in keys:
        if key in op.metrics:
            value = _num(op.metrics[key])
            if value is None:
                return None
            return value / 1_000_000 if "Nanos" in key else value
    return None


def _top(
    operators: list[OperatorInfo], keys: tuple[str, ...]
) -> tuple[OperatorStat, ...]:
    stats = [
        OperatorStat(str(op.id), op.name, op.tag, value)
        for op in operators
        if (value := _metric(op, keys)) is not None and value > 0
    ]
    stats.sort(key=lambda s: (-s.value, s.id))
    return tuple(stats[:TOP_N])


def join_algorithm(tag: str) -> str:
    """The join algorithm named by an operator tag."""
    upper = tag.upper()
    if "BROADCAST_HASH" in upper:
        return "Broadcast Hash"
    if "SHUFFLED_HASH" in upper:
        return "Shuffled Hash"
    if "SORT_MERGE" in upper:
        return "Sort Merge"
    if "BROADCAST_NESTED_LOOP" in upper:
        return "Broadcast Nested Loop"
    if "NESTED_LOOP" in upper:
        return "Nested Loop"
    if "CARTESIAN" in upper:
        return "Cartesian Product"
    return "Unknown"


def _counts(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    tally: dict[str, int] = {}
    for value in values:
        tally[value] = tally.get(value, 0) + 1
    return tuple(sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])))


def _int(value: Any) -> int:
    number = _num(value)
    return int(number) if number is not None else 0


def _scan_stats(operators: list[OperatorInfo], meta: Mapping[str, Any]) -> ScanStats:
    scans = [op for op in operators if op.tag in SCAN_TAGS or "Scan" in op.name]
    tables = []
    for op in scans:
        match = _SCAN_TABLE.search(op.name)
        tables.append(match.group(1) if match else op.name)
    return ScanStats(
        scan_count=len(scans),
        tables=_counts(tables),
        read_bytes=_int(meta.get("readBytes")),
        rows_read=_int(meta.get("rowsReadCount")),
        files_read=_int(meta.get("readFilesCount")),
        files_pruned=_int(meta.get("prunedFilesCount")),
        bytes_pruned=_int(meta.get("prunedBytes")),
    )


def _range_join_candidates(joins: list[OperatorInfo]) -> bool:
    """Whether a join has an inequality condition and no range-join hint applies."""
    hinted = False
    candidates = 0
    for op in joins:
        if "RANGE" in op.tag.upper() or any(
            isinstance(v, str) and any(h in v.lower() for h in _RANGE_HINTS)
            for v in op.metadata.values()
        ):
            hinted = True
        condition = op.metadata.get("CONDITION", [])
        text = (
            " ".join(str(c) for c in condition)
            if isinstance(condition, list)
            else str(condition)
        )
        if text and any(p in text for p in _INEQUALITIES):
            candidates += 1
    return candidates > 0 and not hinted


def _warnings(
    operators: list[OperatorInfo],
    spill: SpillStats,
    stages: list[Mapping[str, Any]],
) -> tuple[str, ...]:
    codes: set[str] = set()
    joins = [op for op in operators if op.tag in JOIN_TAGS]
    if spill.spill_to_disk_bytes > 0 or spill.operators_with_spill > 0:
        codes.add(WARN_SPILL)
    if any("NESTED_LOOP" in op.tag.upper() for op in operators):
        codes.add(WARN_NESTED_LOOP)
    if any("CARTESIAN" in op.tag.upper() for op in operators):
        codes.add(WARN_CARTESIAN)
    if _range_join_candidates(joins):
        codes.add(WARN_RANGE_JOIN)
    if any(s.get("status") == "FAILED" for s in stages):
        codes.add(WARN_FAILED_STAGES)
    return tuple(sorted(codes))


def parse_profile(
    content: str | bytes,
    *,
    max_operators: int | None = DEFAULT_MAX_OPERATORS,
) -> QueryProfileSummary:
    """Parse a query profile JSON into a :class:`QueryProfileSummary`.

    ``max_operators`` caps :attr:`QueryProfileSummary.operators` (``None`` keeps all;
    ``truncated`` says whether the cap applied). The aggregates cover every operator.
    Invalid JSON raises :class:`ValueError` (``json.JSONDecodeError``).
    """
    data = json.loads(content)
    fmt, operators, meta, stages = _read_shape(data)
    spill = SpillStats(
        spill_to_disk_bytes=_int(meta.get("spillToDiskBytes")),
        operators_with_spill=sum(
            1 for op in operators if (_metric(op, _SPILL_KEYS) or 0) > 0
        ),
    )
    kept = operators if max_operators is None else operators[:max_operators]
    logger.debug("query_profile_parsed format=%s operators=%d", fmt, len(operators))
    return QueryProfileSummary(
        format=fmt,
        query=meta,
        stages=tuple(stages),
        operator_count=len(operators),
        operators=tuple(kept),
        tag_counts=_counts(op.tag for op in operators),
        join_algorithms=_counts(
            join_algorithm(op.tag) for op in operators if op.tag in JOIN_TAGS
        ),
        top_by_time=_top(operators, _TIME_KEYS),
        top_by_rows=_top(operators, _ROW_KEYS),
        top_by_bytes=_top(operators, _BYTE_KEYS),
        spill=spill,
        scans=_scan_stats(operators, meta),
        warnings=_warnings(operators, spill, stages),
        truncated=len(kept) < len(operators),
    )


__all__ = [
    "DEFAULT_MAX_OPERATORS",
    "JOIN_TAGS",
    "SCAN_TAGS",
    "SHUFFLE_TAGS",
    "OperatorInfo",
    "OperatorStat",
    "QueryProfileSummary",
    "ScanStats",
    "SpillStats",
    "join_algorithm",
    "parse_profile",
]
