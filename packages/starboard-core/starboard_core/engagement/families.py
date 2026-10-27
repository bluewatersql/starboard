# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Six-family observation producers (phase 3 spec §C, D3-6, D3-18).

Pure functions, no I/O. Each maps one evidence shape to
:class:`~starboard_core.engagement.records.Observation` records whose
``(family, metric, entity_kind, unit)`` come from
:data:`starboard_core.engagement.catalog.FAMILY_METRICS`:

- :func:`from_facts` — a discovery ``facts`` dict (``starboard_x.discovery``).
  Workspace reliability comes only from F-06 (``job_reliability``); per-job
  reliability from F-12 (``job_reliability_by_job``) is a top-25 truncation, so
  each per-job observation is ``partial``, carries uncertainty
  ``per_job_cap_25`` and an F-12 aggregate ``dedupe_key``.
- :func:`from_reliability` — a run-level
  :class:`~starboard_core.engagement.jobruns.Reconstruction`, per job only. Its
  observations share the F-12 ``observation_id`` (same family, metric, interval
  and ``job_reliability_v1``), so :func:`~starboard_core.engagement.dedupe.merge`
  lets them supersede the aggregates.
- :func:`rule_coverage` — a findings-manifest 2.0 dict: ``rules_evaluated`` and
  ``active_rule_findings`` per family.

Uncertainty codes ride on ``Observation.uncertainty``; ``dedupe_key`` is
supersession identity only. An unknown observation's ``unknown_reason`` is a short code, e.g. ``missing_source:F-08,F-09``
(query / template IDs to acquire), ``no_runs`` or ``source_conflict``. Never
emits family ``other``. ``DBU`` values are list-price DBU quantities, not ``$``.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from functools import lru_cache
from typing import Any

from starboard_core.domain.rules import (
    DOMAIN_TO_RULE_DOMAIN,
    RuleRegistry,
    rule_family,
)
from starboard_core.engagement.catalog import (
    FAMILY_METRICS,
    METHOD_VERSION,
    SIX_FAMILIES,
)
from starboard_core.engagement.dedupe import job_aggregate_dedupe_key
from starboard_core.engagement.jobruns import (
    METHOD_VERSION as RELIABILITY_METHOD,
)
from starboard_core.engagement.jobruns import (
    UNCERTAINTY_PER_JOB_CAP,
    UNCERTAINTY_SOURCE_CONFLICT,
    Reconstruction,
)
from starboard_core.engagement.observations import build_observation
from starboard_core.engagement.records import Observation

__all__ = [
    "RUN_LEVEL_KEY_PREFIX",
    "from_facts",
    "from_reliability",
    "rule_coverage",
]

#: ``dedupe_key`` prefix of a run-level (reconstructed) per-job observation.
RUN_LEVEL_KEY_PREFIX = "job_run_slices|"

_FACT_ID_RE = re.compile(r"\bF-\d{2}\b")
_RELIABILITY_TEMPLATE = "vt-job-run-states"


# ---- shared helpers ------------------------------------------------------------------


def _unit(family: str, metric: str, entity_kind: str) -> str:
    for spec in FAMILY_METRICS[family]:
        if spec.metric == metric and spec.entity_kind == entity_kind:
            return spec.unit
    raise KeyError(f"{family}.{metric} ({entity_kind}) is not a catalog metric")


def _source(family: str, metric: str, entity_kind: str = "workspace") -> str:
    for spec in FAMILY_METRICS[family]:
        if spec.metric == metric and spec.entity_kind == entity_kind:
            return spec.source
    raise KeyError(f"{family}.{metric} ({entity_kind}) is not a catalog metric")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _share(part: float, whole: float) -> float:
    return round(part / whole * 100.0, 2)


def _missing(ids: Iterable[str]) -> str:
    return "missing_source:" + ",".join(sorted(set(ids)))


# ---- from_facts ----------------------------------------------------------------------


def _window(block: Any, fallback: tuple[str, str]) -> tuple[str, str]:
    window = block.get("window") if isinstance(block, Mapping) else None
    if isinstance(window, Mapping) and window.get("start") and window.get("end"):
        return str(window["start"]), str(window["end"])
    return fallback


def from_facts(
    facts: Mapping[str, Any],
    *,
    run_id: str,
    account_key: str,
    workspace_id: str,
    source_kind: str,
    evidence_ids: Sequence[str],
    as_of: str | None = None,
) -> tuple[Observation, ...]:
    """Map a discovery ``facts`` dict to six-family observations.

    The interval is ``facts.window`` (the reliability blocks use their own
    ``window`` when present). A field that is ``None`` yields ``unknown``
    observations with ``missing_source:<fact IDs>`` (the IDs named in
    ``facts.unavailable[field]``, else the catalog source). A fallback-sourced
    ``top_jobs`` gives ``partial`` coverage, and ``unknown``
    (``window_mismatch:<qid>``) when its window differs from the facts window.

    Raises:
        ValueError: When ``facts.window`` lacks ``start``/``end``.
    """
    window = facts.get("window")
    if (
        not isinstance(window, Mapping)
        or not window.get("start")
        or not window.get("end")
    ):
        raise ValueError("discovery facts need window.start and window.end")
    interval = (str(window["start"]), str(window["end"]))
    unavailable = facts.get("unavailable") or {}
    fallbacks = facts.get("fallbacks") or {}
    stamp = as_of or interval[1]
    out: list[Observation] = []

    def emit(
        family: str,
        metric: str,
        value: float | None,
        *,
        reason: str | None = None,
        coverage: str = "complete",
        entity_kind: str = "workspace",
        entity_id: str = workspace_id,
        ws: str = workspace_id,
        method: str = METHOD_VERSION,
        span: tuple[str, str] = interval,
        dedupe_key: str | None = None,
        uncertainty: Sequence[str] = (),
    ) -> None:
        out.append(
            build_observation(
                run_id=run_id,
                account_key=account_key,
                workspace_id=ws,
                family=family,
                entity_kind=entity_kind,
                entity_id=entity_id,
                metric=metric,
                value=value,
                unit=_unit(family, metric, entity_kind),
                method_version=method,
                interval=span,
                as_of=stamp,
                coverage=coverage,
                evidence_ids=evidence_ids,
                source_kind=source_kind,
                unknown_reason=reason,
                dedupe_key=dedupe_key,
                uncertainty=uncertainty,
            )
        )

    def block(field: str) -> Mapping[str, Any] | None:
        value = facts.get(field)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(f"discovery facts {field!r} must be an object")
        return value

    def items(field: str) -> list[Mapping[str, Any]] | None:
        value = facts.get(field)
        if value is None:
            return None
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"discovery facts {field!r} must be a list")
        return [i for i in value if isinstance(i, Mapping)]

    def missing(field: str, family: str, metric: str) -> str:
        ids = _FACT_ID_RE.findall(str(unavailable.get(field) or ""))
        return _missing(ids or _source(family, metric).split("|"))

    # consumption_trajectory ---------------------------------------------------
    fam = "consumption_trajectory"
    total = block("total")
    total_dbus = _number(total.get("dbus")) if total else None
    if total is None:
        for metric in ("total_dbus", "total_dsu"):
            emit(fam, metric, None, reason=missing("total", fam, metric))
    else:
        emit(fam, "total_dbus", total_dbus, reason="no_total_dbus")
        # DSU is None when the window had no DSU rows: a measured zero.
        emit(fam, "total_dsu", _number(total.get("dsu")) or 0.0)

    months = block("months")
    if months is None:
        for metric in ("last_full_month_dbus", "month_over_month_pct"):
            emit(fam, metric, None, reason=missing("months", fam, metric))
    else:
        last = months.get("last_full")
        last_dbus = _number(last.get("dbus")) if isinstance(last, Mapping) else None
        emit(fam, "last_full_month_dbus", last_dbus, reason="no_full_month")
        emit(
            fam,
            "month_over_month_pct",
            _number(months.get("mom_growth_pct")),
            reason="no_prior_month_dbus",
        )

    step = facts.get("step_change")
    if step is None and "step_change" in unavailable:
        for metric in ("step_change_present", "step_change_lift_daily_dbus"):
            emit(fam, metric, None, reason=missing("step_change", fam, metric))
    elif step is None:
        emit(fam, "step_change_present", 0.0)
        emit(fam, "step_change_lift_daily_dbus", None, reason="no_step_change")
    else:
        if not isinstance(step, Mapping):
            raise ValueError("discovery facts 'step_change' must be an object")
        emit(fam, "step_change_present", 1.0)
        emit(
            fam,
            "step_change_lift_daily_dbus",
            _number(step.get("lift_daily_dbus")),
            reason="no_step_lift",
        )

    # efficiency ---------------------------------------------------------------
    fam = "efficiency"
    perf = block("performance_mode")
    if perf is None:
        metric = "performance_optimized_pct"
        emit(fam, metric, None, reason=missing("performance_mode", fam, metric))
    else:
        emit(
            fam,
            "performance_optimized_pct",
            _number(perf.get("performance_optimized_pct")),
            reason="no_performance_pool_dbus",
        )
    wh = block("warehouses")
    metric = "warehouse_serverless_share_pct"
    if wh is None:
        emit(fam, metric, None, reason=missing("warehouses", fam, metric))
    else:
        classic = _number(wh.get("classic_dbus")) or 0.0
        serverless = _number(wh.get("serverless_dbus")) or 0.0
        pool = classic + serverless
        emit(
            fam,
            metric,
            _share(serverless, pool) if pool > 0 else None,
            reason="no_warehouse_dbus",
        )

    # reliability: workspace grain from F-06 only ------------------------------
    fam = "reliability"
    rel = block("job_reliability")
    span = _window(rel, interval)
    ws_metrics = (
        ("job_runs", "runs"),
        ("failed_job_runs", "failed_runs"),
        ("cancelled_job_runs", "cancelled_runs"),
        ("job_failure_rate_pct", "failure_rate_pct"),
    )
    for metric, key in ws_metrics:
        if rel is None:
            reason = missing("job_reliability", fam, metric)
            value = None
        else:
            value = _number(rel.get(key))
            reason = "no_runs" if key == "failure_rate_pct" else "no_value"
        emit(fam, metric, value, reason=reason, method=RELIABILITY_METHOD, span=span)

    # reliability: per job from F-12 (top-25 truncation) -----------------------
    by_job = block("job_reliability_by_job")
    if by_job is not None:
        jspan = _window(by_job, interval)
        seen: set[tuple[str, str]] = set()
        for item in by_job.get("jobs") or ():
            if not isinstance(item, Mapping) or item.get("job_id") in (None, ""):
                continue
            ws = str(item.get("workspace_id") or workspace_id)
            job = str(item["job_id"])
            if (ws, job) in seen:
                continue
            seen.add((ws, job))
            key = job_aggregate_dedupe_key(ws, job, *jspan, RELIABILITY_METHOD)
            for metric, field in (
                ("job_runs", "runs"),
                ("failed_job_runs", "failed_runs"),
                ("job_failure_rate_pct", "failure_rate_pct"),
            ):
                emit(
                    fam,
                    metric,
                    _number(item.get(field)),
                    reason="no_runs" if field == "failure_rate_pct" else "no_value",
                    coverage="partial",
                    entity_kind="job",
                    entity_id=job,
                    ws=ws,
                    method=RELIABILITY_METHOD,
                    span=jspan,
                    dedupe_key=key,
                    uncertainty=(UNCERTAINTY_PER_JOB_CAP,),
                )

    # adoption_breadth ---------------------------------------------------------
    fam = "adoption_breadth"
    mix = items("product_mix")
    if mix is None:
        metric = "products_in_use"
        emit(fam, metric, None, reason=missing("product_mix", fam, metric))
    else:
        used: dict[str, float] = {}
        for item in mix:
            product, dbus = item.get("product"), _number(item.get("dbus"))
            if product in (None, "") or dbus is None:
                continue
            used[str(product)] = used.get(str(product), 0.0) + dbus
        emit(fam, "products_in_use", float(sum(1 for d in used.values() if d > 0)))
        for product, dbus in used.items():
            emit(
                fam,
                "product_in_use",
                1.0 if dbus > 0 else 0.0,
                entity_kind="product",
                entity_id=product,
            )

    # concentration (shares of the window's total DBUs) ------------------------
    fam = "concentration"

    def share_of_total(
        metric: str, field: str, top: list[Mapping[str, Any]] | None, n: int
    ) -> None:
        if top is None:
            emit(fam, metric, None, reason=missing(field, fam, metric))
            return
        qid = fallbacks.get(field)
        if qid and any(i.get("pct") is None for i in top[:n]):
            emit(fam, metric, None, reason=f"window_mismatch:{qid}")
            return
        if not total_dbus:
            reason = missing("total", fam, metric) if total is None else "no_total_dbus"
            emit(fam, metric, None, reason=reason)
            return
        part = sum(_number(i.get("dbus")) or 0.0 for i in top[:n])
        emit(
            fam,
            metric,
            _share(part, total_dbus),
            coverage="partial" if qid else "complete",
        )

    top_jobs = items("top_jobs")
    share_of_total("top_job_share_pct", "top_jobs", top_jobs, 1)
    share_of_total("top10_jobs_share_pct", "top_jobs", top_jobs, 10)
    share_of_total(
        "top_warehouse_share_pct", "top_warehouses", items("top_warehouses"), 1
    )
    share_of_total("top_product_share_pct", "product_mix", mix, 1)
    return tuple(out)


# ---- from_reliability ----------------------------------------------------------------


def from_reliability(
    recon: Reconstruction,
    *,
    run_id: str,
    account_key: str,
    source_kind: str,
    interval: tuple[str, str],
    as_of: str | None = None,
) -> tuple[Observation, ...]:
    """Per-job reliability observations from a run-level reconstruction.

    Per job only (no workspace roll-up): ``job_runs``, ``failed_job_runs`` and
    ``job_failure_rate_pct`` with the job's coverage and evidence IDs, method
    ``job_reliability_v1``, a run-level ``dedupe_key`` and the job's uncertainty
    codes (e.g. ``verify_limit_reached``). An uncovered job is
    ``unknown`` (``missing_source:vt-job-run-states``); a conflicting one is
    ``unknown`` (``source_conflict``).

    Args:
        interval: The reporting interval passed to
            :func:`~starboard_core.engagement.jobruns.reconstruct_runs` (the
            reconstruction does not record it); use the facts window so the
            observations supersede the F-12 aggregates.
    """
    family = "reliability"
    stamp = as_of or interval[1]
    out: list[Observation] = []
    for jr in recon.jobs:
        key = RUN_LEVEL_KEY_PREFIX + "|".join(
            (jr.workspace_id, jr.job_id, *interval, RELIABILITY_METHOD)
        )
        uncertainty = set(jr.uncertainty)
        if jr.conflicts or UNCERTAINTY_SOURCE_CONFLICT in uncertainty:
            unknown = UNCERTAINTY_SOURCE_CONFLICT
            uncertainty.add(UNCERTAINTY_SOURCE_CONFLICT)
        elif jr.coverage == "unknown":
            unknown = _missing((_RELIABILITY_TEMPLATE,))
        else:
            unknown = None
        values = (
            ("job_runs", jr.runs),
            ("failed_job_runs", jr.failed_runs),
            ("job_failure_rate_pct", jr.failure_rate_pct),
        )
        for metric, value in values:
            reason = unknown or (
                "no_runs" if metric == "job_failure_rate_pct" else None
            )
            out.append(
                build_observation(
                    run_id=run_id,
                    account_key=account_key,
                    workspace_id=jr.workspace_id,
                    family=family,
                    entity_kind="job",
                    entity_id=jr.job_id,
                    metric=metric,
                    value=None if unknown else _number(value),
                    unit=_unit(family, metric, "job"),
                    method_version=RELIABILITY_METHOD,
                    interval=interval,
                    as_of=stamp,
                    coverage=jr.coverage,
                    evidence_ids=jr.evidence_ids,
                    source_kind=source_kind,
                    unknown_reason=reason,
                    dedupe_key=key,
                    uncertainty=sorted(uncertainty),
                )
            )
    return tuple(out)


# ---- rule_coverage -------------------------------------------------------------------


@lru_cache(maxsize=1)
def _seed_registry() -> RuleRegistry:
    return RuleRegistry.from_seed()


def _rule_domain(domain: str) -> str:
    return DOMAIN_TO_RULE_DOMAIN.get(domain, domain)


#: Ruleset domains in canonical review order (``jobs, query, warehouse, uc, …``).
_DOMAIN_ORDER: tuple[str, ...] = tuple(dict.fromkeys(DOMAIN_TO_RULE_DOMAIN.values()))


def _not_evaluated_reason(members: Sequence[tuple[str, Any]], attempted: Collection[str]) -> str:
    """Why a family with rules has none evaluated.

    ``not_reviewed:<ruleset domains>`` when some of its rule domains were never
    reviewed (the fix is ``review --domains``); otherwise every domain was
    reviewed but its evidence was unavailable: ``missing_source:<query IDs>``.
    """
    unreviewed = {d for d, _ in members if d not in attempted}
    if unreviewed:
        order = {d: i for i, d in enumerate(_DOMAIN_ORDER)}
        return "not_reviewed:" + ",".join(
            sorted(unreviewed, key=lambda d: (order.get(d, len(order)), d))
        )
    queries = {r.evidence_query for _, r in members if r.evidence_query}
    return _missing(queries) if queries else "not_reviewed"


def _suppressed_code(rule: Any) -> str:
    """``suppressed:<rule_id>`` (``:missing_column:<column>`` for a ``requires_column``
    rule): the review ran the rule's evidence but did not evaluate the rule."""
    column = rule.params.get("requires_column")
    if isinstance(column, str) and column:
        return f"suppressed:{rule.id}:missing_column:{column}"
    return f"suppressed:{rule.id}"


def _partial_gaps(
    members: Sequence[tuple[str, Any]],
    done: Collection[Any],
    attempted: Collection[str],
    *,
    degraded: bool,
    capped: bool,
    unavailable: Collection[str] = (),
) -> tuple[str, ...]:
    """Why a family with some rules evaluated is ``partial``, as uncertainty codes.

    One ``not_reviewed:<ruleset domain>`` per unreviewed domain of an unevaluated
    rule, one ``missing_source:<query ID>`` per unavailable evidence query of an
    unevaluated rule in a reviewed domain, then ``manifest_degraded`` (with one
    ``unavailable_query:<query ID>`` per other query the degraded manifest lists
    in ``unavailable_queries``, e.g. a failed discovery query) / ``evidence_capped``.
    """
    order = {d: i for i, d in enumerate(_DOMAIN_ORDER)}
    left = [(d, r) for d, r in members if r not in done]
    unreviewed = sorted(
        {d for d, _ in left if d not in attempted},
        key=lambda d: (order.get(d, len(order)), d),
    )
    queries = sorted(
        {r.evidence_query for d, r in left if d in attempted and r.evidence_query}
    )
    codes = [f"not_reviewed:{d}" for d in unreviewed]
    codes += [f"missing_source:{q}" for q in queries]
    if degraded:
        codes.append("manifest_degraded")
        codes += [f"unavailable_query:{q}" for q in sorted(set(unavailable) - set(queries))]
    if capped:
        codes.append("evidence_capped")
    return tuple(codes)


def rule_coverage(
    manifest: Mapping[str, Any],
    *,
    run_id: str,
    account_key: str,
    workspace_id: str,
    interval: tuple[str, str],
    evidence_ids: Sequence[str],
    source_kind: str = "customer_workspace",
    reviewed_domains: Collection[str] | None = None,
    registry: RuleRegistry | None = None,
    as_of: str | None = None,
) -> tuple[Observation, ...]:
    """Per-family ``rules_evaluated`` / ``active_rule_findings`` (workspace grain).

    Only positive evidence counts. A rule was evaluated when a finding cites it,
    or when it is enabled, its ruleset domain was reviewed and its evidence ran
    and succeeded: its ``evidence_query`` is not in ``unavailable_queries``
    (failed, skipped or absent) and its domain is not in ``unavailable_domains``.
    Unavailable evidence never makes a domain reviewed.
    ``active_rule_findings`` counts distinct findings whose rule is in the family.
    Coverage is ``partial`` when some family rule was not evaluated, the manifest
    is degraded or a finding's evidence was capped; a partial family's
    observations name why in ``uncertainty`` (``not_reviewed:<domain>``,
    ``missing_source:<query ID>``, ``manifest_degraded`` with its
    ``unavailable_query:<query ID>``, ``evidence_capped``, one code each). A
    family with no evaluated rule is ``unknown``: ``no_family_rules`` when it has none,
    ``suppressed:<rule IDs>`` when the review suppressed every one of its rules,
    ``not_reviewed:<ruleset domains>`` when some of its other rule domains were not
    reviewed (e.g. ``not_reviewed:uc,portfolio_readiness`` on a default
    ``jobs,sql,warehouse`` review), else ``missing_source:<evidence query IDs>``.

    A rule in the manifest's ``suppressed_rules`` (``{rule_id: reason}``: the
    source does not carry a column the rule requires, e.g. ``run_as`` on the
    internal mirror) is never evaluated, even though its evidence ran; its
    family's observations carry ``suppressed:<rule_id>`` (with
    ``:missing_column:<column>`` for a ``requires_column`` rule), whether the
    family is ``partial`` or ``unknown``.

    Args:
        reviewed_domains: Review domains (``--domains`` names or ruleset domains).
            Default: the manifest's ``reviewed_domains`` (the review's domain
            reports); a manifest without them reviewed no domain, so only rules
            with findings count.
        registry: Rule registry (default: the seed rules).

    Raises:
        ValueError: For a non-2.0 manifest, malformed findings, a malformed
            ``reviewed_domains`` or a malformed ``suppressed_rules``.
    """
    if manifest.get("snapshot_version") != "2.0":
        raise ValueError(
            "findings manifest must be snapshot_version '2.0', "
            f"got {manifest.get('snapshot_version')!r}"
        )
    findings = manifest.get("findings") or ()
    if not isinstance(findings, (list, tuple)):
        raise ValueError("findings manifest 'findings' must be a list")
    reg = registry if registry is not None else _seed_registry()
    rules = [
        (ruleset.domain, rule)
        for ruleset in reg.rulesets
        for rule in ruleset.rules
        if rule.enabled
    ]
    unavailable_queries = {str(q) for q in manifest.get("unavailable_queries") or ()}
    unavailable_domains = {
        _rule_domain(str(d)) for d in manifest.get("unavailable_domains") or ()
    }
    recorded_suppressed = manifest.get("suppressed_rules") or {}
    if not isinstance(recorded_suppressed, Mapping):
        raise ValueError("findings manifest 'suppressed_rules' must be an object")
    suppressed = {str(rule_id) for rule_id in recorded_suppressed}

    finding_keys: dict[str, set[str]] = {}
    capped: set[str] = set()
    for entry in findings:
        if not isinstance(entry, Mapping):
            raise ValueError("findings manifest entries must be objects")
        rule_id = entry.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            continue
        key = entry.get("composite_key") or entry.get("id") or rule_id
        finding_keys.setdefault(rule_id, set()).add(str(key))
        if entry.get("evidence_capped"):
            capped.add(rule_id)

    if reviewed_domains is None:
        recorded = manifest.get("reviewed_domains") or ()
        if not isinstance(recorded, (list, tuple)):
            raise ValueError("findings manifest 'reviewed_domains' must be a list")
        reviewed_domains = recorded
    reviewed = {_rule_domain(str(d)) for d in reviewed_domains}

    def evaluated(domain: str, rule: Any) -> bool:
        if rule.id in finding_keys:
            return True
        return (
            rule.id not in suppressed
            and domain in reviewed
            and domain not in unavailable_domains
            and rule.evidence_query not in unavailable_queries
        )

    degraded = bool(manifest.get("degraded"))
    stamp = as_of or interval[1]
    out: list[Observation] = []
    for family in SIX_FAMILIES:
        members = [(d, r) for d, r in rules if r.family == family]
        done = [r for d, r in members if evaluated(d, r)]
        held = [r for _, r in members if r not in done and r.id in suppressed]
        rest = [(d, r) for d, r in members if r not in held]
        if not members:
            reason: str | None = "no_family_rules"
        elif not done and not rest:
            reason = "suppressed:" + ",".join(sorted(r.id for r in held))
        elif not done:
            reason = _not_evaluated_reason(rest, reviewed | unavailable_domains)
        else:
            reason = None
        any_capped = any(r.id in capped for r in done)
        partial = len(done) < len(members) or degraded or any_capped
        gaps = (
            _partial_gaps(
                rest,
                done,
                reviewed | unavailable_domains,
                degraded=degraded,
                capped=any_capped,
                unavailable=unavailable_queries,
            )
            if partial and reason is None
            else ()
        )
        gaps = (*gaps, *(_suppressed_code(r) for r in held))
        active = sum(
            len(keys)
            for rid, keys in finding_keys.items()
            if rule_family(rid, reg) == family
        )
        for metric, value in (
            ("rules_evaluated", float(len(done))),
            ("active_rule_findings", float(active)),
        ):
            out.append(
                build_observation(
                    run_id=run_id,
                    account_key=account_key,
                    workspace_id=workspace_id,
                    family=family,
                    entity_kind="workspace",
                    entity_id=workspace_id,
                    metric=metric,
                    value=None if reason else value,
                    unit=_unit(family, metric, "workspace"),
                    method_version=METHOD_VERSION,
                    interval=interval,
                    as_of=stamp,
                    coverage="partial" if partial else "complete",
                    evidence_ids=evidence_ids,
                    source_kind=source_kind,
                    unknown_reason=reason,
                    uncertainty=gaps,
                )
            )
    return tuple(out)
