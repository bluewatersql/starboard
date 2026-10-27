# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Restricted-ACL classification and permission rechecks (engagement-drive spec §1, §3).

Two pure checks over :class:`~starboard_core.ports.engagement_storage.AccessInfo`:

* :func:`is_restricted` - whether a folder is visible to its owner only, as the
  account-neutral ``_preflight/<run-id>`` staging folder must be before any
  customer-workspace call;
* :func:`recheck_access` - whether a run folder's access is still the one bound
  to the run at route time, checked before each sensitive commit and on resume.
  Unknown, revoked or changed access stops the operation: restore the previous
  sharing, or start a new run.

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from starboard_core.ports.engagement_storage import AccessInfo

AccessReason = Literal["unchanged", "unknown", "revoked", "changed"]

_REASONS: tuple[str, ...] = get_args(AccessReason)
_WIDENING_KINDS = frozenset({"anyone", "domain", "group"})


def is_restricted(access: AccessInfo) -> bool:
    """Whether ``access`` is owner-only.

    True when the ACL listing is complete, has no ``anyone``/``domain``/``group``
    grant and at most one ``user`` grant, whose role is ``owner``. An incomplete
    listing is never restricted: what cannot be seen cannot be proven absent.
    """
    if not access.complete:
        return False
    if any(g.kind in _WIDENING_KINDS for g in access.grants):
        return False
    users = [g for g in access.grants if g.kind == "user"]
    return not users or (len(users) == 1 and users[0].role == "owner")


@dataclass(frozen=True)
class AccessVerdict:
    """Outcome of :func:`recheck_access`.

    Attributes:
        ok: True only when ``reason`` is ``unchanged``.
        reason: ``unchanged``, ``unknown`` (ACL not fully visible), ``revoked``
            (can no longer add children) or ``changed`` (fingerprint differs).
    """

    ok: bool
    reason: str

    def __post_init__(self) -> None:
        if self.reason not in _REASONS:
            raise ValueError(
                f"AccessVerdict.reason must be one of {_REASONS}, got {self.reason!r}"
            )
        if self.ok != (self.reason == "unchanged"):
            raise ValueError("AccessVerdict.ok must be True exactly when unchanged")


def recheck_access(recorded_fingerprint: str, current: AccessInfo) -> AccessVerdict:
    """Compare ``current`` access with the fingerprint recorded for the run.

    Checked in order: an incomplete ACL is ``unknown``; a folder the operator can
    no longer add children to is ``revoked``; a different fingerprint is
    ``changed``; otherwise ``unchanged`` (the only ``ok`` verdict).
    """
    if not current.complete:
        return AccessVerdict(ok=False, reason="unknown")
    if not current.can_add_children:
        return AccessVerdict(ok=False, reason="revoked")
    if not recorded_fingerprint or current.fingerprint != recorded_fingerprint:
        return AccessVerdict(ok=False, reason="changed")
    return AccessVerdict(ok=True, reason="unchanged")


__all__ = ["AccessReason", "AccessVerdict", "is_restricted", "recheck_access"]
