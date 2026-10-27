# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Capability-parity characterization — native-first Phase 0.

Every user-facing capability must have a deterministic, non-loop entrypoint that
is proven to work BEFORE later phases delete the conversational agent loop and
its plumbing. This suite is the parity matrix, executable:

* the ``python -m starboard_x.<domain>`` CLIs emit the stable
  ``starboard_x.contract`` envelope (proven here offline, via the arg-error path —
  no live Databricks call needed);
* the deterministic backing services (DiscoveryEngine, WorkloadReviewService)
  are importable through the public API;
* the skill-delivered domains (job/query/finops/analyze) ship their skills;
* NL data Q&A is intentionally delegated to the host's native Genie — there is no
  Starboard NL entrypoint (the public ``genie ask`` adapter was removed).

If a row here goes red, a capability lost its deterministic entrypoint and no
plumbing beneath it may be deleted until parity is restored.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

# Capabilities with a deterministic ``python -m starboard_x.<domain>`` entrypoint
# that emits the contract envelope.
DETERMINISTIC_X_DOMAINS = [
    "discovery",
    "review",
    "warehouse",
    "cluster",
    "uc",
    "diagnostic",
]

# Capabilities delivered via the skills tree + ``starboard-helper`` (host-orchestrated)
# rather than a dedicated ``starboard_x`` module.
SKILL_DELIVERED_DOMAINS = ["job", "query", "finops", "analyze"]


@pytest.mark.parametrize("domain", DETERMINISTIC_X_DOMAINS)
def test_x_entrypoint_emits_contract_envelope(domain: str) -> None:
    """``python -m starboard_x.<domain>`` is wired to the contract envelope.

    Invoked with no arguments it takes the arg-error path (exit code 4) and emits
    a well-formed envelope carrying the correct ``domain`` — proving a
    deterministic, offline, non-loop entrypoint exists for the capability.
    """
    result = subprocess.run(
        [sys.executable, "-m", f"starboard_x.{domain}"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 4, (
        f"starboard_x.{domain}: expected arg-error exit 4, got {result.returncode}.\n"
        f"stderr: {result.stderr[:500]}"
    )
    envelope = json.loads(result.stdout)
    assert envelope["domain"] == domain
    assert envelope["ok"] is False  # arg-error envelope
    assert {"ok", "domain", "command", "data", "error", "meta"} <= set(envelope)


def test_discovery_backing_engine_is_importable() -> None:
    """The DiscoveryEngine backing ``--discover`` + ``starboard_x.discovery`` is present."""
    from starboard.bootstrap import DiscoveryEngine, EngineConfig

    assert DiscoveryEngine is not None
    assert EngineConfig is not None


def test_review_backing_service_is_importable() -> None:
    """Workload review's deterministic backing service + severity gate are present."""
    from starboard import WorkloadReviewService  # public API facade
    from starboard.tools.services.workload_review_service import SeverityGate

    assert WorkloadReviewService is not None
    assert SeverityGate is not None


@pytest.mark.parametrize("domain", SKILL_DELIVERED_DOMAINS)
def test_skill_delivered_domain_has_skill(domain: str) -> None:
    """job/query/finops/analyze are delivered through the canonical skills tree."""
    skill_dir = (
        _REPO_ROOT
        / "packages"
        / "starboard-skills"
        / "skills"
        / "starboard"
        / f"starboard-{domain}"
    )
    assert skill_dir.is_dir(), f"missing skill for {domain}: {skill_dir}"


def test_nl_query_has_no_public_loop_entrypoint() -> None:
    """NL data Q&A is delegated to the host's native Genie — no Starboard CLI.

    The public ``genie ask`` command/adapter was removed; this documents that the
    capability intentionally has no first-party entrypoint (only the gated
    internal ``CuratedGenieRoomAdapter`` behind the NLQueryPort seam).
    """
    import importlib.util

    assert importlib.util.find_spec("starboard.cli.cli.genie_command") is None
