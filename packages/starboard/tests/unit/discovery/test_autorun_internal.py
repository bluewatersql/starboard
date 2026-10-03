# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Auto-run wiring (Phase-4, Task 9): unattended/scheduled discovery source.

Proves the scheduled-run source resolver builds a no-prompt ``EngineConfig``
selection: a preset workspace_id or account target selects the internal
source; nothing preset leaves the default external source untouched.
"""

from __future__ import annotations

import pytest
from starboard.discovery.engine import EngineConfig, resolve_scheduled_source


@pytest.mark.unit
def test_preset_workspace_id_selects_internal_with_resolved_scope() -> None:
    source, internal_account, internal_workspace_ids = resolve_scheduled_source(
        internal_source_account=None,
        internal_source_workspace_id="1234567890",
    )
    config = EngineConfig(
        source=source,
        internal_account=internal_account,
        internal_workspace_ids=internal_workspace_ids,
    )
    assert config.source == "internal"
    assert config.internal_workspace_ids == ("1234567890",)
    assert config.internal_account is None


@pytest.mark.unit
def test_preset_account_selects_internal_with_resolved_scope() -> None:
    source, internal_account, internal_workspace_ids = resolve_scheduled_source(
        internal_source_account="acme-account",
        internal_source_workspace_id=None,
    )
    config = EngineConfig(
        source=source,
        internal_account=internal_account,
        internal_workspace_ids=internal_workspace_ids,
    )
    assert config.source == "internal"
    assert config.internal_account == "acme-account"
    assert config.internal_workspace_ids is None


@pytest.mark.unit
def test_no_preset_target_stays_external() -> None:
    source, internal_account, internal_workspace_ids = resolve_scheduled_source(
        internal_source_account=None,
        internal_source_workspace_id=None,
    )
    config = EngineConfig(
        source=source,
        internal_account=internal_account,
        internal_workspace_ids=internal_workspace_ids,
    )
    assert config.source == "external"
    assert config.internal_account is None
    assert config.internal_workspace_ids is None


@pytest.mark.unit
def test_workspace_id_takes_precedence_over_account() -> None:
    # Spec: one account or one workspace_id per run — a preset workspace_id wins.
    source, internal_account, internal_workspace_ids = resolve_scheduled_source(
        internal_source_account="acme-account",
        internal_source_workspace_id="1234567890",
    )
    assert source == "internal"
    assert internal_workspace_ids == ("1234567890",)
    assert internal_account is None
