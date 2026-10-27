# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for restricted-ACL classification and permission rechecks."""

from __future__ import annotations

from dataclasses import replace

import pytest
from starboard_core.engagement.access import (
    AccessVerdict,
    is_restricted,
    recheck_access,
)
from starboard_core.ports.engagement_storage import AccessInfo, Grant

OWNER = Grant("user", "owner", "example.com")


def info(*grants: Grant, complete: bool = True, can_add: bool = True) -> AccessInfo:
    return AccessInfo(
        object_id="f1",
        can_add_children=can_add,
        drive_kind="my_drive",
        grants=grants,
        fingerprint="fp-1",
        complete=complete,
    )


def test_owner_only_is_restricted() -> None:
    assert is_restricted(info(OWNER)) is True


def test_no_grants_is_restricted() -> None:
    assert is_restricted(info()) is True


@pytest.mark.parametrize(
    "extra",
    [
        Grant("anyone", "reader"),
        Grant("domain", "reader", "example.com"),
        Grant("group", "writer", "example.com"),
        Grant("user", "reader", "example.com"),
    ],
)
def test_any_widening_grant_is_not_restricted(extra: Grant) -> None:
    assert is_restricted(info(OWNER, extra)) is False


@pytest.mark.parametrize("role", ["writer", "reader", "commenter", "organizer"])
def test_lone_non_owner_user_grant_is_not_restricted(role: str) -> None:
    assert is_restricted(info(Grant("user", role, "example.com"))) is False


def test_incomplete_acl_is_not_restricted() -> None:
    assert is_restricted(info(OWNER, complete=False)) is False


def test_recheck_unchanged() -> None:
    verdict = recheck_access("fp-1", info(OWNER))
    assert verdict == AccessVerdict(ok=True, reason="unchanged")


def test_recheck_incomplete_is_unknown() -> None:
    verdict = recheck_access("fp-1", info(OWNER, complete=False))
    assert verdict == AccessVerdict(ok=False, reason="unknown")


def test_recheck_lost_add_children_is_revoked() -> None:
    verdict = recheck_access("fp-1", info(OWNER, can_add=False))
    assert verdict == AccessVerdict(ok=False, reason="revoked")


def test_recheck_fingerprint_differs_is_changed() -> None:
    current = replace(info(OWNER), fingerprint="fp-2")
    assert recheck_access("fp-1", current) == AccessVerdict(ok=False, reason="changed")


def test_recheck_empty_recorded_fingerprint_is_changed() -> None:
    assert recheck_access("", info(OWNER)).reason == "changed"


def test_recheck_precedence_unknown_before_revoked_before_changed() -> None:
    current = replace(info(OWNER, complete=False, can_add=False), fingerprint="x")
    assert recheck_access("fp-1", current).reason == "unknown"
    current = replace(info(OWNER, can_add=False), fingerprint="x")
    assert recheck_access("fp-1", current).reason == "revoked"


def test_verdict_rejects_unknown_reason_and_inconsistent_ok() -> None:
    with pytest.raises(ValueError):
        AccessVerdict(ok=False, reason="weird")
    with pytest.raises(ValueError):
        AccessVerdict(ok=True, reason="changed")
    with pytest.raises(ValueError):
        AccessVerdict(ok=False, reason="unchanged")
