# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Internal-env (gate: Internal-env) live parity checks for all four adapters.

Guarded: each test SKIPs unless its adapter's internal env is wired. When wired
(internal deployment), each adapter must return real data whose shape is a strict
SUPERSET of the public port DTO — the public-parity fields are present AND the
internal enrichment is populated. Optional ``*_TARGET`` env vars supply the live
inputs (a cluster/run id, a curated room, an NL question); sensible defaults let
the run work against a canonical fixture.

Owner runbook: set the ``STARBOARD_INTERNAL_*`` env, run
``pytest packages/starboard-internal/tests/integration -q``, and record the
parity result under the Internal-env gate in ``OWNER_RUNBOOK.md``.
"""

from __future__ import annotations

import os

import pytest
from starboard_core.ports.diagnostic_backend import DiagnosticResult
from starboard_core.ports.fleet_sql import FleetQuery, FleetResult
from starboard_core.ports.log_retrieval import LogBundle, LogQuery
from starboard_core.ports.nl_query import NLAnswer, WorkspaceCtx
from starboard_internal.centralized_fleet_adapter import CentralizedFleetSqlAdapter
from starboard_internal.curated_genie_adapter import CuratedGenieRoomAdapter
from starboard_internal.dbr_doctor_adapter import DbrDoctorAdapter
from starboard_internal.logs_summariser_adapter import LogsSummariserAdapter

from .conftest import (
    requires_dbr_doctor,
    requires_fleet_sql,
    requires_genie,
    requires_logs_summariser,
)

pytestmark = pytest.mark.integration


@requires_logs_summariser
async def test_logs_summariser_returns_indexed_superset() -> None:
    adapter = LogsSummariserAdapter()  # real backend from env
    entity = os.environ.get("STARBOARD_INTERNAL_LOGS_TARGET_ENTITY", "cluster")
    entity_id = os.environ.get("STARBOARD_INTERNAL_LOGS_TARGET_ID", "")
    bundle = await adapter.fetch(LogQuery(entity=entity, entity_id=entity_id))
    assert isinstance(bundle, LogBundle)
    # Public-parity fields present.
    assert bundle.source and "entity" in bundle.metadata
    # Additive enrichment populated by the real index.
    assert bundle.metadata["indexed"] == "true"


@requires_dbr_doctor
async def test_dbr_doctor_classifies_and_diagnoses_superset() -> None:
    adapter = DbrDoctorAdapter()  # real backend from env
    pasted = os.environ.get(
        "STARBOARD_INTERNAL_DOCTOR_TARGET",
        "Traceback (most recent call last):\nRuntimeError: boom",
    )
    candidates = adapter.classify(pasted)
    assert candidates, "expected the semantic layer to classify the input"
    result = await adapter.analyze(candidates[0])
    assert isinstance(result, DiagnosticResult)
    # Public-parity + additive enrichment.
    assert result.summary and "artifact_kind" in result.metadata
    assert result.metadata["semantic_layer"] == "true"


@requires_fleet_sql
async def test_centralized_fleet_executes_cross_account_superset() -> None:
    adapter = CentralizedFleetSqlAdapter()  # real SDK executor from env
    sql = os.environ.get(
        "STARBOARD_INTERNAL_FLEET_TARGET_SQL",
        "SELECT workspace_id FROM system.billing.usage LIMIT 1",
    )
    result = await adapter.execute(FleetQuery(sql=sql))
    assert isinstance(result, FleetResult)
    # Public-parity + additive rewrite enrichment.
    assert "workspace_id" in result.metadata
    assert result.metadata["cross_account"] == "true"


@requires_genie
async def test_curated_genie_answers_superset() -> None:
    adapter = CuratedGenieRoomAdapter()  # real Genie backend from env
    room = os.environ.get("STARBOARD_INTERNAL_GENIE_TARGET_ROOM", "global_genie")
    question = os.environ.get(
        "STARBOARD_INTERNAL_GENIE_TARGET_QUESTION", "How many rows are available?"
    )
    answer = await adapter.ask(question, WorkspaceCtx(extra={"genie_room": room}))
    assert isinstance(answer, NLAnswer)
    # Public-parity + additive provenance enrichment.
    assert answer.metadata["curated"] == "true"
    assert answer.metadata["room"] == room
