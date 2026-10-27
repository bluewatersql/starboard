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
import os
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from starboard_core.engagement.evidence import EvidenceItem, record_evidence
from starboard_core.engagement.policy import StorageDecision, StoragePolicy
from starboard_core.engagement.records import StorageRef
from starboard_core.engagement.sink import ArtifactSink, LocalDirSink
from starboard_core.engagement.stdout_budget import encoded_size

from starboard_x.contract import to_jsonable
from starboard_x.discovery._facts import build_facts

# Per-query row cap for the emitted data. Discovery packs are curated aggregate
# scans (small result sets by design); this is a safety net against pathological
# outputs. When exceeded, the query's ``truncated`` flag is set. (Distinct from
# ``limit_reached``, which flags a query capped by its own SQL ``LIMIT``.)
_MAX_ROWS_PER_QUERY = 10_000

# Concurrent pack uploads on a Drive sink (bounded: Drive per-user rate limits).
_UPLOAD_WORKERS = 6

_JSON_MIME = "application/json"

#: ``method_version`` recorded on the evidence discovery writes.
METHOD_VERSION = "discovery_v1"

#: Decision behind a plain local ``out_dir`` (the public path, unchanged).
_LOCAL_DECISION = StorageDecision(
    StoragePolicy.LOCAL, False, "local output directory (public path)"
)


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


def _encode_json(payload: Any) -> bytes:
    """Bytes of the historical ``--out-dir`` encoding (``indent=2``, ``default=str``)."""
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def _as_sink(dest: str | os.PathLike[str] | ArtifactSink) -> ArtifactSink:
    """A local path becomes a :class:`LocalDirSink`; a sink is used as is."""
    if isinstance(dest, str | os.PathLike):
        return LocalDirSink(dest, decision=_LOCAL_DECISION)
    return dest


def _rel(prefix: str, name: str) -> str:
    return f"{prefix.strip('/')}/{name}" if prefix.strip("/") else name


def _write_pack(
    pr: Any, sink: ArtifactSink, prefix: str
) -> tuple[dict[str, Any], list[dict[str, Any]], StorageRef]:
    pack_key = _pack_key(pr)
    results = getattr(pr, "results", []) or []
    serialized = [_serialize_query(qr) for qr in results]
    stem = _safe_pack_name(pack_key)
    ref = sink.put_bytes(
        _rel(prefix, f"raw/{stem}.json"),
        _encode_json(
            {
                "pack": pack_key,
                "domain": getattr(pr, "domain", None),
                "results": serialized,
            }
        ),
        _JSON_MIME,
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
    return entry, serialized, ref


def _write_packs(
    packs: Sequence[Any], sink: ArtifactSink, prefix: str
) -> list[tuple[dict[str, Any], list[dict[str, Any]], StorageRef]]:
    """:func:`_write_pack` for each pack, in input order.

    On a Drive sink each upload is a few network round trips, so up to
    :data:`_UPLOAD_WORKERS` packs upload at once (the sink and the Drive adapter
    are thread-safe; each pack is a distinct relpath). Results keep input order;
    on failure the first error raised is re-raised (an access refusal, not the
    follow-on "sink refused an earlier write" of the packs behind it).
    """
    workers = min(_UPLOAD_WORKERS, len(packs))
    stems = {_safe_pack_name(_pack_key(pr)) for pr in packs}
    if getattr(sink, "kind", None) != "drive" or workers < 2 or len(stems) < len(packs):
        # Serial: not Drive, one pack, or two packs share a file (write in order).
        return [_write_pack(pr, sink, prefix) for pr in packs]
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="discovery-upload"
    ) as pool:
        futures = [pool.submit(_write_pack, pr, sink, prefix) for pr in packs]
        first: BaseException | None = None
        for done in as_completed(futures):
            if done.cancelled():  # cancelled behind an earlier failure
                continue
            exc = done.exception()
            if exc is not None and first is None:
                first = exc
                for pending in futures:
                    pending.cancel()
    if first is not None:
        raise first
    return [f.result() for f in futures]


def _in_pack_order(
    refs: Sequence[StorageRef], pack_paths: Sequence[str]
) -> list[StorageRef]:
    """``refs`` with the pack refs (uploaded concurrently) put back in pack order."""
    wanted = set(pack_paths)
    by_path = {r.path: r for r in refs}
    ordered = iter([by_path[p] for p in dict.fromkeys(pack_paths) if p in by_path])
    return [next(ordered) if r.path in wanted else r for r in refs]


def write_pack_file(
    pr: Any, out_dir: str | os.PathLike[str] | ArtifactSink, *, prefix: str = ""
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Write one pack's rows to ``<out_dir>/raw/<pack>.json``.

    ``out_dir`` is a local directory (public path, unchanged bytes) or an
    :class:`~starboard_core.engagement.sink.ArtifactSink` (run-relative; ``prefix``
    nests the layout under a run sub-folder).

    Safe to call as soon as the pack finishes (incremental writes during a run)
    and again at the end — the file is rewritten whole each time.

    Returns:
        ``(manifest_entry, serialized_queries)`` for the pack.
    """
    entry, serialized, _ = _write_pack(pr, _as_sink(out_dir), prefix)
    return entry, serialized


def write_facts_file(
    results: Any, out_dir: str | os.PathLike[str] | ArtifactSink, *, prefix: str = ""
) -> dict[str, Any]:
    """Build facts from ``results`` (QueryResults) and write ``<out_dir>/facts.json``.

    Called early with just the facts pack (so headlines are on disk as soon as
    that pack finishes) and again at the end with every query (the final file
    then also carries any ``fallbacks`` sourced from other packs).
    """
    facts = build_facts([_serialize_query(qr) for qr in (results or [])])
    _as_sink(out_dir).put_bytes(
        _rel(prefix, "facts.json"), _encode_json(facts), _JSON_MIME
    )
    return facts


def write_result_files(
    result: Any,
    out_dir: str | os.PathLike[str] | ArtifactSink,
    *,
    prefix: str = "",
    scope_workspace_ids: Sequence[str] = (),
    source_kind: str = "customer_workspace",
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write each pack's rows to ``raw/<pack>.json`` and the final ``facts.json``;
    return a manifest.

    * ``out_dir`` a **local path** (public path): only ``raw/*`` and ``facts.json`` are
      written, byte-identical to earlier releases. The return value carries
      ``out_dir``.
    * ``out_dir`` an **artifact sink** (covered / Drive runs): the full run layout is
      written run-relative (under ``prefix``): ``raw/<pack>.json``, ``facts.json``,
      ``manifest.json`` (the return value) and ``discovery.json`` (``envelope``, or
      the serialized result). On a Drive sink every object is appended to
      ``evidence/index.json`` as an ``EvidenceRef`` scoped to
      ``scope_workspace_ids``, and the return value carries ``refs``.

    Note: ``rows_total`` counts the emitted (capped at ``_MAX_ROWS_PER_QUERY``)
    rows, not the untruncated workspace total; the ``truncated`` flag signals
    when capping occurred.
    """
    sink = _as_sink(out_dir)
    layout = not isinstance(out_dir, str | os.PathLike)
    manifest: list[dict[str, Any]] = []
    all_serialized: list[dict[str, Any]] = []
    evidence: list[EvidenceItem] = []
    for entry, serialized, ref in _write_packs(
        list(getattr(result, "pack_results", []) or []), sink, prefix
    ):
        manifest.append(entry)
        all_serialized.extend(serialized)
        evidence.append(
            (ref, f"discovery:{entry['pack']}", entry["rows_total"], entry["truncated"])
        )

    facts = build_facts(all_serialized)
    facts_ref = sink.put_bytes(
        _rel(prefix, "facts.json"), _encode_json(facts), _JSON_MIME
    )
    evidence.append((facts_ref, "discovery:facts", None, False))
    out: dict[str, Any] = {} if layout else {"out_dir": out_dir}
    out.update(
        {
            "facts": facts,
            "facts_path": "facts.json",
            "manifest": manifest,
            "errors": list(getattr(result, "errors", []) or []),
        }
    )
    if not layout:
        return out
    manifest_ref = sink.put_bytes(
        _rel(prefix, "manifest.json"), _encode_json(out), _JSON_MIME
    )
    envelope_ref = sink.put_bytes(
        _rel(prefix, "discovery.json"),
        _encode_json(serialize_result(result) if envelope is None else envelope),
        _JSON_MIME,
    )
    evidence.append((manifest_ref, "discovery:manifest", None, False))
    evidence.append(
        (
            envelope_ref,
            "discovery:envelope",
            sum(e["rows_total"] for e in manifest),
            any(e["truncated"] for e in manifest),
        )
    )
    record_evidence(
        sink,
        evidence,
        source_kind=source_kind,
        scope=scope_workspace_ids,
        method_version=METHOD_VERSION,
    )
    pack_paths = [item[0].path for item in evidence[: len(manifest)]]
    return {
        **out,
        "refs": [r.to_dict() for r in _in_pack_order(sink.refs(), pack_paths)],
    }


def write_envelope_file(
    envelope: Mapping[str, Any],
    sink: ArtifactSink,
    relpath: str,
    *,
    scope_workspace_ids: Sequence[str] = (),
    source_kind: str = "customer_workspace",
) -> list[dict[str, Any]]:
    """Write the full discovery envelope to ``relpath`` of a sink (``--output-path``).

    On a Drive sink the object is recorded as evidence. Returns the refs written.
    """
    ref = sink.put_bytes(relpath, _encode_json(envelope), _JSON_MIME)
    record_evidence(
        sink,
        [(ref, "discovery:envelope", None, False)],
        source_kind=source_kind,
        scope=scope_workspace_ids,
        method_version=METHOD_VERSION,
    )
    return [r.to_dict() for r in sink.refs()]


#: The manifest keys a summary keeps per pack once the full entries no longer fit.
SUMMARY_PACK_KEYS = ("pack", "succeeded", "queries", "rows_total", "truncated", "path")


def fit_summary(payload: Mapping[str, Any], *, max_bytes: int) -> dict[str, Any]:
    """A run-folder discovery summary shrunk so the headline ``facts`` give way last.

    :func:`~starboard_core.engagement.stdout_budget.bound` caps every list alike, so
    a many-pack run lost the facts' lists (``product_mix``, ``top_jobs``) to the pack
    refs and manifest. Those are re-readable from the run folder, so they shrink
    first, while over ``max_bytes``: each manifest entry to :data:`SUMMARY_PACK_KEYS`,
    then the pack refs (the count is ``pack_refs_omitted``; the manifest ref lists
    every pack's path). The caller bounds whatever is still over.
    """
    if encoded_size(payload) <= max_bytes:
        return dict(payload)
    summary = dict(payload.get("summary") or {})
    packs = summary.get("packs") or []
    summary["packs"] = [
        {k: entry.get(k) for k in SUMMARY_PACK_KEYS} if isinstance(entry, dict) else entry
        for entry in packs
    ]
    fitted: dict[str, Any] = {**payload, "summary": summary}
    if encoded_size(fitted) <= max_bytes:
        return fitted
    prefix = summary.get("layout_prefix") or ""
    pack_paths = {
        f"{prefix}/{entry['path']}" if prefix else entry["path"]
        for entry in packs
        if isinstance(entry, dict) and entry.get("path")
    }
    refs = payload.get("refs") or []
    kept = [r for r in refs if r.get("path") not in pack_paths]
    fitted["refs"] = kept
    if len(kept) < len(refs):
        fitted["pack_refs_omitted"] = len(refs) - len(kept)
    return fitted
