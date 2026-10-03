# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared, dep-light serializers for the deterministic discovery result.

Extracted so BOTH discovery entry points emit the **same nested envelope
shape** and cannot drift:

- ``python -m starboard_x.discovery`` (external / customer-identity path), and
- ``starboard --discover --json`` (internal-mirror path, which layers
  ``source`` / ``scope`` / three-state ``counts`` on top of this same shape).

Stdlib-only and duck-typed on ``to_dicts()`` / ``columns`` (polars) so it stays
importable in the dep-light ``starboard_x`` tier with no SDK / pydantic. The
per-query dict carries the actual result ``rows`` (list-of-dicts) plus a
three-state ``status`` (``succeeded`` / ``skipped`` / ``failed``) so a host agent
can reason over the data directly without a server-side LLM.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from starboard_x.contract import to_jsonable
from starboard_x.discovery._facts import build_facts

# Per-query row cap for the emitted data. Discovery packs are curated aggregate
# scans (small result sets by design); this is a safety net against pathological
# outputs. When exceeded, the query's ``truncated`` flag is set. (Distinct from
# ``limit_reached``, which flags a query capped by its own SQL ``LIMIT``.)
_MAX_ROWS_PER_QUERY = 10_000


def _query_rows(df: Any) -> tuple[list[str], list[dict[str, Any]], bool]:
    """Extract (columns, capped-rows, truncated) from a DataFrame-like result.

    Duck-typed on ``to_dicts()`` / ``columns`` (polars) so this module stays
    dep-light and testable without importing polars. Returns empty values when
    there is no data (e.g. a failed query).
    """
    if df is None:
        return [], [], False
    to_dicts = getattr(df, "to_dicts", None)
    if not callable(to_dicts):
        return [], [], False
    records = to_dicts()
    columns = [str(c) for c in (getattr(df, "columns", None) or [])]
    truncated = len(records) > _MAX_ROWS_PER_QUERY
    rows = to_jsonable(records[:_MAX_ROWS_PER_QUERY])
    return columns, rows, truncated


def _query_status(qr: Any) -> str:
    """Three-state outcome for a query: ``succeeded`` / ``skipped`` / ``failed``.

    Prefers the model's ``status`` property; falls back to deriving from
    ``succeeded`` / ``skipped`` for duck-typed fakes that expose only those.
    A skip (unavailable on the selected source) is a coverage gap, not an error.
    """
    status = getattr(qr, "status", None)
    if isinstance(status, str):
        return status
    if getattr(qr, "succeeded", False):
        return "succeeded"
    return "skipped" if getattr(qr, "skipped", False) else "failed"


def _serialize_query(qr: Any) -> dict[str, Any]:
    """Serialize one ``QueryResult`` including its actual data rows.

    Emits both the boolean ``succeeded`` (backward-compatible) and the
    three-state ``status`` so a coverage skip is distinguishable from a failure.
    """
    columns, rows, truncated = _query_rows(getattr(qr, "data", None))
    # ``truncated`` only says THIS serializer dropped rows past its safety cap.
    # A query whose SQL carries ``LIMIT {result_limit}`` is capped upstream too:
    # when it returns exactly that many rows there may be more in the workspace,
    # so surface that separately (``limit_reached``) with the limit itself.
    row_count = getattr(qr, "row_count", len(rows))
    row_limit = getattr(qr, "result_limit", None)
    if not isinstance(row_limit, int) or isinstance(row_limit, bool):
        row_limit = None
    limit_reached = (
        row_limit is not None and isinstance(row_count, int) and row_count >= row_limit
    )
    return {
        "query_id": getattr(qr, "query_id", None),
        "domain": getattr(qr, "domain", None),
        "succeeded": bool(getattr(qr, "succeeded", False)),
        "status": _query_status(qr),
        "error": getattr(qr, "error", None),
        "row_count": row_count,
        "columns": columns,
        "rows": rows,
        "truncated": truncated,
        "row_limit": row_limit,
        "limit_reached": limit_reached,
        "lookback_days": getattr(qr, "lookback_days", None),
        # Execution metadata: how many times the statement was submitted (>1 =
        # a timed-out statement was retried) and each submission's wall time.
        "execution_time_ms": _round_ms(getattr(qr, "execution_time_ms", None)),
        "attempts": _int_or_none(getattr(qr, "attempts", None)),
        "attempt_elapsed_ms": [
            ms
            for ms in (_round_ms(v) for v in (getattr(qr, "attempt_elapsed_ms", None) or ()))
            if ms is not None
        ],
    }


def _round_ms(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 1)


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def serialize_result(result: Any) -> dict[str, Any]:
    """Serialize an ``EngineResult`` into a JSON-able data-only report.

    Emits the actual query result rows (not just counts) grouped by pack so a
    host agent (Isaac / Claude / Codex) can reason over the deterministic data
    directly — the data-only path runs no LLM itself.
    """
    audit = None
    audit_result = getattr(result, "audit_result", None)
    if audit_result is not None:
        audit = {"succeeded": getattr(audit_result, "succeeded", None)}

    packs: list[dict[str, Any]] = []
    pack_domains: list[str] = []
    for pr in getattr(result, "pack_results", []) or []:
        results = getattr(pr, "results", []) or []
        pack_domains.append(str(getattr(pr, "domain", None) or _pack_key(pr)))
        packs.append(
            {
                "pack": (
                    getattr(pr, "pack_id", None)
                    or getattr(pr, "name", None)
                    or getattr(pr, "domain", None)
                ),
                "queries": len(results),
                "succeeded": sum(
                    1 for qr in results if getattr(qr, "succeeded", False)
                ),
                "results": [_serialize_query(qr) for qr in results],
            }
        )

    return {
        "data_only": True,
        "trace_id": getattr(result, "trace_id", ""),
        "elapsed_ms": getattr(result, "elapsed_ms", 0.0),
        "errors": list(getattr(result, "errors", []) or []),
        "audit": audit,
        # Deterministic headline numbers (full-day windows) from the facts
        # pack — hosts quote these verbatim instead of recomputing headlines.
        "facts": build_facts([q for p in packs for q in p["results"]]),
        "pack_count": len(packs),
        "packs": packs,
        # LLM-graded analyses when the full pipeline ran; on the data-only path
        # (no analyses) a deterministic per-domain summary instead — no LLM, no
        # heuristics, ``kind == "data_only_summary"`` (see _data_only_summaries).
        "domain_analyses": (
            to_jsonable(getattr(result, "domain_analyses", []) or [])
            or _data_only_summaries(packs, pack_domains)
        ),
    }


def _data_only_summaries(
    packs: list[dict[str, Any]], pack_domains: list[str]
) -> list[dict[str, Any]]:
    """Deterministic per-domain starting point for a data-only run.

    One entry per domain (first-seen pack order): its packs, query outcome
    counts, per-query row counts, and pointers to the rows — ``data_paths``
    into this envelope (``data.packs[i]``) and ``raw_paths`` relative to
    ``--out-dir`` (``raw/<pack>.json``, written only when an out-dir is set).
    Counts only: no grade, no findings, no heuristic or LLM judgement.
    """
    by_domain: dict[str, dict[str, Any]] = {}
    for index, (pack, domain) in enumerate(zip(packs, pack_domains, strict=True)):
        entry = by_domain.setdefault(
            domain,
            {
                "kind": "data_only_summary",
                "domain": domain,
                "packs": [],
                "queries": 0,
                "succeeded": 0,
                "skipped": 0,
                "failed": 0,
                "rows_total": 0,
                "nonempty_query_ids": [],
                "limit_reached_ids": [],
                "query_row_counts": {},
                "data_paths": [],
                "raw_paths": [],
            },
        )
        pack_key = str(pack["pack"] or domain)
        entry["packs"].append(pack_key)
        entry["data_paths"].append(f"data.packs[{index}]")
        entry["raw_paths"].append(f"raw/{_safe_pack_name(pack_key)}.json")
        for q in pack["results"]:
            entry["queries"] += 1
            status = q["status"]
            if status in ("succeeded", "skipped", "failed"):
                entry[status] += 1
            rows = len(q["rows"])
            entry["rows_total"] += rows
            entry["query_row_counts"][q["query_id"]] = q["row_count"]
            if status == "succeeded" and rows:
                entry["nonempty_query_ids"].append(q["query_id"])
            if q["limit_reached"]:
                entry["limit_reached_ids"].append(q["query_id"])
    return list(by_domain.values())


def _safe_pack_name(name: str) -> str:
    """Return a filesystem-safe stem for a pack name."""
    safe = re.sub(r"[/\\:*?\"<>|()\s]+", "_", name or "unknown")
    return re.sub(r"_+", "_", safe).strip("_").lower() or "unknown"


def _pack_key(pr: Any) -> str:
    return getattr(pr, "pack_id", None) or getattr(pr, "domain", None) or "unknown"


def write_pack_file(pr: Any, out_dir: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Write one pack's rows to ``out_dir/raw/<pack>.json``.

    Safe to call as soon as the pack finishes (incremental writes during a run)
    and again at the end — the file is rewritten whole each time.

    Returns:
        ``(manifest_entry, serialized_queries)`` for the pack.
    """
    raw_dir = Path(out_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pack_key = _pack_key(pr)
    results = getattr(pr, "results", []) or []
    serialized = [_serialize_query(qr) for qr in results]
    stem = _safe_pack_name(pack_key)
    (raw_dir / f"{stem}.json").write_text(
        json.dumps(
            {
                "pack": pack_key,
                "domain": getattr(pr, "domain", None),
                "results": serialized,
            },
            indent=2,
            default=str,
        )
    )
    entry = {
        "pack": pack_key,
        "domain": getattr(pr, "domain", None),
        "queries": len(results),
        "succeeded": sum(1 for qr in results if getattr(qr, "succeeded", False)),
        "rows_total": sum(len(q["rows"]) for q in serialized),
        "truncated": any(q["truncated"] for q in serialized),
        "limit_reached": any(q["limit_reached"] for q in serialized),
        "path": f"raw/{stem}.json",
    }
    return entry, serialized


def write_facts_file(results: Any, out_dir: str) -> dict[str, Any]:
    """Build facts from ``results`` (QueryResults) and write ``out_dir/facts.json``.

    Called early with just the facts pack (so headlines are on disk as soon as
    that pack finishes) and again at the end with every query (the final file
    then also carries any ``fallbacks`` sourced from other packs).
    """
    facts = build_facts([_serialize_query(qr) for qr in (results or [])])
    _write_facts(facts, out_dir)
    return facts


def _write_facts(facts: dict[str, Any], out_dir: str) -> None:
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "facts.json").write_text(json.dumps(facts, indent=2, default=str))


def write_result_files(result: Any, out_dir: str) -> dict[str, Any]:
    """Write each pack's rows to ``out_dir/raw/<pack>.json`` and the final
    ``out_dir/facts.json``; return a manifest.

    Note: ``rows_total`` counts the emitted (capped at ``_MAX_ROWS_PER_QUERY``)
    rows, not the untruncated workspace total; the ``truncated`` flag signals
    when capping occurred.
    """
    manifest: list[dict[str, Any]] = []
    all_serialized: list[dict[str, Any]] = []
    for pr in getattr(result, "pack_results", []) or []:
        entry, serialized = write_pack_file(pr, out_dir)
        manifest.append(entry)
        all_serialized.extend(serialized)

    facts = build_facts(all_serialized)
    _write_facts(facts, out_dir)
    return {
        "out_dir": out_dir,
        "facts": facts,
        "facts_path": "facts.json",
        "manifest": manifest,
        "errors": list(getattr(result, "errors", []) or []),
    }
