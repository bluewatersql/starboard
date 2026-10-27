#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Generate Claude Code agent definition files from the canonical source.

Single source of truth: ``packages/starboard-skills/agents/*.yaml``.
Each YAML defines one agent (subagent, orchestrator, or autonomous).
This script reads those definitions and emits Claude Code ``.claude/agents/*.md``
files (frontmatter: name/description/tools/model + Markdown body) into
``plugin/agents/``.

Codex/Isaac/OpenCode emission is reserved for the Item-08 converter
(``scripts/port_to_opencode.py``); this script handles Claude Code output only.

Usage::

    python scripts/gen_agents.py             # write plugin/agents/*.md
    python scripts/gen_agents.py --check     # verify committed files are up to date (CI)

``--check`` exits non-zero (without writing) when any generated file has drifted
from what the canonical source would produce.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML required — pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths (resolved from script location so the script works from any cwd)
# ---------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
CANONICAL_DIR: Path = REPO_ROOT / "packages" / "starboard-skills" / "agents"
OUTPUT_DIR: Path = REPO_ROOT / "plugin" / "agents"

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS: tuple[str, ...] = ("name", "description", "kind", "model", "tools", "body")
_VALID_KINDS: frozenset[str] = frozenset({"subagent", "orchestrator", "autonomous"})
_VALID_MODELS: frozenset[str] = frozenset({"sonnet", "opus", "haiku", "inherit"})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(agent: dict[str, Any], src: Path) -> None:
    """Raise ``ValueError`` if the agent dict is missing required fields or has invalid values."""
    missing = [f for f in _REQUIRED_FIELDS if f not in agent]
    if missing:
        raise ValueError(f"{src.name}: missing required fields: {missing}")
    if agent["kind"] not in _VALID_KINDS:
        raise ValueError(
            f"{src.name}: invalid kind={agent['kind']!r}; "
            f"must be one of {sorted(_VALID_KINDS)}"
        )
    if agent["model"] not in _VALID_MODELS:
        raise ValueError(
            f"{src.name}: invalid model={agent['model']!r}; "
            f"must be one of {sorted(_VALID_MODELS)}"
        )
    if not isinstance(agent["tools"], list) or not agent["tools"]:
        raise ValueError(f"{src.name}: tools must be a non-empty list")
    if agent["kind"] == "orchestrator" and "dispatches_to" not in agent:
        raise ValueError(f"{src.name}: orchestrator agents must have a 'dispatches_to' list")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _tools_inline(tools: list[str]) -> str:
    """Format a tools list as an inline YAML sequence, e.g. ``[Bash, Read, Task]``."""
    return "[" + ", ".join(tools) + "]"


def render_claude_code(agent: dict[str, Any]) -> str:
    """Render a Claude Code ``.md`` agent definition from a canonical agent dict.

    Output format::

        ---
        name: <name>
        description: >-
          <description lines>
        tools: [<tools>]
        model: <model>
        ---

        <Markdown body>

    The four frontmatter fields (name, description, tools, model) are the only
    fields Claude Code requires.  Additional canonical-source fields (kind,
    skill_ref, dispatches_to, trigger_recipe) are intentionally omitted from
    the generated file — they live in the canonical source only.
    """
    desc = str(agent["description"]).strip()
    lines: list[str] = ["---"]
    lines.append(f"name: {agent['name']}")
    # Use YAML folded block scalar (>-) so long one-liner descriptions
    # are rendered cleanly while still parsing as a single string.
    lines.append("description: >-")
    for part in desc.splitlines():
        lines.append(f"  {part}")
    lines.append(f"tools: {_tools_inline(agent['tools'])}")
    lines.append(f"model: {agent['model']}")
    lines.append("---")
    lines.append("")
    lines.append(str(agent["body"]).strip())
    lines.append("")  # ensure trailing newline
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_agents(canonical_dir: Path) -> list[dict[str, Any]]:
    """Load and validate all canonical agent YAML files from *canonical_dir*."""
    sources = sorted(canonical_dir.glob("*.yaml"))
    if not sources:
        raise FileNotFoundError(f"No .yaml files found in {canonical_dir}")
    agents: list[dict[str, Any]] = []
    for src in sources:
        data: dict[str, Any] = yaml.safe_load(src.read_text(encoding="utf-8"))
        _validate(data, src)
        agents.append(data)
    return agents


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate(
    canonical_dir: Path = CANONICAL_DIR,
    output_dir: Path = OUTPUT_DIR,
    check: bool = False,
    verbose: bool = False,
) -> list[str]:
    """Generate (or check) Claude Code agent ``.md`` files from the canonical YAML source.

    Args:
        canonical_dir: Directory containing ``*.yaml`` canonical agent definitions.
        output_dir: Directory where Claude Code ``.md`` files are written.
        check: When ``True``, compare rendered content against committed files and
               return a list of drift items instead of writing.
        verbose: When ``True`` (and ``check=False``), print each written file path.

    Returns:
        Empty list when up-to-date; list of ``"<filename> (reason)"`` strings on drift.
    """
    agents = _load_agents(canonical_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    drift: list[str] = []
    for agent in agents:
        content = render_claude_code(agent)
        out = output_dir / f"{agent['name']}.md"
        if check:
            if not out.exists():
                drift.append(f"{out.name} (missing)")
            elif out.read_text(encoding="utf-8") != content:
                drift.append(f"{out.name} (stale)")
        else:
            out.write_text(content, encoding="utf-8")
            if verbose:
                print(f"  wrote {out.relative_to(output_dir.parent)}")
    return drift


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python scripts/gen_agents.py``."""
    parser = argparse.ArgumentParser(
        description="Generate Claude Code agent definitions from canonical YAML source.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/gen_agents.py            # generate plugin/agents/*.md\n"
            "  python scripts/gen_agents.py --check    # verify no drift (CI)"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify generated files match committed output; exit 1 on drift.",
    )
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=CANONICAL_DIR,
        help=f"Canonical YAML source directory (default: {CANONICAL_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Output directory for generated .md files (default: {OUTPUT_DIR})",
    )
    args = parser.parse_args(argv)

    try:
        drift = generate(
            canonical_dir=args.canonical_dir,
            output_dir=args.output_dir,
            check=args.check,
            verbose=not args.check,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if drift:
            print(
                "DRIFT — run `python scripts/gen_agents.py` to regenerate:",
                file=sys.stderr,
            )
            for item in drift:
                print(f"  {item}", file=sys.stderr)
            return 1
        n = len(list(args.canonical_dir.glob("*.yaml")))
        print(f"OK — {n} agent files are up to date.")
    else:
        n = len(list(args.output_dir.glob("*.md")))
        print(
            f"Generated {n} agent definition files → "
            f"{args.output_dir.relative_to(REPO_ROOT)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
