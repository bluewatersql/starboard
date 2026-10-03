"""OpenCode backend for starboard-maint.

OpenCode has no package channel (no plugin registry or CLI installer).
This backend emits copy-paste prompt-based install instructions only.
"""
from __future__ import annotations


def install_instructions(scope: str) -> str:
    """Return copy-paste installation instructions for OpenCode.

    Since OpenCode lacks a package channel, users must paste the Starboard
    skill text into OpenCode's agent/rules configuration manually.
    """
    scope_note = (
        "project (paste into your project's OpenCode config directory)"
        if scope == "project"
        else "user (paste into your global OpenCode config directory)"
    )
    return f"""
Starboard for OpenCode — Manual Install Instructions
=====================================================

OpenCode does not have a plugin marketplace. Install Starboard by:

1. Install the helper CLI:

   pip install starboard-skills
   # or: uv pip install starboard-skills

2. Add Starboard to your OpenCode agent configuration.
   Scope: {scope_note}

   Create or edit your OpenCode skills/agents config and add:

   ---
   name: starboard
   description: >
     AI-powered Databricks workload analysis. Use for warehouse sizing,
     job diagnostics, Unity Catalog, cluster optimization, and FinOps.
   commands:
     - starboard-helper warehouse list
     - starboard-helper job list --limit 20
     - python -m starboard_x.warehouse list
     - python -m starboard_x.diagnostic --run-id <RUN_ID>
   ---

3. Verify the helper works:

   starboard-helper warehouse list

   (Expects DATABRICKS_HOST and DATABRICKS_TOKEN in environment, or a
   configured ~/.databrickscfg profile.)

4. Full skill documentation: see packages/starboard-skills/skills/starboard/
   in the Starboard repository, or https://github.com/databricks/starboard

No automated install/remove is available for OpenCode.
Run `starboard-maint verify --host opencode` to check helper availability.
"""


def verify() -> tuple[bool, str]:
    """Check that the starboard-helper is available (minimum OpenCode requirement)."""
    import shutil
    if shutil.which("starboard-helper") is None:
        return False, (
            "starboard-helper not found on PATH.\n"
            "Fix: pip install starboard-skills"
        )
    return True, "OK: starboard-helper is available for OpenCode"
