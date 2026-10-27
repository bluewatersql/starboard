# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared fakes for the phase-2 ``starboard_x`` writer tests (discovery, review).

* a deterministic fake ``EngineResult`` (duck-typed, no polars),
* an in-memory Drive run (descriptor + verified identity check),
* helpers to fake the overlay and sandbox HOME, cwd and TMPDIR.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement.commit import write_descriptor
from starboard_core.engagement.folders import IDENTITY_PROPERTY
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.records import (
    AccountRef,
    DriveContext,
    IdentityCheck,
    RunAuthorization,
)
from starboard_core.ports.engagement_storage import Grant

RID = "20261008_12345678-1234-4234-8234-123456789abc"
OTHER_RID = "20261008_87654321-4321-4234-8234-cba987654321"
WS = "123"
GOLDEN = Path(__file__).parent / "golden"


# --- fake discovery result ------------------------------------------------------------


class Df:
    """Minimal polars-like duck type (``to_dicts`` / ``columns``)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.columns = list(rows[0]) if rows else []
        self._rows = rows

    def to_dicts(self) -> list[dict[str, Any]]:
        return list(self._rows)


def _qr(query_id: str, domain: str, rows: list[dict[str, Any]] | None, **kw: Any):
    return SimpleNamespace(
        query_id=query_id,
        domain=domain,
        data=None if rows is None else Df(rows),
        error=kw.pop("error", None),
        row_count=0 if rows is None else len(rows),
        succeeded=rows is not None,
        skipped=False,
        result_limit=kw.pop("result_limit", None),
        lookback_days=30,
        execution_time_ms=12.34,
        attempts=1,
        attempt_elapsed_ms=[12.34],
    )


def fake_result() -> SimpleNamespace:
    """Two packs, three queries (one failed), values that need ``default=str``."""
    billing = SimpleNamespace(
        pack_id="billing",
        domain="billing",
        results=[
            _qr(
                "F-01",
                "billing",
                [
                    {
                        "workspace_id": WS,
                        "billing_origin_product": "JOBS",
                        "usage_unit": "DBU",
                        "window_start": "2026-09-01",
                        "window_end": "2026-09-30",
                        "usage_quantity": Decimal("600.5"),
                    }
                ],
            ),
            _qr("F-02", "billing", None, error="PARSE_SYNTAX_ERROR"),
        ],
    )
    gov = SimpleNamespace(
        pack_id="Governance (UC)",
        domain="governance",
        results=[
            _qr(
                "G-01",
                "governance",
                [{"catalog": "main", "tables": 3}, {"catalog": "dev", "tables": 1}],
            )
        ],
    )
    return SimpleNamespace(
        trace_id="trace-1",
        elapsed_ms=1.0,
        errors=["F-02: PARSE_SYNTAX_ERROR"],
        audit_result=SimpleNamespace(succeeded=True),
        pack_results=[billing, gov],
        domain_analyses=[],
    )


class FakeEngine:
    def __init__(self, result: Any) -> None:
        self._result = result

    async def run(self) -> Any:
        return self._result


# --- fake Drive run -------------------------------------------------------------------


def identity_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": 1,
        "run_id": RID,
        "provisional_account_key": "acme",
        "provisional_account_name": "Acme Corp",
        "provisional_source": "operator",
        "expected_workspace_id": WS,
        "expected_host": None,
        "observed_workspace_id": WS,
        "observed_host": "https://acme.cloud.databricks.com",
        "principal_id": "7781234",
        "principal_kind": "user",
        "checked_at": "2026-10-08T09:00:00+00:00",
        "status": "verified",
        "reasons": [],
    }
    record.update(overrides)
    return record


def drive_run(
    *,
    workspace_ids: tuple[str, ...] = (WS,),
    identity: dict[str, object] | None | bool = True,
    identity_in: str = "run",
    run_id: str = RID,
    source_mode: SourceMode = SourceMode.CUSTOMER_WORKSPACE,
    basis: str | None = None,
    workspace_profile: str | None = None,
) -> tuple[InMemoryEngagementStorage, str]:
    """An authorized Drive run folder (a ``source_mode`` run, customer by default).

    Args:
        identity: ``True`` for a verified identity check, a dict for a custom
            record, ``False``/``None`` for none.
        identity_in: ``run`` (``<run>/analysis/identity-check.json``) or
            ``staging`` (``<preflight_folder_id>/identity-check.json``).
        basis / workspace_profile: ``authorized_scope.basis`` and the verified
            ``--profile`` the descriptor records (``None``: not recorded).
    """
    store = InMemoryEngagementStorage()
    folder = store.create_folder(store.root_folder_id(), "run", {})
    store.set_access(
        folder.id,
        can_add_children=True,
        grants=(Grant(kind="user", role="owner"),),
        complete=True,
    )
    staging = store.create_folder(store.root_folder_id(), "staging", {})
    fp = store.inspect_access(folder.id).fingerprint
    drive = DriveContext(
        provider="google_drive",
        principal="perm-1",
        route="account",
        base_folder_id="base",
        root_folder_id="root",
        run_folder_id=folder.id,
        registry_folder_id="reg",
        account_key="acme",
        acl_classification="restricted",
        permission_fingerprints={folder.id: fp},
        capabilities={"upload": True},
        created_at="2026-10-08T09:00:00+00:00",
        idempotency_key="sbk1_" + "a" * 64,
        preflight_folder_id=staging.id,
    )
    write_descriptor(
        store,
        folder.id,
        RunAuthorization(
            engagement_id="acme/workspace/ws-123",
            run_id=run_id,
            intent="discovery",
            task="workspace",
            account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
            requested_scope={"workspace_ids": list(workspace_ids)},
            authorized_scope={
                "account_key": "acme",
                "workspace_ids": list(workspace_ids),
                **({"basis": basis} if basis else {}),
            },
            reporting_interval="P30D",
            timezone="UTC",
            source_mode=source_mode,
            storage_policy=StoragePolicy.DRIVE_REQUIRED,
            audience="internal",
            methodology_version="m1",
            drive=drive,
            workspace_profile=workspace_profile,
        ),
    )
    if identity:
        record = identity_record() if identity is True else dict(identity)
        IdentityCheck.from_dict(record)  # the fixture itself must be a valid record
        props: dict[str, str] = {}
        if identity_in == "run":
            # Sink-compatible layout: the same folder/file identities DriveRunSink
            # uses, so later ``analysis/...`` writes reuse this folder.
            parent = store.create_folder(
                folder.id, "analysis", {IDENTITY_PROPERTY: "artifact-dir:analysis"}
            ).id
            props = {
                "starboard_artifact": "analysis/identity-check.json",
                "starboard_run": run_id,
            }
        else:
            parent = staging.id
        store.put_stream(
            parent,
            "identity-check.json",
            "application/json",
            [json.dumps(record).encode()],
            properties=props,
        )
    return store, folder.id


# --- environment ----------------------------------------------------------------------


def covered_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: InMemoryEngagementStorage
) -> dict[str, Path]:
    """Fake the overlay and sandbox HOME, cwd and TMPDIR."""
    import tempfile

    sandbox = {name: tmp_path / name for name in ("home", "cwd", "tmp")}
    for path in sandbox.values():
        path.mkdir()
    monkeypatch.setenv("STARBOARD_OVERLAY", "1")
    monkeypatch.setenv("HOME", str(sandbox["home"]))
    monkeypatch.setenv("TMPDIR", str(sandbox["tmp"]))
    monkeypatch.setattr(tempfile, "tempdir", str(sandbox["tmp"]))
    monkeypatch.chdir(sandbox["cwd"])
    return sandbox


def written(sink: Any, prefix: str = "") -> set[str]:
    """Relpaths in a run besides the fixture's own ``analysis/identity-check.json``."""
    return set(sink.list(prefix)) - {"analysis/identity-check.json"}


def local_run_dir(
    root: Path,
    *,
    source_mode: SourceMode = SourceMode.INTERNAL_ONLY,
    storage_policy: StoragePolicy = StoragePolicy.INTERNAL_ONLY_LOCAL,
) -> Path:
    """A local run directory with ``analysis/run-authorization.json`` (D-11)."""
    run_dir = root / "local-run"
    (run_dir / "analysis").mkdir(parents=True)
    auth = RunAuthorization(
        engagement_id="internal/workspace/ws-123",
        run_id=RID,
        intent="discovery",
        task="workspace",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={},
        authorized_scope={"account_key": "acme"},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=source_mode,
        storage_policy=storage_policy,
        audience="internal",
        methodology_version="m1",
    )
    (run_dir / "analysis" / "run-authorization.json").write_text(
        json.dumps(auth.to_dict())
    )
    return run_dir
