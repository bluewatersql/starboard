# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Explicit dedupe keys and observation merging (D3-19). Stdlib only.

Mirrored evidence (a customer copy and an internal-mirror copy of one slice) and
known fan-outs (the price catalog replicated per tenant, the ``node_types``
dimension) must count once. Every kind names its key fields explicitly in
:data:`DEDUPE_KEYS`; nothing is de-duplicated by "all columns".

Duplicates never count as independent corroboration: callers count dedupe groups,
not evidence IDs.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from starboard_core.engagement.evidence import SOURCE_KIND_ORDER
from starboard_core.engagement.records import Observation

__all__ = [
    "AGGREGATE_KEY_PREFIX",
    "DEDUPE_KEYS",
    "DedupeResult",
    "MergeResult",
    "dedupe_rows",
    "job_aggregate_dedupe_key",
    "merge",
    "merge_observations",
    "observation_dedupe_key",
]

#: Key fields per dedupe kind. ``observation`` is the fallback key used when an
#: observation has no ``dedupe_key`` (its comparison key + interval + method).
DEDUPE_KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "job_run": ("workspace_id", "job_id", "run_id"),
        "job_aggregate_slice": (
            "workspace_id",
            "job_id",
            "window_start",
            "window_end",
            "method_version",
        ),
        # The catalog is replicated per tenant: dedupe, then join on sku+cloud+unit.
        "price_catalog": ("sku_name", "cloud", "usage_unit", "price_start_time"),
        # The dimension fans out (one copy per tenant / region).
        "node_type": ("node_type",),
        "billing_usage": ("record_id",),
        "observation": (
            "account_key",
            "workspace_id",
            "family",
            "entity_kind",
            "entity_id",
            "metric",
            "interval_start",
            "interval_end",
            "method_version",
        ),
    }
)

#: Tenant-identity columns of replicated rows. They are not compared when they are
#: not part of the key, so per-tenant replicas of one catalog row collapse.
_TENANT_FIELDS: frozenset[str] = frozenset({"account_id", "workspace_id"})

#: ``dedupe_key`` prefix that marks an F-12 per-job aggregate observation.
AGGREGATE_KEY_PREFIX = "job_aggregate_slice|"

_COVERAGE_RANK = {"complete": 0, "partial": 1, "unknown": 2}
_AUDIENCE_RANK = {"internal_only": 0, "customer_shareable": 1}


@dataclass(frozen=True)
class DedupeResult:
    """Outcome of :func:`dedupe_rows`.

    Attributes:
        unique: One row per non-conflicting key, in first-seen order.
        duplicates: Rows dropped as exact copies of a kept row.
        conflicts: Keys whose rows disagreed on a compared value (group dropped).
    """

    unique: tuple[Mapping[str, Any], ...]
    duplicates: int
    conflicts: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True)
class MergeResult:
    """Outcome of :func:`merge`.

    Attributes:
        observations: The merged observations, in first-seen order.
        superseded: ``(kept_observation_id, superseded_aggregate)`` pairs (the
            superseded F-12 value goes to ``ChangeInput.co_movements``).
    """

    observations: tuple[Observation, ...]
    superseded: tuple[tuple[str, Observation], ...] = ()


def _key_fields(kind: str) -> tuple[str, ...]:
    try:
        return DEDUPE_KEYS[kind]
    except KeyError:
        raise ValueError(f"unknown dedupe kind {kind!r}") from None


def dedupe_rows(kind: str, rows: Iterable[Mapping[str, Any]]) -> DedupeResult:
    """De-duplicate ``rows`` by the explicit key fields of ``kind``.

    Rows with the same key and the same compared values collapse to the first.
    Rows with the same key and different compared values are a conflict: the whole
    group is dropped and its key is reported (callers mark the result
    ``coverage=partial`` with uncertainty ``source_conflict``).
    """
    key_fields = _key_fields(kind)
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        missing = [f for f in key_fields if f not in row]
        if missing:
            raise ValueError(
                f"{kind} row is missing key field(s): {', '.join(missing)}"
            )
        groups.setdefault(tuple(row[f] for f in key_fields), []).append(row)

    skip = set(key_fields) | (_TENANT_FIELDS - set(key_fields))
    unique: list[Mapping[str, Any]] = []
    conflicts: list[tuple[Any, ...]] = []
    duplicates = 0
    for key, group in groups.items():
        values = {_compared(row, skip) for row in group}
        if len(values) > 1:
            conflicts.append(key)
            continue
        unique.append(group[0])
        duplicates += len(group) - 1
    return DedupeResult(
        unique=tuple(unique), duplicates=duplicates, conflicts=tuple(conflicts)
    )


def _compared(row: Mapping[str, Any], skip: set[str]) -> str:
    return repr(sorted((k, repr(v)) for k, v in row.items() if k not in skip))


# ---- observations ----------------------------------------------------------------


def observation_dedupe_key(o: Observation) -> str:
    """``o.dedupe_key``, else the ``observation`` kind key joined with ``|``."""
    if o.dedupe_key:
        return o.dedupe_key
    return "|".join(str(getattr(o, f)) for f in DEDUPE_KEYS["observation"])


def job_aggregate_dedupe_key(
    workspace_id: str,
    job_id: str,
    window_start: str,
    window_end: str,
    method_version: str,
) -> str:
    """The ``dedupe_key`` of an F-12 per-job aggregate observation.

    The prefix marks the observation as an aggregate, which a run-level value for
    the same job and interval supersedes in :func:`merge`.
    """
    return AGGREGATE_KEY_PREFIX + "|".join(
        (workspace_id, job_id, window_start, window_end, method_version)
    )


def _is_aggregate(o: Observation) -> bool:
    return bool(o.dedupe_key and o.dedupe_key.startswith(AGGREGATE_KEY_PREFIX))


def _same_value(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def _combine(group: Sequence[Observation]) -> Observation:
    """Merge copies of one observation (same ``observation_id``)."""
    if len(group) == 1:
        return group[0]
    measured = [o for o in group if o.state == "measured"]
    pool = measured or list(group)
    first = pool[0]
    if len(pool) == 1:
        return first
    evidence = tuple(dict.fromkeys(e for o in group for e in o.evidence_ids))
    source = min((o.source_kind for o in group), key=SOURCE_KIND_ORDER.index)
    audience = min((o.audience_class for o in group), key=_AUDIENCE_RANK.__getitem__)
    as_of = max(o.as_of for o in group)
    if measured and not all(_same_value(o.value, first.value) for o in pool):
        return replace(
            first,
            value=None,
            state="unknown",
            unknown_reason="source_conflict",
            coverage="unknown",
            coverage_fraction=None,
            evidence_ids=evidence,
            source_kind=source,
            audience_class=audience,
            as_of=as_of,
        )
    coverage = max((o.coverage for o in pool), key=_COVERAGE_RANK.__getitem__)
    fractions = [o.coverage_fraction for o in pool if o.coverage_fraction is not None]
    return replace(
        first,
        coverage=coverage,
        coverage_fraction=min(fractions) if fractions else None,
        evidence_ids=evidence,
        source_kind=source,
        audience_class=audience,
        as_of=as_of,
    )


def merge(observations: Iterable[Observation]) -> MergeResult:
    """Merge mirrored copies and apply per-job run-level supersession (D3-19).

    Observations are grouped by ``observation_id`` (entity, metric, interval and
    method). Within a group:

    - for ``entity_kind == "job"``, a measured run-level copy supersedes F-12
      aggregate copies (marked by :func:`job_aggregate_dedupe_key`); so does a
      run-level ``source_conflict`` unknown (unequal copies of the same run must
      not fall back to the capped aggregate, spec §I); a run-level unknown for
      another reason (e.g. an uncovered job) does not; workspace-grain values are
      never superseded;
    - equal values merge: evidence IDs are united and ``source_kind`` is the most
      restrictive by ``SOURCE_KIND_ORDER``;
    - unequal values give ``state=unknown`` with ``unknown_reason="source_conflict"``;
    - a measured copy is preferred over an unknown copy.
    """
    groups: dict[str, list[Observation]] = {}
    for o in observations:
        groups.setdefault(o.observation_id, []).append(o)

    merged: list[Observation] = []
    superseded: list[tuple[str, Observation]] = []
    for group in groups.values():
        dropped: list[Observation] = []
        if group[0].entity_kind == "job":
            run_level = [
                o
                for o in group
                if not _is_aggregate(o)
                and (o.state == "measured" or o.unknown_reason == "source_conflict")
            ]
            if run_level:
                dropped = [o for o in group if _is_aggregate(o)]
                group = [o for o in group if not _is_aggregate(o)]
        kept = _combine(group)
        merged.append(kept)
        superseded.extend((kept.observation_id, o) for o in dropped)
    return MergeResult(observations=tuple(merged), superseded=tuple(superseded))


def merge_observations(observations: Iterable[Observation]) -> tuple[Observation, ...]:
    """The merged observations of :func:`merge`."""
    return merge(observations).observations
