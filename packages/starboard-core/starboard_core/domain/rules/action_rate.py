# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Action-Rate re-scan loop — resolved-rate delta over review snapshots (D1c / D-3.3).

Workloads have no PR/merge event, so the Action-Rate feedback loop is synthesized
by **re-scan** (PHASE_3 D-3.3): persist a lightweight snapshot of a review's
finding ids, then on a later review compute how many of the prior findings are
no longer present — the *resolved rate*. It is a **read-only** observable proxy;
nothing is ever written back to the customer workspace.

This module is **pure and I/O-free** — no ``databricks-sdk`` / ``openai`` /
``fastapi`` / ``mcp``. Snapshot persistence (reading/writing the JSON file) is a
thin concern handled by the caller (the ``starboard`` CLI / ``starboard_x``
helper); this module only defines the snapshot shape and the delta computation,
both of which operate on plain in-memory objects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from starboard_core.domain.models.review import WorkloadReview

# Bumped only if the persisted snapshot shape changes in a breaking way.
SNAPSHOT_VERSION = "1.0"

# The per-run ``findings-manifest.json`` record shape (recurrence loop). It is a
# superset of ``ReviewSnapshot``: it carries per-finding DBU magnitude and entity
# attribution so a later run can answer "newly expensive / regressed by how much".
# Distinct from ``SNAPSHOT_VERSION`` so the CLI can discriminate a v1 snapshot
# (finding ids only) from a v2 manifest (finding records) by ``snapshot_version``.
MANIFEST_VERSION = "2.0"

# DBU-bearing evidence columns, in extraction priority order. These are the
# **absolute** list-price DBU estimate columns the detectors read (see
# ``domain.rules.detectors``); percentage columns (``wasted_dbu_pct``,
# ``auto_stop_waste_pct``) are deliberately excluded — they are not DBU magnitudes.
_DBU_EVIDENCE_KEYS: tuple[str, ...] = (
    "evidence_dbu_estimate",
    "recoverable_dbus",
    "recoverable_dbu",
    "total_dbus",
    "dbus_consumed",
    "dbus",
)

# Classification defaults for the run-over-run cost comparison (D §3.3).
# A newly-appeared finding is "newly expensive" only above this DBU floor.
NEWLY_EXPENSIVE_DBU_THRESHOLD = 5000.0
# A persisting finding is "regressed"/"improved" only when its DBU moves by more
# than this fraction (±20%); within the band it is unchanged ("persisting").
DBU_CHANGE_PCT_THRESHOLD = 0.20

# Severity ordering for run-over-run comparison (higher = more severe).
_SEVERITY_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class ReviewSnapshot(BaseModel):
    """A persisted, comparable summary of one review run (D-3.3).

    Stores just enough to compute a resolved-rate delta on a later re-scan: the
    set of finding ids and the context they were produced in. It deliberately
    does **not** persist evidence rows — the snapshot is a diff key, not a data
    export.
    """

    model_config = ConfigDict(frozen=True)

    snapshot_version: str = Field(default=SNAPSHOT_VERSION)
    created_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp the snapshot was taken (caller-supplied).",
    )
    workspace: str | None = Field(default=None)
    requested_domains: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def finding_count(self) -> int:
        """Number of finding ids captured in the snapshot."""
        return len(self.finding_ids)

    @classmethod
    def from_review(
        cls, review: WorkloadReview, *, created_at: str | None = None
    ) -> ReviewSnapshot:
        """Build a snapshot from a completed :class:`WorkloadReview`.

        Finding ids are de-duplicated and sorted so the snapshot is stable and
        order-independent (a review re-run that reorders equal-scored findings
        still produces an identical snapshot).
        """
        ids = sorted({rf.finding.id for rf in review.findings})
        return cls(
            created_at=created_at,
            workspace=review.workspace,
            requested_domains=tuple(review.requested_domains),
            finding_ids=tuple(ids),
        )


class ActionRateDelta(BaseModel):
    """The resolved-rate delta between a prior snapshot and a current review.

    A prior finding is **resolved** when it is absent from the current review;
    it is **persisting** when it still appears; a current finding absent from
    the prior snapshot is **new**. ``resolved_rate`` is the fraction of the
    prior findings that resolved (``0.0`` when the prior snapshot was empty).
    """

    model_config = ConfigDict(frozen=True)

    prior_created_at: str | None = None
    prior_count: int = 0
    current_count: int = 0
    resolved_ids: tuple[str, ...] = ()
    persisting_ids: tuple[str, ...] = ()
    new_ids: tuple[str, ...] = ()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_count(self) -> int:
        """Number of prior findings no longer present in the current review."""
        return len(self.resolved_ids)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_rate(self) -> float:
        """Fraction of prior findings that resolved (0.0 if none prior)."""
        if self.prior_count == 0:
            return 0.0
        return self.resolved_count / self.prior_count


def compute_action_rate(
    prior: ReviewSnapshot, current: WorkloadReview
) -> ActionRateDelta:
    """Compute the resolved-rate delta from ``prior`` to ``current``.

    Pure and read-only: compares finding-id sets and never mutates either input
    or the customer workspace. Id tuples on the result are sorted for a stable,
    reproducible ordering.
    """
    prior_ids = set(prior.finding_ids)
    current_ids = {rf.finding.id for rf in current.findings}

    resolved = prior_ids - current_ids
    persisting = prior_ids & current_ids
    new = current_ids - prior_ids

    return ActionRateDelta(
        prior_created_at=prior.created_at,
        prior_count=len(prior_ids),
        current_count=len(current_ids),
        resolved_ids=tuple(sorted(resolved)),
        persisting_ids=tuple(sorted(persisting)),
        new_ids=tuple(sorted(new)),
    )


# --------------------------------------------------------------------------- #
# Recurrence loop: per-run findings manifest + run-over-run cost comparison.
# --------------------------------------------------------------------------- #


def _coerce_float(value: Any) -> float | None:
    """Coerce a cell to ``float`` when numeric, else ``None`` (never raises).

    Mirrors ``domain.rules.detectors._as_float``: ``bool`` is not numeric, and a
    numeric string coerces. Kept local so this pure module has no cross-import.
    """
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


def extract_evidence_dbu(row: Mapping[str, Any]) -> float | None:
    """Extract the list-price DBU estimate from an evidence row, or ``None``.

    Scans the known **absolute** DBU columns (``_DBU_EVIDENCE_KEYS``) in priority
    order and returns the first numeric value. Returns ``None`` when the row
    carries no DBU magnitude — e.g. reliability/latency findings whose evidence is
    a failure rate or a shuffle volume, not a DBU figure. Percentage columns are
    never matched (their names are not in the key set).
    """
    for key in _DBU_EVIDENCE_KEYS:
        if key in row:
            dbu = _coerce_float(row[key])
            if dbu is not None:
                return dbu
    return None


def _queries(n: int) -> str:
    return f"{n} {'query' if n == 1 else 'queries'}"


def coverage_note(
    unavailable_queries: Sequence[str],
    discovery_skipped: Sequence[str] | None = None,
) -> str:
    """One-line review coverage statement for the manifest / review JSON / README.

    ``unavailable_queries`` are the evidence queries the review rules consumed
    but did not get; ``discovery_skipped`` (``None`` = live review, no discovery
    input) are all the queries the discovery run skipped, used by rules or not.
    """
    unavailable = sorted(set(unavailable_queries))
    if discovery_skipped is None:
        if not unavailable:
            return (
                "Review ran its own evidence queries; all evidence used by review "
                "rules is present."
            )
        return (
            f"Review ran its own evidence queries; {_queries(len(unavailable))} used "
            f"by review rules unavailable ({', '.join(unavailable)}) — findings in "
            "those domains are partial."
        )
    skipped = sorted(set(discovery_skipped))
    used = [q for q in skipped if q in unavailable]
    other = [q for q in unavailable if q not in skipped]
    note = f"{len(skipped)} discovery {'query' if len(skipped) == 1 else 'queries'} skipped"
    if skipped and not used:
        note += "; none used by review rules"
    elif used:
        note += (
            f"; {len(used)} used by review rules ({', '.join(used)}) — findings in "
            "those domains are partial"
        )
    if other:
        note += (
            f"; {len(other)} review evidence {'query' if len(other) == 1 else 'queries'} "
            f"failed or missing in the discovery output ({', '.join(other)})"
        )
    elif not used:
        note += "; all evidence used by review rules is present"
    return note + "."


class FindingRecord(BaseModel):
    """One finding's machine-readable per-run record (part of the manifest).

    Carries the diff key (``composite_key``) plus the DBU magnitude and severity
    the run-over-run comparison needs. ``$``/DBU values are list-price estimates.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="The originating finding id.")
    rule_id: str | None = Field(default=None, description="Originating rule id.")
    category: str | None = Field(default=None, description="Domain category.")
    severity: str = Field(..., description="Finding severity (value string).")
    score: float = Field(..., description="Priority score at capture time.")
    entity_id: str | None = Field(
        default=None,
        description="Stable Databricks resource id (warehouse/job/endpoint/...).",
    )
    entity_label: str | None = Field(
        default=None, description="Human-readable entity label (defaults to id)."
    )
    evidence_dbu_estimate: float | None = Field(
        default=None,
        description="List-price DBU estimate from the evidence row (None if none).",
    )
    query_id: str | None = Field(
        default=None, description="Evidence query_id that supplied the row."
    )
    evidence_capped: bool = Field(
        default=False,
        description=(
            "True when the evidence query hit its row limit (the query's "
            "result_limit): the evidence rows may be truncated. Not the per-rule "
            "finding cap (see rule_finding_cap)."
        ),
    )
    rule_finding_cap: int | None = Field(
        default=None,
        description=(
            "The rule's per-rule finding cap (max_findings, default 20) when it "
            "truncated this rule's findings: more entities matched than the "
            "manifest lists. None = every matching entity is listed."
        ),
    )
    rule_findings_dropped: int | None = Field(
        default=None,
        description=(
            "Matching entities of this rule past rule_finding_cap that the "
            "manifest does not list (None = none dropped)."
        ),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def composite_key(self) -> str:
        """Stable cross-run key: ``rule_id + '::' + entity_id``.

        Falls back to the finding ``id`` when ``rule_id`` or ``entity_id`` is
        absent (e.g. a non-rule/LLM finding). For rule-produced findings this is
        identical to ``id`` (the evaluator builds ``id = rule_id::entity_key``),
        but both are stored so entity tracking survives an opaque id (D §6.1).
        """
        if self.rule_id and self.entity_id:
            return f"{self.rule_id}::{self.entity_id}"
        return self.id


class FindingsManifest(BaseModel):
    """The per-run ``findings-manifest.json`` record (recurrence keystone).

    A local file only — never written to the customer workspace. Supersedes
    ``ReviewSnapshot`` for the per-run record: it stores finding-level DBU and
    entity attribution so a later run computes a cost-aware delta, not just a
    presence/absence action rate.
    """

    model_config = ConfigDict(frozen=True)

    snapshot_version: str = Field(default=MANIFEST_VERSION)
    run_date: str | None = Field(
        default=None, description="Run date (YYYY-MM-DD), caller-supplied."
    )
    workspace: str | None = Field(default=None)
    workspace_id: str | None = Field(default=None)
    lookback_days: int | None = Field(default=None)
    products_dbu: dict[str, float] = Field(
        default_factory=dict,
        description="Product-level DBU totals (list-price; account-scoped).",
    )
    findings: tuple[FindingRecord, ...] = ()
    degraded: bool = Field(
        default=False,
        description=(
            "True when any reviewed domain had unavailable evidence — the "
            "finding count is partial and not comparable run-over-run."
        ),
    )
    unavailable_queries: tuple[str, ...] = Field(
        default=(), description="Evidence query_ids that were unavailable."
    )
    unavailable_domains: tuple[str, ...] = Field(
        default=(), description="Review domains that degraded."
    )
    reviewed_domains: tuple[str, ...] = Field(
        default=(),
        description=(
            "Review domains the review evaluated (its domain reports; an unknown "
            "domain is not reviewed). Rule coverage counts a rule as evaluated "
            "only in these domains."
        ),
    )
    cost_basis: str | None = Field(
        default=None, description="The review's $ basis label (list-price DBU)."
    )
    evidence_source: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Where the evidence came from (e.g. kind=discovery with path / "
            "lookback_days); None = the review ran its own evidence queries."
        ),
    )
    discovery_skipped: tuple[str, ...] = Field(
        default=(),
        description=(
            "Every query_id the discovery input skipped, used by review rules or "
            "not (unavailable_queries lists only those the rules consumed)."
        ),
    )
    coverage_note: str | None = Field(
        default=None,
        description="One-line coverage statement (skipped vs used by review rules).",
    )
    suppressed_rules: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Rules not evaluated, keyed by rule id, with the reason (e.g. the "
            "source carries no run_as identity): no finding from such a rule "
            "means not assessed, not healthy."
        ),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def finding_count(self) -> int:
        """Number of finding records in the manifest."""
        return len(self.findings)

    @classmethod
    def from_review(
        cls,
        review: WorkloadReview,
        *,
        run_date: str | None = None,
        lookback_days: int | None = None,
        workspace_id: str | None = None,
        products_dbu: Mapping[str, float] | None = None,
        evidence_source: Mapping[str, Any] | None = None,
        discovery_skipped: Sequence[str] | None = None,
    ) -> FindingsManifest:
        """Build a manifest from a completed :class:`WorkloadReview`.

        ``discovery_skipped`` (``--from-discovery`` only; ``None`` = live
        review) lists every query the discovery input skipped; with the review's
        ``unavailable_queries`` it drives :func:`coverage_note`.

        The DBU estimate for each finding is extracted from its evidence rows
        (first row that carries a DBU column); ``None`` when the finding has no
        DBU attribution. Records are sorted by ``composite_key`` for a stable,
        reproducible manifest independent of finding ranking order.
        """
        records: list[FindingRecord] = []
        for rf in review.findings:
            f = rf.finding
            entity_id = f.location.entity if f.location else None
            dbu: float | None = None
            for ref in rf.evidence:
                dbu = extract_evidence_dbu(ref.row)
                if dbu is not None:
                    break
            query_id = rf.evidence[0].query_id if rf.evidence else None
            records.append(
                FindingRecord(
                    id=f.id,
                    rule_id=f.rule_id,
                    category=f.category,
                    severity=f.severity.value,
                    score=f.score,
                    entity_id=entity_id,
                    entity_label=entity_id,
                    evidence_dbu_estimate=dbu,
                    query_id=query_id,
                    evidence_capped=bool(rf.metadata.get("evidence_capped")),
                    rule_finding_cap=rf.metadata.get("rule_finding_cap"),
                    rule_findings_dropped=rf.metadata.get("rule_findings_dropped"),
                )
            )
        records.sort(key=lambda r: r.composite_key)
        return cls(
            run_date=run_date,
            workspace=review.workspace,
            workspace_id=workspace_id,
            lookback_days=lookback_days,
            products_dbu=dict(products_dbu) if products_dbu else {},
            findings=tuple(records),
            degraded=review.degraded,
            unavailable_queries=review.unavailable_queries,
            unavailable_domains=review.unavailable_domains,
            reviewed_domains=tuple(
                r.domain for r in review.domain_reports if r.rule_domain
            ),
            cost_basis=review.cost_basis,
            evidence_source=dict(evidence_source) if evidence_source else None,
            discovery_skipped=tuple(sorted(discovery_skipped or ())),
            coverage_note=coverage_note(review.unavailable_queries, discovery_skipped),
            suppressed_rules={
                rule_id: reason
                for r in review.domain_reports
                for rule_id, reason in sorted(r.suppressed_rules.items())
            },
        )


class CostDeltaEntry(BaseModel):
    """One classified finding in a run-over-run comparison, with DBU delta."""

    model_config = ConfigDict(frozen=True)

    composite_key: str
    rule_id: str | None = None
    entity_id: str | None = None
    category: str | None = None
    prior_severity: str | None = None
    current_severity: str | None = None
    prior_dbu: float | None = None
    current_dbu: float | None = None
    dbu_delta: float | None = Field(
        default=None, description="current_dbu - prior_dbu when both are present."
    )
    dbu_delta_pct: float | None = Field(
        default=None, description="Fractional DBU change vs. prior (prior > 0)."
    )
    severity_changed: str | None = Field(
        default=None, description="'worsened' | 'improved' | None."
    )
    note: str | None = Field(
        default=None, description="Classification annotation (e.g. no DBU attribution)."
    )


class CostDelta(BaseModel):
    """Run-over-run comparison of two findings manifests (D §3.3/3.4).

    Classifies every entity+rule pair as **newly-expensive**, **regressed**,
    **improved**, **persisting**, or **new (low-cost)** — and carries per-product
    DBU deltas. Pure and read-only: nothing is written to the workspace.
    """

    model_config = ConfigDict(frozen=True)

    prior_run_date: str | None = None
    current_run_date: str | None = None
    prior_count: int = 0
    current_count: int = 0
    newly_expensive: tuple[CostDeltaEntry, ...] = ()
    regressed: tuple[CostDeltaEntry, ...] = ()
    improved: tuple[CostDeltaEntry, ...] = ()
    persisting: tuple[CostDeltaEntry, ...] = ()
    new_low_cost: tuple[CostDeltaEntry, ...] = ()
    products_dbu_delta: dict[str, float] = Field(default_factory=dict)
    comparable: bool = Field(
        default=True,
        description=(
            "False when the two runs cover different-length or overlapping windows "
            "(classes are then presence/severity only — capture repeatability, not a change)."
        ),
    )
    not_comparable_reason: str | None = Field(
        default=None,
        description="'window_mismatch' | 'interval_overlap' when comparable is False.",
    )
    prior_lookback_days: int | None = None
    current_lookback_days: int | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def newly_expensive_count(self) -> int:
        """Number of newly-expensive findings."""
        return len(self.newly_expensive)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def regressed_count(self) -> int:
        """Number of regressed findings."""
        return len(self.regressed)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def improved_count(self) -> int:
        """Number of improved (resolved or cost-reduced) findings."""
        return len(self.improved)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def persisting_count(self) -> int:
        """Number of persisting (unchanged) findings."""
        return len(self.persisting)


def _severity_delta(prior: str | None, current: str | None) -> int:
    """+1 when severity worsened, -1 when it improved, 0 when unchanged/unknown."""
    p = _SEVERITY_RANK.get((prior or "").lower())
    c = _SEVERITY_RANK.get((current or "").lower())
    if p is None or c is None:
        return 0
    return (c > p) - (c < p)


def _both_entry(
    prior: FindingRecord,
    current: FindingRecord,
    *,
    comparable: bool = True,
    reason: str | None = None,
) -> CostDeltaEntry:
    """Build a comparison entry for a finding present in both runs.

    With ``comparable=False`` (``reason``: different lookback windows or overlapping
    windows) the DBU figures are kept but no delta is computed: a 7-day total minus a
    30-day total, or two captures of the same days, is not a change.
    """
    p_dbu = prior.evidence_dbu_estimate
    c_dbu = current.evidence_dbu_estimate
    delta: float | None = None
    pct: float | None = None
    note: str | None = None
    if not comparable:
        note = _NOT_COMPARABLE_NOTES.get(reason or "", _NOT_COMPARABLE_NOTES["window_mismatch"])
    elif p_dbu is not None and c_dbu is not None:
        delta = c_dbu - p_dbu
        if p_dbu > 0:
            pct = delta / p_dbu
    else:
        note = "DBU impact not measured (no attribution on one or both runs)"
    sev = _severity_delta(prior.severity, current.severity)
    sev_changed = "worsened" if sev > 0 else "improved" if sev < 0 else None
    return CostDeltaEntry(
        composite_key=current.composite_key,
        rule_id=current.rule_id,
        entity_id=current.entity_id,
        category=current.category,
        prior_severity=prior.severity,
        current_severity=current.severity,
        prior_dbu=p_dbu,
        current_dbu=c_dbu,
        dbu_delta=delta,
        dbu_delta_pct=pct,
        severity_changed=sev_changed,
        note=note,
    )


def _appeared_entry(current: FindingRecord) -> CostDeltaEntry:
    """Build a comparison entry for a finding absent from the prior run."""
    note = None if current.evidence_dbu_estimate is not None else "no DBU attribution"
    return CostDeltaEntry(
        composite_key=current.composite_key,
        rule_id=current.rule_id,
        entity_id=current.entity_id,
        category=current.category,
        current_severity=current.severity,
        current_dbu=current.evidence_dbu_estimate,
        note=note,
    )


def _resolved_entry(prior: FindingRecord) -> CostDeltaEntry:
    """Build a comparison entry for a finding no longer present (resolved)."""
    return CostDeltaEntry(
        composite_key=prior.composite_key,
        rule_id=prior.rule_id,
        entity_id=prior.entity_id,
        category=prior.category,
        prior_severity=prior.severity,
        prior_dbu=prior.evidence_dbu_estimate,
        note="resolved (no longer firing)",
    )


_NOT_COMPARABLE_NOTES = {
    "window_mismatch": "window_mismatch: DBU delta not computed (different lookback windows)",
    "interval_overlap": (
        "interval_overlap: DBU delta not computed (the windows overlap — capture "
        "repeatability, not a change)"
    ),
}


def _field(manifest: FindingsManifest | Mapping[str, Any], name: str) -> Any:
    if isinstance(manifest, Mapping):
        return manifest.get(name)
    return getattr(manifest, name, None)


def _window_of(value: Any) -> tuple[str, str] | None:
    if isinstance(value, Mapping):
        start, end = value.get("start"), value.get("end")
        if isinstance(start, str) and start and isinstance(end, str) and end:
            return start[:10], end[:10]
    return None


def manifest_interval(
    manifest: FindingsManifest | Mapping[str, Any],
) -> tuple[str, str] | None:
    """The reporting window ``(start, end)`` (ISO dates) a findings manifest covers.

    Its ``facts_window``, else its discovery evidence window
    (``evidence_source.discovery_window``), else the ``lookback_days`` full days
    ending the day before ``run_date`` (the discovery facts window); ``None`` when
    the manifest records neither.
    """
    found = _window_of(_field(manifest, "facts_window"))
    source = _field(manifest, "evidence_source")
    if found is None and isinstance(source, Mapping):
        found = _window_of(source.get("discovery_window"))
    if found is not None:
        return found
    run_date, lookback = _field(manifest, "run_date"), _field(manifest, "lookback_days")
    if not (isinstance(run_date, str) and isinstance(lookback, int) and lookback > 0):
        return None
    try:
        day = date.fromisoformat(run_date[:10])
    except ValueError:
        return None
    return (day - timedelta(days=lookback)).isoformat(), (day - timedelta(days=1)).isoformat()


def window_comparability(
    prev: FindingsManifest | Mapping[str, Any],
    curr: FindingsManifest | Mapping[str, Any],
) -> str | None:
    """Why two findings manifests are not comparable run-over-run, or ``None``.

    The ``engagement analyze`` / ``run recur`` window rule at manifest level:
    ``window_mismatch`` when both record a ``lookback_days`` of a different length
    (:func:`~starboard_core.engagement.history.same_lookback`), else
    ``interval_overlap`` when the prior window ends after the current one starts
    (:func:`~starboard_core.engagement.history.intervals_overlap` over
    :func:`manifest_interval`). A manifest that records no window is assumed
    comparable.
    """
    # lazy: the engagement layer imports this module's package
    from starboard_core.engagement.history import intervals_overlap, same_lookback

    prior_lb, cur_lb = _field(prev, "lookback_days"), _field(curr, "lookback_days")
    if isinstance(prior_lb, int) and isinstance(cur_lb, int) and not same_lookback(prior_lb, cur_lb):
        return "window_mismatch"
    prior_iv, cur_iv = manifest_interval(prev), manifest_interval(curr)
    if prior_iv and cur_iv and intervals_overlap(prior_iv[1], cur_iv[0]):
        return "interval_overlap"
    return None


def compute_cost_delta(
    prev: FindingsManifest,
    curr: FindingsManifest,
    *,
    dbu_threshold: float = NEWLY_EXPENSIVE_DBU_THRESHOLD,
    dbu_change_pct: float = DBU_CHANGE_PCT_THRESHOLD,
) -> CostDelta:
    """Classify the run-over-run delta between two findings manifests.

    Keyed on ``composite_key = rule_id + '::' + entity_id``:

    * **appeared** (in ``curr`` only): *newly-expensive* when its DBU estimate is
      above ``dbu_threshold``, else *new (low-cost)* — including null-DBU findings.
    * **resolved** (in ``prev`` only): *improved* (the entity stopped firing).
    * **present in both**: severity worsening ⇒ *regressed*; severity improvement
      ⇒ *improved*; otherwise classify on DBU — up > ``dbu_change_pct`` ⇒
      *regressed*, down > ``dbu_change_pct`` ⇒ *improved*, else *persisting*.
      Null-DBU findings with unchanged severity classify as *persisting*.

    When :func:`window_comparability` finds the runs not comparable — different
    ``lookback_days`` (``window_mismatch``) or overlapping windows
    (``interval_overlap``: two captures of the same days, capture repeatability) —
    the result has ``comparable=False`` / ``not_comparable_reason=<reason>``,
    ``products_dbu_delta`` is empty, no per-finding DBU delta is computed, and the
    DBU-based classes (*newly-expensive*, DBU *regressed* / *improved*) are not
    assigned — only presence and severity classify.

    Pure and read-only. All output lists are sorted by ``composite_key``.
    """
    prev_map = {r.composite_key: r for r in prev.findings}
    curr_map = {r.composite_key: r for r in curr.findings}
    # products_dbu and finding DBU are lookback-window totals (F-01): runs over
    # different or overlapping windows have no DBU delta (a 7-day minus a 30-day
    # total, or a recapture of the same days, is not a change).
    reason = window_comparability(prev, curr)
    same_window = reason is None

    newly_expensive: list[CostDeltaEntry] = []
    regressed: list[CostDeltaEntry] = []
    improved: list[CostDeltaEntry] = []
    persisting: list[CostDeltaEntry] = []
    new_low_cost: list[CostDeltaEntry] = []

    for key in curr_map.keys() - prev_map.keys():
        rec = curr_map[key]
        entry = _appeared_entry(rec)
        dbu = rec.evidence_dbu_estimate
        if same_window and dbu is not None and dbu > dbu_threshold:
            newly_expensive.append(entry)
        else:
            new_low_cost.append(entry)

    for key in prev_map.keys() - curr_map.keys():
        improved.append(_resolved_entry(prev_map[key]))

    for key in prev_map.keys() & curr_map.keys():
        entry = _both_entry(
            prev_map[key], curr_map[key], comparable=same_window, reason=reason
        )
        if entry.severity_changed == "worsened":
            regressed.append(entry)
        elif entry.severity_changed == "improved":
            improved.append(entry)
        elif entry.dbu_delta_pct is not None and entry.dbu_delta_pct > dbu_change_pct:
            regressed.append(entry)
        elif entry.dbu_delta_pct is not None and entry.dbu_delta_pct < -dbu_change_pct:
            improved.append(entry)
        else:
            persisting.append(entry)

    products = set(prev.products_dbu) | set(curr.products_dbu) if same_window else set()
    products_dbu_delta = {
        p: curr.products_dbu.get(p, 0.0) - prev.products_dbu.get(p, 0.0)
        for p in sorted(products)
    }

    def _by_key(entries: list[CostDeltaEntry]) -> tuple[CostDeltaEntry, ...]:
        return tuple(sorted(entries, key=lambda e: e.composite_key))

    return CostDelta(
        prior_run_date=prev.run_date,
        current_run_date=curr.run_date,
        prior_count=len(prev_map),
        current_count=len(curr_map),
        newly_expensive=_by_key(newly_expensive),
        regressed=_by_key(regressed),
        improved=_by_key(improved),
        persisting=_by_key(persisting),
        new_low_cost=_by_key(new_low_cost),
        products_dbu_delta=products_dbu_delta,
        comparable=same_window,
        not_comparable_reason=reason,
        prior_lookback_days=prev.lookback_days,
        current_lookback_days=curr.lookback_days,
    )


__all__ = [
    "DBU_CHANGE_PCT_THRESHOLD",
    "MANIFEST_VERSION",
    "NEWLY_EXPENSIVE_DBU_THRESHOLD",
    "SNAPSHOT_VERSION",
    "ActionRateDelta",
    "CostDelta",
    "CostDeltaEntry",
    "FindingRecord",
    "FindingsManifest",
    "ReviewSnapshot",
    "compute_action_rate",
    "compute_cost_delta",
    "coverage_note",
    "extract_evidence_dbu",
    "manifest_interval",
    "window_comparability",
]
