# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Load a saved discovery run as Workload Review evidence (``review --from-discovery``).

Discovery (``starboard --discover … --out-dir <run>/discovery`` or
``python -m starboard_x.discovery --out-dir …``) already executed the same
query-pack queries a review needs and saved them per ``query_id``:

* ``raw/<pack>.json`` — ``{pack, domain, results[]}`` (preferred), and
* ``discovery.json`` — the envelope (``data.packs[].results[]``), which also
  carries ``source`` / ``scope`` / ``lookback_days`` on the ``starboard
  --discover`` path (fallback for rows; sole source of run-level provenance).

Each result carries ``status`` (``succeeded`` / ``skipped`` / ``failed``),
``rows``, ``row_limit``, ``limit_reached`` and ``lookback_days``. Loading is
pure file I/O (stdlib only): no query runs and no workspace is contacted.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ENVELOPE_FILE = "discovery.json"
_RAW_DIR = "raw"


class DiscoveryEvidenceError(ValueError):
    """The ``--from-discovery`` path is missing, unreadable, or has no results."""


@dataclass(frozen=True)
class DiscoveryEvidence:
    """Per-``query_id`` discovery results plus the run's scope/lookback provenance.

    Attributes:
        path: The discovery directory the evidence was loaded from.
        envelope_file: The ``discovery.json`` read for provenance (``None`` when
            the run dir has only ``raw/`` — e.g. the public ``starboard_x`` path).
        results: Serialized query results keyed by ``query_id``.
        source: Discovery source label from the envelope (``None`` if absent).
        workspace_ids: Workspace ids the discovery was scoped to (may be empty).
        account: Account id the discovery was scoped to (``None`` if absent).
        lookback_days: The discovery run's lookback (envelope value, else the
            most common per-query ``lookback_days``).
        generated_at: When the discovery output was produced (envelope value if
            present, else the envelope/raw file modification time, ISO-8601 UTC).
        window: The facts headline window (``facts.window``) when present.
    """

    path: str
    envelope_file: str | None
    results: dict[str, dict[str, Any]]
    source: str | None = None
    workspace_ids: tuple[str, ...] = ()
    account: str | None = None
    lookback_days: int | None = None
    generated_at: str | None = None
    window: dict[str, Any] | None = field(default=None)

    @property
    def skipped_query_ids(self) -> tuple[str, ...]:
        """Sorted ``query_id`` values the discovery run skipped (any pack)."""
        return tuple(
            sorted(q for q, r in self.results.items() if result_status(r) == "skipped")
        )

    def provenance(self) -> dict[str, Any]:
        """The ``evidence_source`` record for the review JSON / findings-manifest."""
        return {
            "kind": "discovery",
            "path": self.path,
            "envelope_file": self.envelope_file,
            "discovery_source": self.source,
            "discovery_generated_at": self.generated_at,
            "discovery_window": self.window,
            "lookback_days": self.lookback_days,
            "workspace_ids": list(self.workspace_ids),
            "account": self.account,
        }


def result_status(result: dict[str, Any]) -> str:
    """Three-state status of a serialized result (derives it for older output)."""
    status = result.get("status")
    if isinstance(status, str) and status:
        return status
    return "succeeded" if result.get("succeeded") else "failed"


def _read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise DiscoveryEvidenceError(f"could not read {path}: {exc}") from exc


def _resolve_layout(path: str | Path) -> tuple[Path, Path | None]:
    """Return ``(discovery_dir, envelope_file_or_None)`` for a dir or json path."""
    p = Path(path).expanduser()
    if p.is_file():
        return p.parent, p
    if not p.is_dir():
        raise DiscoveryEvidenceError(f"discovery output not found: {p}")
    # Tolerate the run dir (``<run>/discovery``) as well as the discovery dir.
    if (
        not (p / _ENVELOPE_FILE).is_file()
        and not (p / _RAW_DIR).is_dir()
        and (p / "discovery").is_dir()
    ):
        p = p / "discovery"
    envelope = p / _ENVELOPE_FILE
    return p, (envelope if envelope.is_file() else None)


def _iter_results(container: Any) -> list[dict[str, Any]]:
    results = container.get("results") if isinstance(container, dict) else None
    return [r for r in (results or []) if isinstance(r, dict) and r.get("query_id")]


def load_discovery_evidence(path: str | Path) -> DiscoveryEvidence:
    """Load discovery output (dir or ``discovery.json``) as review evidence.

    Rows come from ``raw/<pack>.json`` first; any ``query_id`` absent there is
    filled from ``discovery.json`` ``data.packs[].results[]``.

    Raises:
        DiscoveryEvidenceError: The path is missing/unreadable, the envelope is
            an error envelope, or no query results were found.
    """
    base, envelope_file = _resolve_layout(path)

    data: dict[str, Any] = {}
    if envelope_file is not None:
        payload = _read_json(envelope_file)
        if not isinstance(payload, dict):
            raise DiscoveryEvidenceError(f"{envelope_file} is not a JSON object")
        if payload.get("ok") is False:
            raise DiscoveryEvidenceError(
                f"{envelope_file} is an error envelope: {payload.get('error')}"
            )
        inner = payload.get("data")
        data = inner if isinstance(inner, dict) else payload

    results: dict[str, dict[str, Any]] = {}
    raw_dir = base / _RAW_DIR
    newest_mtime: float | None = None
    if raw_dir.is_dir():
        for raw_file in sorted(raw_dir.glob("*.json")):
            for result in _iter_results(_read_json(raw_file)):
                results.setdefault(str(result["query_id"]), result)
            raw_mtime = raw_file.stat().st_mtime
            newest_mtime = (
                raw_mtime if newest_mtime is None else max(newest_mtime, raw_mtime)
            )
    for pack in data.get("packs") or []:
        for result in _iter_results(pack):
            results.setdefault(str(result["query_id"]), result)

    if not results:
        raise DiscoveryEvidenceError(
            f"no discovery query results found under {base} "
            f"(expected {_RAW_DIR}/<pack>.json or {_ENVELOPE_FILE})"
        )

    raw_scope = data.get("scope")
    scope: dict[str, Any] = raw_scope if isinstance(raw_scope, dict) else {}
    workspace_ids = tuple(str(w) for w in (scope.get("workspace_ids") or []) if w)
    account = scope.get("account")

    lookback = data.get("lookback_days")
    if not isinstance(lookback, int) or isinstance(lookback, bool):
        per_query = Counter(
            r["lookback_days"]
            for r in results.values()
            if isinstance(r.get("lookback_days"), int)
        )
        lookback = per_query.most_common(1)[0][0] if per_query else None

    generated_at = data.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        mtime: float | None = (
            envelope_file.stat().st_mtime if envelope_file is not None else newest_mtime
        )
        generated_at = (
            datetime.fromtimestamp(mtime, UTC).isoformat() if mtime is not None else None
        )

    facts = data.get("facts")
    window = facts.get("window") if isinstance(facts, dict) else None

    return DiscoveryEvidence(
        path=str(base),
        envelope_file=str(envelope_file) if envelope_file is not None else None,
        results=results,
        source=data.get("source") if isinstance(data.get("source"), str) else None,
        workspace_ids=workspace_ids,
        account=str(account) if account else None,
        lookback_days=lookback,
        generated_at=generated_at,
        window=window if isinstance(window, dict) else None,
    )


__all__ = [
    "DiscoveryEvidence",
    "DiscoveryEvidenceError",
    "load_discovery_evidence",
    "result_status",
]
