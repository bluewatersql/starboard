# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Observation adapters over existing evidence.

Pure functions, no I/O. They map a findings-manifest 2.0 dict to
:class:`~starboard_core.engagement.records.Observation` records. ``family`` is
the rule's family from the rule registry
(:func:`starboard_core.domain.rules.rule_family`), ``"unclassified"`` for an
untagged or unknown rule. The six-family metric producers over discovery facts,
reliability reconstructions and rule coverage live in
:mod:`starboard_core.engagement.families`.

Findings use the presence-flag convention of
:mod:`starboard_core.engagement.history`: ``metric="finding_present"``,
``unit="flag"``, ``1.0`` when present. A prior triggered finding absent from a
non-degraded manifest becomes a measured ``0.0`` (so selection can say
``recovered``); on a degraded manifest it is ``unknown``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from starboard_core.domain.rules import RuleRegistry, rule_family
from starboard_core.engagement.history import TRIGGER_UNIT
from starboard_core.engagement.records import (
    RUN_RATE_RULES,
    UNCLASSIFIED,
    Observation,
    audience_class_for,
    observation_id,
)

__all__ = [
    "FINDINGS_METHOD",
    "build_observation",
    "composite_key",
    "from_findings_manifest",
]

FINDINGS_METHOD = "findings_manifest_v2"
_MANIFEST_VERSION = "2.0"
_PRESENT = "finding_present"
_GRAIN = "interval"


def build_observation(
    *,
    run_id: str,
    account_key: str,
    workspace_id: str,
    family: str,
    entity_kind: str,
    entity_id: str,
    metric: str,
    value: float | None,
    unit: str,
    method_version: str,
    interval: tuple[str, str],
    as_of: str,
    coverage: str,
    evidence_ids: Sequence[str],
    source_kind: str,
    unknown_reason: str | None = None,
    dedupe_key: str | None = None,
    uncertainty: Sequence[str] = (),
) -> Observation:
    """Build an :class:`Observation` with its derived ``observation_id``.

    ``value=None`` makes it ``unknown`` (coverage ``unknown``, ``unknown_reason``
    defaulting to ``unavailable``); otherwise it is ``measured``.
    """
    key = (
        account_key,
        workspace_id,
        family,
        entity_kind,
        entity_id,
        metric,
        interval[0],
        interval[1],
        method_version,
    )
    unknown = value is None
    return Observation(
        observation_id=observation_id(key),
        run_id=run_id,
        account_key=account_key,
        workspace_id=workspace_id,
        family=family,
        entity_kind=entity_kind,
        entity_id=entity_id,
        metric=metric,
        value=value,
        unit=unit,
        grain=_GRAIN,
        method_version=method_version,
        interval_start=interval[0],
        interval_end=interval[1],
        as_of=as_of,
        coverage="unknown" if unknown else coverage,
        coverage_fraction=None,
        state="unknown" if unknown else "measured",
        unknown_reason=(unknown_reason or "unavailable") if unknown else None,
        evidence_ids=tuple(evidence_ids),
        source_kind=source_kind,
        audience_class=audience_class_for(source_kind),
        dedupe_key=dedupe_key,
        uncertainty=tuple(uncertainty),
    )


def composite_key(entry: Mapping[str, Any]) -> str:
    """A findings-manifest entry's identity: its ``composite_key``, else
    ``rule_id::entity_id``, else its ``id``. Raises ``ValueError`` without one.
    """
    key = entry.get("composite_key")
    if isinstance(key, str) and key:
        return key
    rule_id, entity_id = entry.get("rule_id"), entry.get("entity_id")
    if rule_id and entity_id:
        return f"{rule_id}::{entity_id}"
    fid = entry.get("id")
    if not isinstance(fid, str) or not fid:
        raise ValueError("findings-manifest entry needs an id or composite_key")
    return fid


def _family(entry: Mapping[str, Any], registry: RuleRegistry | None) -> str:
    rule_id = entry.get("rule_id")
    if not isinstance(rule_id, str) or not rule_id:
        return UNCLASSIFIED
    return rule_family(rule_id, registry)


def from_findings_manifest(
    manifest: Mapping[str, Any],
    *,
    run_id: str,
    account_key: str,
    workspace_id: str,
    interval: tuple[str, str],
    evidence_ids: Sequence[str],
    source_kind: str = "customer_workspace",
    as_of: str | None = None,
    prior: Iterable[Observation] = (),
    registry: RuleRegistry | None = None,
) -> tuple[Observation, ...]:
    """Map a findings-manifest 2.0 dict to observations.

    One ``finding_present`` observation per ``composite_key`` (deduplicated),
    plus ``evidence_dbu_estimate`` (unit ``DBU``; ``DBU/day`` for a run-rate rule
    in ``RUN_RATE_RULES``) when the entry has one.
    Coverage is ``partial`` when the entry's evidence was capped or its
    category is in ``unavailable_domains``.

    Args:
        prior: Earlier observations; each triggered ``finding_present`` of the
            same account and workspace whose key is absent here yields a clear
            (``0.0``) observation, or an ``unknown`` one when the manifest is
            degraded.
        registry: Rule registry for ``family`` (default: the seed rules); a
            rule it does not know, or one without a family, is ``unclassified``.

    Raises:
        ValueError: For a non-2.0 manifest or malformed findings.
    """
    if manifest.get("snapshot_version") != _MANIFEST_VERSION:
        raise ValueError(
            f"findings manifest must be snapshot_version {_MANIFEST_VERSION!r}, "
            f"got {manifest.get('snapshot_version')!r}"
        )
    findings = manifest.get("findings") or ()
    if not isinstance(findings, (list, tuple)):
        raise ValueError("findings manifest 'findings' must be a list")
    unavailable_domains = set(manifest.get("unavailable_domains") or ())
    run_date = manifest.get("run_date")
    stamp = as_of or (
        run_date if isinstance(run_date, str) and run_date else interval[1]
    )
    common: dict[str, Any] = {
        "run_id": run_id,
        "account_key": account_key,
        "workspace_id": workspace_id,
        "entity_kind": "finding",
        "method_version": FINDINGS_METHOD,
        "interval": interval,
        "as_of": stamp,
        "evidence_ids": evidence_ids,
        "source_kind": source_kind,
    }

    out: list[Observation] = []
    seen: set[str] = set()
    for entry in findings:
        if not isinstance(entry, Mapping):
            raise ValueError("findings manifest entries must be objects")
        key = composite_key(entry)
        if key in seen:
            continue
        seen.add(key)
        partial = (
            bool(entry.get("evidence_capped"))
            or entry.get("category") in unavailable_domains
        )
        coverage = "partial" if partial else "complete"
        family = _family(entry, registry)
        out.append(
            build_observation(
                **common,
                family=family,
                entity_id=key,
                metric=_PRESENT,
                value=1.0,
                unit=TRIGGER_UNIT,
                coverage=coverage,
            )
        )
        dbu = entry.get("evidence_dbu_estimate")
        if isinstance(dbu, (int, float)) and not isinstance(dbu, bool):
            out.append(
                build_observation(
                    **common,
                    family=family,
                    entity_id=key,
                    metric="evidence_dbu_estimate",
                    value=float(dbu),
                    unit="DBU/day" if entry.get("rule_id") in RUN_RATE_RULES else "DBU",
                    coverage=coverage,
                )
            )

    degraded = bool(manifest.get("degraded"))
    for p in prior:
        if (
            p.metric != _PRESENT
            or p.method_version != FINDINGS_METHOD
            or p.account_key != account_key
            or p.workspace_id != workspace_id
            or p.value is None
            or p.value < 0.5
            or p.entity_id in seen
        ):
            continue
        seen.add(p.entity_id)
        out.append(
            build_observation(
                **common,
                family=p.family,
                entity_id=p.entity_id,
                metric=_PRESENT,
                value=None if degraded else 0.0,
                unit=TRIGGER_UNIT,
                coverage="complete",
                unknown_reason="finding absent but the manifest is degraded",
            )
        )
    return tuple(out)
