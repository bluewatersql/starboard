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

from pydantic import BaseModel, ConfigDict, Field, computed_field

from starboard_core.domain.models.review import WorkloadReview

# Bumped only if the persisted snapshot shape changes in a breaking way.
SNAPSHOT_VERSION = "1.0"


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


__all__ = [
    "SNAPSHOT_VERSION",
    "ActionRateDelta",
    "ReviewSnapshot",
    "compute_action_rate",
]
