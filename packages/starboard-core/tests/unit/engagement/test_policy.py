# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the engagement storage-policy classifier."""

from __future__ import annotations

import pytest
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.policy import (
    LOCAL_FILE_INTAKE_GUIDANCE,
    SourceMode,
    StorageDecision,
    StoragePolicy,
    classify_storage,
    local_file_intake_allowed,
)

ON = OverlaySignal(enabled=True, reasons=("internal_package",))
OFF = OverlaySignal(enabled=False)


@pytest.mark.parametrize(
    "mode", [SourceMode.CUSTOMER_WORKSPACE, SourceMode.HYBRID, SourceMode.UNKNOWN]
)
@pytest.mark.parametrize("requested", [None, "drive"])
def test_overlay_with_customer_leg_requires_drive(
    mode: SourceMode, requested: str | None
) -> None:
    d = classify_storage(mode, ON, requested=requested)  # type: ignore[arg-type]
    assert d.policy is StoragePolicy.DRIVE_REQUIRED
    assert d.drive_required is True
    assert d.refusal is None
    assert d.reason


@pytest.mark.parametrize(
    "mode", [SourceMode.CUSTOMER_WORKSPACE, SourceMode.HYBRID, SourceMode.UNKNOWN]
)
def test_overlay_customer_leg_local_request_refused(mode: SourceMode) -> None:
    d = classify_storage(mode, ON, requested="local")
    assert d.policy is StoragePolicy.DRIVE_REQUIRED
    assert d.drive_required is True
    assert d.refusal is not None
    assert "laptop" in d.refusal
    assert "Drive" in d.refusal


def test_public_customer_workspace_defaults_local() -> None:
    d = classify_storage(SourceMode.CUSTOMER_WORKSPACE, OFF, requested=None)
    assert d.policy is StoragePolicy.LOCAL
    assert d.drive_required is False
    assert d.refusal is None


def test_public_customer_workspace_local_request() -> None:
    d = classify_storage(SourceMode.CUSTOMER_WORKSPACE, OFF, requested="local")
    assert d.policy is StoragePolicy.LOCAL
    assert d.refusal is None


def test_public_customer_workspace_drive_optional() -> None:
    d = classify_storage(SourceMode.CUSTOMER_WORKSPACE, OFF, requested="drive")
    assert d.policy is StoragePolicy.DRIVE_OPTIONAL
    assert d.drive_required is False
    assert d.refusal is None


def test_public_unknown_treated_as_customer_workspace() -> None:
    assert (
        classify_storage(SourceMode.UNKNOWN, OFF, requested=None).policy
        is StoragePolicy.LOCAL
    )
    assert (
        classify_storage(SourceMode.UNKNOWN, OFF, requested="drive").policy
        is StoragePolicy.DRIVE_OPTIONAL
    )


@pytest.mark.parametrize("overlay", [ON, OFF])
def test_internal_only_defaults_to_drive(overlay: OverlaySignal) -> None:
    d = classify_storage(SourceMode.INTERNAL_ONLY, overlay, requested=None)
    assert d.policy is StoragePolicy.DRIVE_DEFAULT
    assert d.drive_required is False
    assert d.refusal is None
    d2 = classify_storage(SourceMode.INTERNAL_ONLY, overlay, requested="drive")
    assert d2.policy is StoragePolicy.DRIVE_DEFAULT


@pytest.mark.parametrize("overlay", [ON, OFF])
def test_internal_only_explicit_local(overlay: OverlaySignal) -> None:
    d = classify_storage(SourceMode.INTERNAL_ONLY, overlay, requested="local")
    assert d.policy is StoragePolicy.INTERNAL_ONLY_LOCAL
    assert d.drive_required is False
    assert d.refusal is None


@pytest.mark.parametrize("requested", [None, "drive", "local"])
def test_hybrid_without_overlay_fails_closed(requested: str | None) -> None:
    d = classify_storage(SourceMode.HYBRID, OFF, requested=requested)  # type: ignore[arg-type]
    assert d.policy is StoragePolicy.DRIVE_REQUIRED
    assert d.drive_required is True
    assert "overlay" in d.reason
    assert (d.refusal is not None) == (requested == "local")


def test_decision_is_frozen() -> None:
    d = classify_storage(SourceMode.CUSTOMER_WORKSPACE, OFF, requested=None)
    assert isinstance(d, StorageDecision)
    with pytest.raises(AttributeError):
        d.policy = StoragePolicy.DRIVE_REQUIRED  # type: ignore[misc]


def test_invalid_requested_rejected() -> None:
    with pytest.raises(ValueError):
        classify_storage(SourceMode.CUSTOMER_WORKSPACE, OFF, requested="s3")  # type: ignore[arg-type]


def test_source_mode_values() -> None:
    assert {m.value for m in SourceMode} == {
        "customer_workspace",
        "internal_only",
        "hybrid",
        "unknown",
    }
    assert {p.value for p in StoragePolicy} == {
        "local",
        "drive_optional",
        "drive_required",
        "drive_default",
        "internal_only_local",
    }


def test_local_file_intake() -> None:
    assert local_file_intake_allowed(OFF) is True
    assert local_file_intake_allowed(ON) is False
    assert "Drive" in LOCAL_FILE_INTAKE_GUIDANCE
