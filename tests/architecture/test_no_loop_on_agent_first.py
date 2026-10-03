# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Architecture fitness test — native-first Phase 0 guardrail.

The deterministic, "agent-first" entrypoints (the ``python -m starboard_x.<domain>``
CLIs and the ``starboard review`` command path) must deliver their capability
WITHOUT the conversational multi-agent loop under ``starboard.agents``. Importing
one of these modules must not drag in ``starboard.agents`` — that is precisely what
lets later simplification phases delete the loop without a capability regression.

This test must stay green forever. If it fails, an agent-first entrypoint grew a
dependency on the conversational loop and the loop can no longer be removed safely.

STATUS: Enforced (passing). ``--discover`` already routes through
``starboard.discovery.engine.DiscoveryEngine`` (not the loop), and the
``starboard_x`` domains live in the kernel tier which cannot import the loop.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

# Deterministic, non-loop entrypoints for each parity-matrix capability.
# (The public ``genie ask`` adapter was removed — NL Q&A is delegated to the
# host's native Genie — so it is intentionally absent here.)
AGENT_FIRST_MODULES = [
    "starboard_x.discovery",
    "starboard_x.review",
    "starboard_x.warehouse",
    "starboard_x.cluster",
    "starboard_x.uc",
    "starboard_x.diagnostic",
    "starboard.cli.cli.review_command",
]


@pytest.mark.parametrize("module", AGENT_FIRST_MODULES)
def test_agent_first_module_does_not_import_agent_loop(module: str) -> None:
    """Importing an agent-first entrypoint must not import ``starboard.agents``."""
    code = (
        "import importlib, sys\n"
        f"importlib.import_module({module!r})\n"
        "leaked = sorted(\n"
        "    m for m in sys.modules\n"
        "    if m == 'starboard.agents' or m.startswith('starboard.agents.')\n"
        ")\n"
        "assert not leaked, 'agent loop imported: ' + repr(leaked)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{module} pulled in the conversational agent loop (starboard.agents):\n"
        f"{result.stderr}"
    )
