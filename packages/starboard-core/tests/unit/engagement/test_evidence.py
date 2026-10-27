# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the one evidence recorder and the computed source kind (D-14)."""

from __future__ import annotations

import json

import pytest
from starboard_core.engagement.evidence import (
    derive_source_kind,
    input_source_kinds,
    record_evidence,
)
from starboard_core.engagement.folders import IDENTITY_PROPERTY
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.policy import SourceMode
from starboard_core.engagement.publication import audience_gate
from starboard_core.engagement.records import EvidenceRef, ReportRevision, StorageRef
from starboard_core.engagement.sink import EVIDENCE_INDEX, DriveRunSink, MemorySink

RID = "20261008_12345678-1234-4234-8234-123456789abc"


def _sink() -> DriveRunSink:
    store = InMemoryEngagementStorage()
    run = store.create_folder(
        store.root_folder_id(), RID, {IDENTITY_PROPERTY: f"run:{RID}"}
    )
    return DriveRunSink(
        store, run.id, run_id=RID, access_fingerprint=store.inspect_access(run.id).fingerprint
    )


def _record(sink: DriveRunSink, relpath: str, source_kind: str) -> list[EvidenceRef]:
    ref = sink.put_text(relpath, f"[{relpath!r}]", "application/json")
    return record_evidence(
        sink,
        [(ref, f"test:{relpath}", 3, False)],
        source_kind=source_kind,
        scope=("123",),
        method_version="m1",
    )


@pytest.mark.unit
class TestRecordEvidence:
    def test_records_and_returns_refs_with_computed_audience(self) -> None:
        sink = _sink()
        (cust,) = _record(sink, "raw/a.json", "customer_workspace")
        (internal,) = _record(sink, "raw/b.json", "internal_mirror")
        assert cust.audience_class == "customer_shareable"
        assert internal.audience_class == "internal_only"
        assert cust.scope_workspace_ids == ("123",)
        assert (cust.producer, cust.row_count, cust.truncated) == ("test:raw/a.json", 3, False)
        assert cust.method_version == "m1"
        stored = [EvidenceRef.from_dict(d) for d in json.loads(sink.get_bytes(EVIDENCE_INDEX))]
        assert stored == [cust, internal]

    def test_non_drive_sink_records_nothing(self) -> None:
        sink = MemorySink(run_id=RID)
        ref = sink.put_text("raw/a.json", "[]", "application/json")
        out = record_evidence(
            sink,
            [(ref, "p", None, False)],
            source_kind="customer_workspace",
            scope=(),
            method_version="m1",
        )
        assert out == []
        assert not sink.exists(EVIDENCE_INDEX)

    def test_empty_items_record_nothing(self) -> None:
        sink = _sink()
        assert record_evidence(
            sink, [], source_kind="customer_workspace", scope=(), method_version="m1"
        ) == []
        assert not sink.exists(EVIDENCE_INDEX)

    def test_unknown_source_kind_is_refused(self) -> None:
        sink = _sink()
        ref = sink.put_text("raw/a.json", "[]", "application/json")
        with pytest.raises(ValueError, match="source_kind"):
            record_evidence(
                sink, [(ref, "p", None, False)], source_kind="bogus", scope=(),
                method_version="m1",
            )


@pytest.mark.unit
class TestDeriveSourceKind:
    @pytest.mark.parametrize(
        ("kinds", "mode", "expected"),
        [
            # Pure customer rows stay customer_workspace.
            (["customer_workspace"], SourceMode.CUSTOMER_WORKSPACE, "customer_workspace"),
            (["customer_workspace"], SourceMode.HYBRID, "customer_workspace"),
            ([], SourceMode.CUSTOMER_WORKSPACE, "customer_workspace"),
            # Unknown provenance takes the run's label: customer only on a customer run.
            ([None], SourceMode.CUSTOMER_WORKSPACE, "customer_workspace"),
            ([None], SourceMode.HYBRID, "internal_mirror"),
            ([None], SourceMode.UNKNOWN, "internal_mirror"),
            # The most restrictive label wins; any internal input makes it internal.
            (["customer_workspace", "internal_mirror"], SourceMode.CUSTOMER_WORKSPACE,
             "internal_mirror"),
            (["internal_mirror", "internal_telemetry"], SourceMode.HYBRID,
             "internal_telemetry"),
            (["customer_workspace", "drive_object"], SourceMode.CUSTOMER_WORKSPACE,
             "drive_object"),
            # A hybrid run is internal unless every input is customer-sourced.
            (["customer_workspace", "drive_object"], SourceMode.HYBRID, "internal_mirror"),
            ([], SourceMode.HYBRID, "internal_mirror"),
            (["customer_workspace"], SourceMode.INTERNAL_ONLY, "internal_mirror"),
            ([], "internal_only", "internal_mirror"),
        ],
    )
    def test_labels(self, kinds: list[str | None], mode: SourceMode, expected: str) -> None:
        assert derive_source_kind(kinds, source_mode=mode) == expected

    def test_unknown_kind_is_refused(self) -> None:
        with pytest.raises(ValueError, match="source_kind"):
            derive_source_kind(["bogus"], source_mode=SourceMode.CUSTOMER_WORKSPACE)


@pytest.mark.unit
class TestInputSourceKind:
    def test_indexed_relpath_and_object_id_resolve_to_their_evidence(self) -> None:
        sink = _sink()
        (ev,) = _record(sink, "raw/w-w01.json", "internal_mirror")
        assert input_source_kinds(
            sink, ["raw/w-w01.json", f"drive:{ev.storage_ref.object_id}"]
        ) == ["internal_mirror", "internal_mirror"]

    def test_unindexed_inputs(self) -> None:
        sink = _sink()
        sink.put_text("raw/upload.json", "[]", "application/json")
        assert input_source_kinds(sink, ["raw/upload.json", "drive:elsewhere"]) == [
            None,
            "drive_object",
        ]
        assert input_source_kinds(sink, []) == []

    def test_hybrid_run_with_internal_mirror_rows_blocks_a_customer_report(self) -> None:
        """arch H4: outputs over internal-mirror rows are internal-only (D-14 gate)."""
        sink = _sink()
        _record(sink, "raw/w-w01.json", "internal_mirror")
        _record(sink, "raw/w-w02.json", "customer_workspace")
        kind = derive_source_kind(
            input_source_kinds(sink, ["raw/w-w01.json", "raw/w-w02.json"]),
            source_mode=SourceMode.HYBRID,
        )
        out = sink.put_text("analysis/review.json", "{}", "application/json")
        (ev,) = record_evidence(
            sink, [(out, "review", None, False)], source_kind=kind, scope=("123",),
            method_version="m1",
        )
        assert (ev.source_kind, ev.audience_class) == ("internal_mirror", "internal_only")
        report = ReportRevision(
            report_id="rpt_1",
            revision=1,
            audience="customer",
            object_ref=StorageRef(
                path="deliverables/report.md", object_id="o1", revision="r1",
                md5="0" * 32, size=1, mime_type="text/markdown",
            ),
            cited_evidence_ids=(ev.evidence_id,),
            cited_observation_ids=(),
            derived_from=None,
            state="draft",
            blocked_reasons=(),
            created_at="2026-10-08T09:00:00+00:00",
        )
        state, reasons = audience_gate(
            report,
            {ev.evidence_id: ev},
            {},
            source_mode=SourceMode.CUSTOMER_WORKSPACE,
            source_revision=None,
        )
        assert state == "blocked_audience"
        assert reasons == (f"internal_only_evidence:{ev.evidence_id}",)

    def test_pure_customer_rows_stay_shareable(self) -> None:
        sink = _sink()
        _record(sink, "raw/w-w01.json", "customer_workspace")
        kind = derive_source_kind(
            input_source_kinds(sink, ["raw/w-w01.json"]), source_mode=SourceMode.HYBRID
        )
        out = sink.put_text("analysis/review.json", "{}", "application/json")
        (ev,) = record_evidence(
            sink, [(out, "review", None, False)], source_kind=kind, scope=(),
            method_version="m1",
        )
        assert (ev.source_kind, ev.audience_class) == (
            "customer_workspace",
            "customer_shareable",
        )
