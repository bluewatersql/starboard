# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for identity-only workspace checks and host normalization."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from starboard_core.engagement.identity import check_identity, normalize_host

RID = "20261008_12345678-1234-4234-8234-123456789abc"
HOST = "https://adb-1.azuredatabricks.net"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://adb-1.azuredatabricks.net", HOST),
        ("https://ADB-1.AzureDatabricks.net/", HOST),
        ("https://adb-1.azuredatabricks.net/?o=123#x", HOST),
        ("https://adb-1.azuredatabricks.net/some/path", HOST),
        ("https://adb-1.azuredatabricks.net:443", HOST),
        ("https://adb-1.azuredatabricks.net.", HOST),
        ("adb-1.azuredatabricks.net", HOST),
        ("  https://adb-1.azuredatabricks.net  ", HOST),
        ("http://adb-1.azuredatabricks.net:80/", HOST),
        ("https://dbc.example.com:8443/x", "https://dbc.example.com:8443"),
    ],
)
def test_normalize_host(raw: str, expected: str) -> None:
    assert normalize_host(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "   ", "https://", "ftp://host.example", "https:///p"]
)
def test_normalize_host_rejects_bad_input(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_host(raw)


def run_check(**over: Any) -> Any:
    base: dict[str, Any] = {
        "run_id": RID,
        "provisional_account_key": "acme",
        "provisional_account_name": "Acme Corp",
        "provisional_source": "operator",
        "expected_workspace_id": "1234567890",
        "expected_host": None,
        "observed_workspace_id": "1234567890",
        "observed_host": "https://ADB-1.azuredatabricks.net/",
        "principal_id": "7781234",
        "principal_kind": "user",
        "checked_at": "2026-10-08T09:00:00+00:00",
    }
    base.update(over)
    return check_identity(**base)


def test_verified_when_workspace_matches() -> None:
    check = run_check()
    assert check.status == "verified"
    assert check.reasons == ()
    assert check.observed_host == HOST
    assert check.expected_host is None
    assert check.checked_at == "2026-10-08T09:00:00+00:00"


def test_verified_with_matching_expected_host_after_normalization() -> None:
    check = run_check(expected_host="adb-1.azuredatabricks.net")
    assert check.status == "verified"
    assert check.expected_host == HOST


def test_workspace_id_mismatch() -> None:
    check = run_check(observed_workspace_id="999")
    assert check.status == "mismatch"
    assert len(check.reasons) == 1
    assert "workspace id differs" in check.reasons[0]


def test_host_mismatch_only_when_expected_host_given() -> None:
    check = run_check(expected_host="https://other.cloud.databricks.com")
    assert check.status == "mismatch"
    assert any("host differs" in r for r in check.reasons)


def test_missing_expected_workspace_id_is_a_mismatch() -> None:
    check = run_check(expected_workspace_id="")
    assert check.status == "mismatch"
    assert check.reasons == ("no expected workspace id",)


def test_multiple_reasons_are_all_reported() -> None:
    check = run_check(
        observed_workspace_id="999", expected_host="https://other.example.com"
    )
    assert check.status == "mismatch"
    assert len(check.reasons) == 2


def test_workspace_ids_compared_after_strip() -> None:
    assert run_check(observed_workspace_id=" 1234567890 ").status == "verified"


def test_checked_at_defaults_to_now() -> None:
    check = run_check(checked_at=None)
    assert datetime.fromisoformat(check.checked_at).tzinfo is not None


def test_service_principal_and_sources_carried() -> None:
    check = run_check(principal_kind="service_principal", provisional_source="ticket")
    assert check.principal_kind == "service_principal"
    assert check.provisional_source == "ticket"
    assert check.provisional_account_key == "acme"


def test_invalid_inputs_raise() -> None:
    with pytest.raises(ValueError):
        run_check(principal_id="person@example.com")
    with pytest.raises(ValueError):
        run_check(provisional_source="guess")
    with pytest.raises(ValueError):
        run_check(observed_host="")


def test_workspace_profile_recorded() -> None:
    assert run_check(workspace_profile="acme-ws").workspace_profile == "acme-ws"
    assert run_check().workspace_profile is None
    assert run_check(workspace_profile="").workspace_profile is None


# ---- run_profile: the verified identity is the one that fetches ---------------


def _auth(*, basis: str | None = "verified", workspace_profile: str | None = "acme-ws"):
    from starboard_core.engagement.records import (
        AccountRef,
        RunAuthorization,
        SourceMode,
        StoragePolicy,
    )

    scope: dict[str, Any] = {"workspaces": ["1234567890"], "days": 30}
    if basis is not None:
        scope["basis"] = basis
    return RunAuthorization(
        engagement_id="eng-acme",
        run_id=RID,
        intent="health_check",
        task="review",
        account=AccountRef(id="001ABC", display_name="Acme", verifier="identity_check"),
        requested_scope=dict(scope),
        authorized_scope=scope,
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=SourceMode.CUSTOMER_WORKSPACE,
        storage_policy=StoragePolicy.DRIVE_REQUIRED,
        audience="internal",
        methodology_version="m1",
        workspace_profile=workspace_profile,
    )


def test_run_profile_defaults_to_the_verified_profile() -> None:
    from starboard_core.engagement.identity import run_profile

    assert run_profile(_auth(), None) == "acme-ws"
    assert run_profile(_auth(), "") == "acme-ws"
    assert run_profile(_auth(), "acme-ws") == "acme-ws"


def test_run_profile_refuses_a_different_profile() -> None:
    from starboard_core.engagement.identity import ProfileMismatch, run_profile

    with pytest.raises(ProfileMismatch, match=r"^PROFILE_MISMATCH: .*'acme-ws'.*'other'"):
        run_profile(_auth(), "other")


def test_run_profile_host_verified_run() -> None:
    from starboard_core.engagement.identity import ProfileMismatch, run_profile

    auth = _auth(workspace_profile=None)
    assert run_profile(auth, None) is None
    with pytest.raises(ProfileMismatch, match=r"^PROFILE_MISMATCH: .*--host"):
        run_profile(auth, "acme-ws")


@pytest.mark.parametrize("basis", [None, "declared"])
def test_run_profile_unverified_scope_passes_through(basis: str | None) -> None:
    from starboard_core.engagement.identity import run_profile

    auth = _auth(basis=basis, workspace_profile=None)
    assert run_profile(auth, "anything") == "anything"
    assert run_profile(auth, None) is None
