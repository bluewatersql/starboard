"""P2-G14 exit test 9 - the local -> Drive bridge (``import-local``).

An internal-only local run, imported with ``import-local --confirm``, is visible
to a later Drive-backed run's ``history`` as a baseline candidate. A local run
whose evidence came from a customer workspace is refused (``IMPORT_REFUSED``)
and nothing reaches the registry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.registry import (
    RegistryNotFoundError,
    ensure_registry,
    list_registrations,
)
from starboard_skills.helpers import engagement

from ._support import ACCOUNT, eng, error_code, observation, ok, routed, sink_put

SEP = ("2026-09-01", "2026-09-30")
OCT = ("2026-10-01", "2026-10-31")


def _internal_local_run(capsys: Any) -> tuple[str, Path]:
    pre = ok(
        capsys, "preflight", "--source-mode", "internal_only", "--task", "discovery",
        "--task-name", "ws-123", "--account-key", ACCOUNT, "--account-name", "Acme Corp",
        "--storage", "local", "--internal-workspace-id", "123",
    )
    assert pre["storage_decision"] == "internal_only_local"
    run_dir = Path(pre["local_run_dir"])
    ok(capsys, "route", "--run-dir", str(run_dir))
    return pre["run_id"], run_dir


def _import(capsys: Any, run_dir: Path) -> tuple[int, dict[str, Any], str]:
    return eng(capsys, "import-local", "--run-dir", str(run_dir), "--account-key", ACCOUNT,
               "--confirm")


def _registrations(store: Any) -> list[Any]:
    views = list_registrations(store, ensure_registry(store, ACCOUNT), account_key=ACCOUNT)
    return [v.registration for v in views if v.registration is not None]


@pytest.mark.unit
class TestBridge:
    """Spec P2-G14 item 9."""

    def test_imported_internal_local_run_is_a_baseline_for_a_drive_run(
        self, capsys, store
    ) -> None:
        local_id, run_dir = _internal_local_run(capsys)
        base = observation(local_id, "job-1", value=10.0, start=SEP[0], end=SEP[1],
                           source_kind="internal_mirror")
        (run_dir / engagement.OBSERVATIONS_PATH).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / engagement.OBSERVATIONS_PATH).write_text(json.dumps([base.to_dict()]))
        code, env, raw = _import(capsys, run_dir)
        assert code == 0, raw
        reg_id = env["data"]["registration_id"]
        assert reg_id.startswith("reg_imp_")

        pre, route = routed(capsys)
        rf = route["run_folder_id"]
        sink_put(store, rf, {engagement.OBSERVATIONS_PATH: [
            observation(pre["run_id"], "job-1", value=12.0, start=OCT[0],
                        end=OCT[1]).to_dict()]})
        data = ok(capsys, "history", "--run-folder", rf, "--interval-start", OCT[0],
                  "--interval-end", OCT[1])

        assert data["candidates"] == 1 and data["unavailable"] == []
        (entry,) = data["selected"]
        assert entry["baseline_observation_id"] == base.observation_id
        assert entry["comparison"] == "continuing"
        kinds = {r.registration_id: r.kind for r in _registrations(store)}
        assert kinds[reg_id] == "imported_local"

    def test_customer_sourced_local_run_is_refused(self, capsys, store) -> None:
        _, run_dir = _internal_local_run(capsys)
        (run_dir / "capture").mkdir(exist_ok=True)
        (run_dir / "capture" / "rows.json").write_text(
            json.dumps({"rows": [{"source_kind": "customer_workspace"}]}))
        objects = store.object_count

        code, env, raw = _import(capsys, run_dir)

        assert code == 2 and error_code(env) == "IMPORT_REFUSED", raw
        assert store.object_count == objects  # not even the account registry exists
        with pytest.raises(RegistryNotFoundError):
            ensure_registry(store, ACCOUNT)
