"""P2-G14 exit test 8 - audience and publication integrity.

* A customer report citing internal evidence is ``blocked_audience`` and cannot
  be delivered.
* A failed delivery is never ``delivered``: the run is ``publication_pending``.
* Approval and receipt are bound to the exact MD5 of the delivered report bytes.
* After delivery, a host artifact changed with ``put`` and re-committed with
  ``commit --stage check`` is re-bound in the manifest (ref MD5 = new bytes), is
  readable, and leaves publication ``complete``. Without the re-commit ``read``
  reports ``committed: false`` (``true`` again after it).
* ``report --path`` refuses a body not committed at its current md5
  (``UNCOMMITTED_ARTIFACT``, exit 2).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from starboard_core.engagement.records import Approval, DeliveryReceipt
from starboard_core.engagement.sink import sink_evidence

from ._support import (
    eng,
    error_code,
    evidence,
    manifest,
    ok,
    put,
    routed,
    run_sink,
)

REPORT = "deliverables/report.md"
REPORT_BYTES = b"# Cost review\n\nJobs spend is up 12% (list-price DBU estimate).\n"


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # noqa: S324 - Drive's content checksum


def _setup(capsys: Any, store: Any, *, kind: str = "customer_workspace") -> dict[str, Any]:
    pre, route = routed(capsys)
    rf = route["run_folder_id"]
    sink = run_sink(store, rf)
    ev = evidence(pre["run_id"], "capture/rows.json", kind)
    sink_evidence(sink, [ev])
    sink.put_bytes(REPORT, REPORT_BYTES, "text/markdown")
    for stage in ("capture", "analysis", "check"):  # so status reflects publication
        ok(capsys, "commit", "--run-folder", rf, "--stage", stage)
    flags = ("--run-folder", rf, "--report-id", "cost-review", "--revision", "1")
    return {"pre": pre, "rf": rf, "ev": ev, "flags": flags}


def _report(capsys: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    return ok(capsys, "report", "--run-folder", ctx["rf"], "--report-id", "cost-review",
              "--audience", "customer", "--path", REPORT, "--cite-evidence",
              ctx["ev"].evidence_id)


def _delivered(capsys: Any, store: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    _report(capsys, ctx)
    approved = ok(capsys, "approve", *ctx["flags"])
    dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
    delivered = ok(capsys, "deliver", *ctx["flags"], "--destination-folder-id", dest)
    assert delivered["state"] == "delivered" and delivered["publication"] == "complete"
    return {"approved": approved, "delivered": delivered, "dest": dest}


def _record(store: Any, rf: str, cls: Any, record_id: str) -> Any:
    """Load an approval/receipt record from the run folder by its ID."""
    sink = run_sink(store, rf)
    for rel in sink.list(""):
        if record_id in rel:
            return cls.from_dict(json.loads(sink.get_bytes(rel)))
    raise AssertionError(f"{record_id} not found under {rf}: {sink.list('')}")


@pytest.mark.unit
class TestAudience:
    """Spec P2-G14 item 8."""

    def test_customer_report_citing_internal_evidence_is_blocked_and_not_deliverable(
        self, capsys, store
    ) -> None:
        ctx = _setup(capsys, store, kind="internal_mirror")
        out = _report(capsys, ctx)
        assert out["state"] == "blocked_audience" and out["blocked_reasons"]
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        code, env, raw = eng(capsys, "deliver", *ctx["flags"], "--destination-folder-id", dest)
        assert code == 2 and error_code(env) == "DELIVERY_REFUSED", raw
        assert store.list_children(dest) == []
        assert manifest(store, ctx["rf"]).states["publication"] != "complete"

    def test_failed_delivery_is_never_delivered(self, capsys, store) -> None:
        ctx = _setup(capsys, store)
        _report(capsys, ctx)
        ok(capsys, "approve", *ctx["flags"])
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        store.fail_put_after = 0
        code, env, raw = eng(capsys, "deliver", *ctx["flags"], "--destination-folder-id", dest)
        store.fail_put_after = None
        assert code == 4, raw
        assert env["data"]["run_status"] == "publication_pending"
        assert env["data"]["resume"]["stage"] == "publication"
        assert "delivered" not in raw.replace("delivered_", "")
        assert manifest(store, ctx["rf"]).states["publication"] == "pending"
        assert manifest(store, ctx["rf"]).receipts == ()
        status = ok(capsys, "status", "--run-folder", ctx["rf"])
        assert status["run_status"] == "publication_pending"

    def test_approval_and_receipt_are_bound_to_the_exact_report_md5(
        self, capsys, store
    ) -> None:
        ctx = _setup(capsys, store)
        done = _delivered(capsys, store, ctx)
        want = _md5(REPORT_BYTES)
        approval = _record(store, ctx["rf"], Approval, done["approved"]["approval_id"])
        receipt = _record(store, ctx["rf"], DeliveryReceipt, done["delivered"]["receipt_id"])
        assert approval.object_md5 == want and receipt.object_md5 == want
        (copy,) = store.list_children(done["dest"])
        assert copy.md5 == want

    def test_report_edited_after_approval_delivers_the_approved_bytes(
        self, capsys, store
    ) -> None:
        ctx = _setup(capsys, store)
        _report(capsys, ctx)
        ok(capsys, "approve", *ctx["flags"])
        run_sink(store, ctx["rf"]).put_text(REPORT, "# Cost review\n\nEdited after approval.\n")
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        delivered = ok(capsys, "deliver", *ctx["flags"], "--destination-folder-id", dest)
        (copy,) = store.list_children(dest)
        assert copy.md5 == _md5(REPORT_BYTES)  # the pinned revision, not the edit
        receipt = _record(store, ctx["rf"], DeliveryReceipt, delivered["receipt_id"])
        assert receipt.object_md5 == _md5(REPORT_BYTES)


@pytest.mark.unit
class TestPostDeliveryHostArtifact:
    """Coordinator scenario: a host artifact changed after deliver + receipt."""

    def _delivered_with_readme(self, capsys, monkeypatch, store) -> dict[str, Any]:
        ctx = _setup(capsys, store)
        put(capsys, monkeypatch, ctx["rf"], {"README.md": "# Readme v1\n"})
        ok(capsys, "commit", "--run-folder", ctx["rf"], "--stage", "check")
        done = _delivered(capsys, store, ctx)
        receipt = ok(capsys, "receipt", *ctx["flags"], "--channel", "slack",
                     "--external-object-id", "p123", "--destination-id", "C0123")
        assert receipt["receipt_id"]
        return {**ctx, **done}

    def test_changed_put_then_check_commit_rebinds_and_keeps_publication(
        self, capsys, monkeypatch, store
    ) -> None:
        ctx = self._delivered_with_readme(capsys, monkeypatch, store)
        rf = ctx["rf"]
        assert manifest(store, rf).states["publication"] == "complete"
        new = b"# Readme v2\n\nUpdated after delivery.\n"

        put(capsys, monkeypatch, rf, {"README.md": new})
        committed = ok(capsys, "commit", "--run-folder", rf, "--stage", "check")
        assert committed["unchanged"] is False

        m = manifest(store, rf)
        (ref,) = [r for r in m.refs if r.path == "README.md"]
        assert ref.md5 == _md5(new)  # (a)
        read = ok(capsys, "read", "--run-folder", rf, "--path", "README.md")  # (b)
        assert read["excerpt"] == new.decode() and read["md5"] == _md5(new)
        assert m.states["publication"] == "complete"  # (c)
        status = ok(capsys, "status", "--run-folder", rf)
        assert status["states"]["publication"] == "complete"
        assert status["run_status"] == "complete"
        assert ctx["delivered"]["receipt_id"] in m.receipts

    def test_changed_put_without_recommit_reads_uncommitted_until_recommit(
        self, capsys, monkeypatch, store
    ) -> None:
        # (d) ``read`` verifies the downloaded bytes against the live Drive object, and
        # reports ``committed``: true only when the latest committed manifest binds the
        # path at that md5. A report cannot bind uncommitted bytes.
        ctx = self._delivered_with_readme(capsys, monkeypatch, store)
        rf = ctx["rf"]
        before = ok(capsys, "read", "--run-folder", rf, "--path", "README.md")
        assert before["committed"] is True
        committed_md5 = next(r.md5 for r in manifest(store, rf).refs if r.path == "README.md")
        new = b"# Readme v3\n\nNot re-committed.\n"
        put(capsys, monkeypatch, rf, {"README.md": new})

        code, env, raw = eng(capsys, "read", "--run-folder", rf, "--path", "README.md")
        assert code == 0, raw
        assert env["data"]["excerpt"] == new.decode()
        assert env["data"]["md5"] == _md5(new) != committed_md5
        assert env["data"]["committed"] is False
        # The manifest still binds the old bytes until a commit re-binds them.
        assert next(r.md5 for r in manifest(store, rf).refs
                    if r.path == "README.md") == committed_md5
        assert manifest(store, rf).states["publication"] == "complete"

        ok(capsys, "commit", "--run-folder", rf, "--stage", "check")
        after = ok(capsys, "read", "--run-folder", rf, "--path", "README.md")
        assert after["committed"] is True and after["md5"] == _md5(new)


@pytest.mark.unit
class TestReportNeedsCommittedBytes:
    def test_report_refuses_an_uncommitted_body(self, capsys, store) -> None:
        ctx = _setup(capsys, store)
        run_sink(store, ctx["rf"]).put_text(REPORT, "# Cost review\n\nNot committed.\n")
        code, env, raw = eng(capsys, "report", "--run-folder", ctx["rf"],
                             "--report-id", "cost-review", "--audience", "customer",
                             "--path", REPORT, "--cite-evidence", ctx["ev"].evidence_id)
        assert code == 2, raw
        assert error_code(env) == "UNCOMMITTED_ARTIFACT"
        assert not any(p.startswith("reports/") for p in run_sink(store, ctx["rf"]).list())

        ok(capsys, "commit", "--run-folder", ctx["rf"], "--stage", "check")
        assert _report(capsys, ctx)["state"] == "ready"
