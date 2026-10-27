"""Account registry commands: ``import-local`` (the internal-only bridge) and ``rebuild-index``."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starboard_skills.helpers.contract import (
    ArgError,
)
from starboard_skills.helpers.engagement import _envelope
from starboard_skills.helpers.engagement._envelope import (
    ARTIFACT_PROPERTY,
    AUTHORIZATION_RECORD,
    FINDINGS_MANIFEST_PATH,
    IMPORT_SUMMARY,
    OBSERVATIONS_PATH,
    SHARED_REGISTRY_ENV,
    Refusal,
    _ctx,
    _storage_errors,
)
from starboard_skills.helpers.engagement._runs import (
    _close,
    _internal_domains,
    _md5,
    _parse_observations,
    _same_sf_id,
    _storage_ref,
)

if TYPE_CHECKING:  # kernel types only; imported lazily at runtime
    from starboard_core.ports.engagement_storage import EngagementStoragePort


# --------------------------------------------------------------------------- #
# import-local / rebuild-index (registry)
# --------------------------------------------------------------------------- #
def _customer_sourced(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("source_kind") == "customer_workspace":
            return True
        return any(_customer_sourced(v) for v in value.values())
    if isinstance(value, list):
        return any(_customer_sourced(v) for v in value)
    return False


def _registry_handles(
    storage: EngagementStoragePort,
    account_key: str,
    account_name: str | None,
    args: Any,
    warnings: list[str],
) -> Any:
    from starboard_core.engagement.registry import ensure_registry  # lazy – kernel dep

    try:
        return ensure_registry(
            storage,
            account_key,
            account_name=account_name,
            shared_root_id=os.environ.get(SHARED_REGISTRY_ENV, "").strip() or None,
            internal_domains=_internal_domains(args),
            warnings=warnings,
        )
    except ValueError as exc:
        raise ArgError(str(exc)) from exc


def cmd_import_local(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.engagement.access import is_restricted  # lazy – kernel dep
    from starboard_core.engagement.folders import ensure_folder
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import Registration, RunAuthorization
    from starboard_core.engagement.registry import (
        import_registration_id,
        list_registrations,
        register,
    )
    from starboard_core.engagement.staging import encode_json, put_json

    ctx = _ctx(args)
    if not args.confirm:
        raise Refusal(
            "CONFIRM_REQUIRED",
            "import-local publishes a summary of a local run to Drive; pass --confirm "
            "to record the operator's permission",
        )
    if args.unattended:
        raise Refusal("IMPORT_REFUSED", "import-local needs an attended operator")
    run_dir = Path(args.run_dir)
    path = run_dir / AUTHORIZATION_RECORD
    try:
        auth = RunAuthorization.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise ArgError(f"--run-dir: no run descriptor at {path}") from exc
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ArgError(
            f"--run-dir: {path} is not a valid run descriptor ({exc})"
        ) from exc
    ctx["run_id"] = auth.run_id
    if (
        auth.storage_policy is not StoragePolicy.INTERNAL_ONLY_LOCAL
        or auth.source_mode is not SourceMode.INTERNAL_ONLY
    ):
        raise Refusal(
            "IMPORT_REFUSED",
            f"run {auth.run_id} is {auth.storage_policy.value}/{auth.source_mode.value}; "
            "only internal_only_local runs can be imported",
        )
    account_key = (args.account_key or "").strip()
    if not account_key or not _same_sf_id(account_key, auth.account.id):
        raise ArgError(
            f"--account-key {account_key!r} does not match the run's account {auth.account.id!r}"
        )
    root = run_dir.resolve()
    files = sorted(run_dir.rglob("*.json"))
    for file in files:
        rel = file.relative_to(run_dir).as_posix()
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise Refusal(
                "IMPORT_REFUSED",
                f"{rel} is a symlink (or resolves outside the run directory); a linked "
                "file cannot be checked as the run's own output, so the run is not "
                "imported",
            )
        if not file.is_file():
            continue
        try:
            parsed = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Refusal(
                "IMPORT_REFUSED",
                f"{rel} could not be read ({exc}); an unreadable file cannot be "
                "checked for customer evidence, so the run is not imported",
            ) from exc
        if _customer_sourced(parsed):
            raise Refusal(
                "IMPORT_REFUSED",
                f"{rel} holds customer_workspace evidence; "
                "customer data is never imported from a local run",
            )
    observations: list[Any] = []
    obs_file = run_dir / OBSERVATIONS_PATH
    if obs_file.is_file():
        try:
            observations = _parse_observations(
                json.loads(obs_file.read_text(encoding="utf-8")), OBSERVATIONS_PATH
            )
        except (OSError, ValueError) as exc:
            raise ArgError(
                f"{obs_file} is not a valid observation list ({exc})"
            ) from exc
    manifest_file = run_dir / FINDINGS_MANIFEST_PATH
    findings: dict[str, Any] | None = None
    if manifest_file.is_file():
        try:
            fm = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ArgError(f"{manifest_file} is not valid JSON ({exc})") from exc
        items = fm.get("findings") if isinstance(fm, dict) else None
        findings = {
            "snapshot_version": fm.get("snapshot_version")
            if isinstance(fm, dict)
            else None,
            "finding_count": len(items) if isinstance(items, list) else 0,
        }
    summary = {
        "schema_version": 1,
        "kind": "local_import_summary",
        "local_run_id": auth.run_id,
        "engagement_id": auth.engagement_id,
        "account_key": auth.account.id,
        "task": auth.intent,
        "task_name": auth.task,
        "observations": [o.to_dict() for o in observations],
        "findings": findings,
    }

    warnings: list[str] = []
    ctx["warnings"] = warnings
    storage = _envelope._make_storage()
    try:
        with _storage_errors(False, auth.run_id):
            handles = _registry_handles(
                storage, auth.account.id, auth.account.display_name, args, warnings
            )
            operator = handles[0]
            summary_md5 = _md5(encode_json(summary))
            existing = None
            for view in list_registrations(
                storage, handles, account_key=auth.account.id
            ):
                reg = view.registration
                if (
                    reg is not None
                    and reg.kind == "imported_local"
                    and reg.provenance.get("local_run_id") == auth.run_id
                ):
                    existing = reg
                    held = reg.observation_summary_ref
                    if held is None or held.md5 != summary_md5:
                        raise Refusal(
                            "IMPORT_REFUSED",
                            f"local run {auth.run_id} is already imported as "
                            f"{reg.registration_id} with a different summary; a "
                            "registration is write-once, so import a new local run",
                        )
                    break
            imports = ensure_folder(
                storage, operator.folder_id, "imports", "registry-imports"
            )
            folder = ensure_folder(
                storage,
                imports.id,
                auth.run_id,
                f"import:{auth.run_id}",
                adopt_untagged=False,
            )
            obj = put_json(
                storage,
                folder.id,
                IMPORT_SUMMARY,
                summary,
                properties={ARTIFACT_PROPERTY: f"import-summary:{auth.run_id}"},
            )
            summary_ref = _storage_ref(f"imports/{auth.run_id}/{IMPORT_SUMMARY}", obj)
            principal = storage.principal_id()
            if existing is not None:
                reg = existing
            else:
                reg = Registration(
                    registration_id=import_registration_id(auth.run_id),
                    kind="imported_local",
                    run_id=auth.run_id,
                    engagement_id=auth.engagement_id,
                    account_key=auth.account.id,
                    task=auth.intent,
                    task_name=auth.task,
                    route="account",
                    source_mode=SourceMode.INTERNAL_ONLY,
                    storage_policy=StoragePolicy.INTERNAL_ONLY_LOCAL,
                    run_folder_id=None,
                    descriptor_ref=None,
                    observation_summary_ref=summary_ref,
                    acl_classification="owner_only"
                    if is_restricted(operator.access)
                    else "internal_only",
                    principal_id=principal,
                    registered_at=_envelope._now(),
                    provenance={
                        "origin": "local_reference",
                        "local_run_id": auth.run_id,
                        "approved_by": principal,
                    },
                )
            for handle in handles:
                register(storage, handle, reg)
    finally:
        _close(storage)
    return {
        "run_id": auth.run_id,
        "registration_id": reg.registration_id,
        "registry_folder_id": operator.folder_id,
        "imported_refs": [summary_ref.to_dict()],
        "observations": len(observations),
        "warnings": warnings,
    }


def cmd_rebuild_index(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.engagement.registry import (  # lazy – kernel dep
        read_index,
        rebuild_index,
    )

    account_key = (args.account_key or "").strip()
    if not account_key:
        raise ArgError("--account-key is required")
    warnings: list[str] = []
    _ctx(args)["warnings"] = warnings
    storage = _envelope._make_storage()
    try:
        with _storage_errors(False, None):
            handles = _registry_handles(
                storage, account_key, args.account_name, args, warnings
            )
            out = []
            for handle in handles:
                obj = rebuild_index(storage, handle)
                entries = read_index(storage, handle)
                match = re.match(r"rev-(\d+)\.json$", obj.name or "")
                out.append(
                    {
                        "location": handle.location,
                        "folder_id": handle.folder_id,
                        "index_object_id": obj.id,
                        "index_revision": int(match.group(1)) if match else None,
                        "entries": None if entries is None else len(entries),
                    }
                )
    finally:
        _close(storage)
    return {
        "account_key": account_key,
        "entries": out[0]["entries"],
        "index_revision": out[0]["index_revision"],
        "handles": out,
        "warnings": warnings,
    }
