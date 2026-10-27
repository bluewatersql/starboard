"""``engagement source-options``: the read-only menu of source modes and stores.

Run before ``preflight`` so the entry skill can map the operator's wording onto
``--source-mode`` (and ``--storage``). It creates no run, calls no storage, reads
no file and never lists or selects a Databricks profile. The storage policy and
the permitted stores come from the kernel's ``classify_storage``, which returns a
decision (with ``refusal`` set for a store that is not permitted) and does not
raise.
"""

from __future__ import annotations

import argparse
from typing import Any, Literal

from starboard_skills.helpers.contract import ArgError
from starboard_skills.helpers.engagement import _envelope
from starboard_skills.helpers.engagement._envelope import TASKS

# Probe order: the store a policy defaults to is listed first, then the other.
_STORES: tuple[Literal["drive", "local"], ...] = ("drive", "local")

_WHAT = {
    "internal_only": "internal telemetry only",
    "customer_workspace": "the customer workspace",
    "hybrid": "internal telemetry and the customer workspace",
}


def _question(options: list[dict[str, Any]]) -> str:
    """The source question to ask as is: each option with its storage and auth need."""
    lines = ["Which source should this run use?"]
    for o in options:
        auth = (
            "Needs a workspace profile."
            if o["needs_workspace_auth"]
            else "No workspace sign-in."
        )
        lines.append(
            f"- {o['source_mode']}: {_WHAT[o['source_mode']]}. Storage: "
            f"{o['storage_policy']} ({' or '.join(o['storage_choices'])}). {auth}"
        )
    return "\n".join(lines)


def cmd_source_options(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.engagement.policy import (  # lazy – kernel dep
        SourceMode,
        StoragePolicy,
        classify_storage,
    )

    # Validated here, not by argparse: a parser error exits 4 (the helper's
    # parse-error code), a usage error is 2.
    if args.task is not None and args.task not in TASKS:
        raise ArgError(f"--task must be one of {', '.join(TASKS)}; got {args.task!r}")
    overlay = _envelope._detect_overlay()
    modes = (
        (SourceMode.INTERNAL_ONLY, SourceMode.CUSTOMER_WORKSPACE, SourceMode.HYBRID)
        if overlay.enabled
        else (SourceMode.CUSTOMER_WORKSPACE,)
    )
    options: list[dict[str, Any]] = []
    for mode in modes:
        policy = classify_storage(mode, overlay, requested=None).policy
        default = "local" if policy is StoragePolicy.LOCAL else "drive"
        choices = [default] + [
            store
            for store in _STORES
            if store != default
            and classify_storage(mode, overlay, requested=store).refusal is None
        ]
        options.append(
            {
                "source_mode": mode.value,
                "storage_policy": policy.value,
                "storage_choices": choices,
                "default_storage": default,
                "needs_workspace_auth": mode is not SourceMode.INTERNAL_ONLY,
            }
        )
    return {
        "overlay_enabled": overlay.enabled,
        "choice_required": overlay.enabled,
        "options": options,
        # Ask this as is when a choice is required (null otherwise).
        "question": _question(options) if overlay.enabled else None,
    }
