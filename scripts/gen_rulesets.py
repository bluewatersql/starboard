# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Generate per-domain rulesets from the canonical Starboard skills tree.

Usage::

    python scripts/gen_rulesets.py           # generate all rulesets + router
    python scripts/gen_rulesets.py --check   # exit 1 if any file is stale

Output
------
``plugin/rules/{domain}.md`` for each domain in DOMAIN_MAP, plus
``plugin/rules/starboard.md`` rewritten as the index / router.

The canonical source for each domain is the corresponding
``packages/starboard-skills/skills/starboard/<skill_dir>/SKILL.md``.
Content extracted: description, MCP tool reference, CLI commands (all tiers),
analytical-reasoning heuristics, and success criteria.

Content-model schema
--------------------
See ``plugin/rules/README.md`` for the full specification.
Every generated file carries YAML frontmatter with these required fields::

    schema:    starboard-ruleset/1   (version sentinel)
    domain:    jobs|sql|warehouse|uc|cluster|discovery
    title:     human-readable title string
    skill:     source skill directory name (e.g. starboard-job)
    mcp_agent: MCP tool identifier (e.g. mcp__starboard__job_agent)
    triggers:  YAML list of keyword strings
    generated: true
    source:    repo-relative path to source SKILL.md
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml  # type: ignore[import]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Repo-root resolution
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Walk up from this script until the canonical skills package is found."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise AssertionError("Cannot locate repo root (expected packages/starboard-skills/skills/)")


REPO_ROOT = _repo_root()
CANONICAL_SKILLS_ROOT = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"
RULES_DIR = REPO_ROOT / "plugin" / "rules"

# ---------------------------------------------------------------------------
# Domain map: slug → skill directory + MCP tool + trigger keywords
# The skill_dir is the subdirectory name under CANONICAL_SKILLS_ROOT.
# The mcp_tool is used to build the mcp__starboard__{mcp_tool} reference.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DomainSpec:
    skill_dir: str
    mcp_tool: str
    triggers: tuple[str, ...]


DOMAIN_MAP: dict[str, DomainSpec] = {
    "jobs": DomainSpec(
        skill_dir="starboard-job",
        mcp_tool="job_agent",
        triggers=("job", "job_run", "failure", "workflow", "schedule"),
    ),
    "sql": DomainSpec(
        skill_dir="starboard-query",
        mcp_tool="query_agent",
        triggers=("query", "sql", "slow query", "query failure", "query performance"),
    ),
    "warehouse": DomainSpec(
        skill_dir="starboard-warehouse",
        mcp_tool="warehouse_agent",
        triggers=("warehouse", "sql warehouse", "autostop", "cluster_size", "serverless"),
    ),
    "uc": DomainSpec(
        skill_dir="starboard-uc",
        mcp_tool="uc_agent",
        triggers=("unity catalog", "catalog", "schema", "lineage", "governance", "table"),
    ),
    "cluster": DomainSpec(
        skill_dir="starboard-cluster",
        mcp_tool="cluster_agent",
        triggers=("cluster", "autoscale", "node", "compute", "oom", "node lost"),
    ),
    "discovery": DomainSpec(
        skill_dir="starboard-discovery",
        mcp_tool="run_discovery_queries",
        triggers=("discovery", "inventory", "workspace", "explore", "audit"),
    ),
}

# ---------------------------------------------------------------------------
# SKILL.md parsing helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)", re.DOTALL)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_yaml, body).  Raises ValueError on parse failure."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("SKILL.md does not start with fenced YAML frontmatter")
    return m.group(1), m.group(2)


def _extract_section(body: str, heading_pattern: str) -> str:
    """Return the text under the first heading matching *heading_pattern*.

    Extraction stops at the next heading at the same or higher level.
    Returns an empty string if the heading is not found.
    """
    lines = body.split("\n")
    section_lines: list[str] = []
    in_section = False
    section_level = 0

    for line in lines:
        m = re.match(r"^(#+)\s+", line)
        if m:
            level = len(m.group(1))
            if re.search(heading_pattern, line, re.IGNORECASE):
                in_section = True
                section_level = level
                continue
            elif in_section and level <= section_level:
                break
        if in_section:
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def _extract_code_blocks(text: str, lang: str = "bash") -> list[str]:
    """Return a list of raw code-block contents (lang-fenced or plain fenced)."""
    # Match ```bash...``` or plain ```...``` blocks
    pattern = rf"```(?:{lang})?\n(.*?)```"
    return [m.strip() for m in re.findall(pattern, text, re.DOTALL) if m.strip()]


def _extract_bullets(text: str) -> list[str]:
    """Return lines that are bullet points (- or * prefixed)."""
    return [
        line.strip()
        for line in text.split("\n")
        if re.match(r"^\s*[-*]\s+", line)
    ]


def _extract_numbered(text: str) -> list[str]:
    """Return lines that are numbered list items."""
    return [
        line.strip()
        for line in text.split("\n")
        if re.match(r"^\s*\d+\.\s+", line)
    ]


# ---------------------------------------------------------------------------
# Per-domain content extraction
# ---------------------------------------------------------------------------

@dataclass
class SkillContent:
    """Content extracted from a SKILL.md, used to populate the ruleset template."""

    description: str
    mcp_refs: list[str]
    tier1_commands: list[str]       # bash code-block lines
    tier0_commands: list[str]       # bash code-block lines
    heuristics: list[str]           # bullet strings
    success_criteria: list[str]     # numbered-item strings
    has_tier1: bool


def extract_skill_content(skill_md: Path) -> SkillContent:
    """Parse *skill_md* and return extracted content for ruleset generation."""
    text = skill_md.read_text(encoding="utf-8")
    fm_text, body = _split_frontmatter(text)
    if yaml is not None:
        fm: dict[str, object] = yaml.safe_load(fm_text) or {}
    else:
        # Minimal fallback: extract description with regex
        desc_m = re.search(r'^description:\s*"?(.+?)"?\s*$', fm_text, re.MULTILINE)
        fm = {"description": desc_m.group(1) if desc_m else ""}

    description: str = str(fm.get("description", ""))

    # MCP references
    mcp_refs = list(dict.fromkeys(re.findall(r"mcp__starboard__\w+", body)))

    # Tier-1 section detection
    tier1_section = _extract_section(body, r"Tier\s*1")
    has_tier1 = bool(tier1_section)
    tier1_commands: list[str] = []
    if has_tier1:
        blocks = _extract_code_blocks(tier1_section)
        for block in blocks:
            tier1_commands.extend(block.splitlines())

    # Tier-0 / Non-MCP commands
    tier0_section = _extract_section(body, r"Tier\s*0|Non-MCP Path")
    tier0_commands: list[str] = []
    if tier0_section:
        blocks = _extract_code_blocks(tier0_section)
        for block in blocks:
            tier0_commands.extend(block.splitlines())

    # Heuristics: "Apply analytical reasoning" or "Build workspace inventory"
    heuristics_section = _extract_section(
        body, r"Apply analytical reasoning|Build workspace inventory"
    )
    heuristics = _extract_bullets(heuristics_section) if heuristics_section else []

    # Success criteria: "Produce recommendations" or "Produce discovery report"
    criteria_section = _extract_section(
        body, r"Produce recommendations|Produce discovery report"
    )
    success_criteria = (
        _extract_numbered(criteria_section) if criteria_section else []
    )

    return SkillContent(
        description=description,
        mcp_refs=mcp_refs,
        tier1_commands=tier1_commands,
        tier0_commands=tier0_commands,
        heuristics=heuristics,
        success_criteria=success_criteria,
        has_tier1=has_tier1,
    )


# ---------------------------------------------------------------------------
# Ruleset template renderer
# ---------------------------------------------------------------------------

_GROUND_RULES = """\
- **Dollar figures are list-price DBU estimates** — always label them as such.
- **Single workspace by default** — targets the resolved workspace; do not assume fleet/cross-account scope.
- **Auth by subtraction** — rely on the resolved credential chain (`--profile` / `STARBOARD_WORKSPACE` / ambient); never hard-code hosts or tokens.
- **Read-only advisory** — Starboard analyzes and recommends; it does not modify the workspace.
- **Exit codes** — `0` ok · `1` auth error · `2` not found · `3` API error · `4` arg error.
- Present findings **highest-priority first** with their evidence (`query_id` + row)."""


def _render_tier1(domain: str, content: SkillContent) -> str:
    if not content.has_tier1:
        return "Not available for this domain — proceed to Tier-0."
    lines = [
        "If `${CLAUDE_SKILL_DIR}/scripts/run.sh` exists, use the bundled pure analyzer "
        "(no network, pre-approved — no permission prompt):",
        "",
        "```bash",
    ]
    lines.extend(content.tier1_commands)
    lines.append("```")
    return "\n".join(lines)


def _render_tier0(content: SkillContent) -> str:
    if not content.tier0_commands:
        return "See the skill body for raw fetch commands."
    lines = ["```bash"]
    lines.extend(content.tier0_commands)
    lines.append("```")
    return "\n".join(lines)


def _render_heuristics(content: SkillContent) -> str:
    if not content.heuristics:
        return "Apply domain expertise when reviewing the structured JSON output."
    return "\n".join(content.heuristics)


def _render_success_criteria(content: SkillContent) -> str:
    if not content.success_criteria:
        return "Produce a structured, prioritized analysis with actionable recommendations."
    return "\n".join(content.success_criteria)


def _discovery_mcp_note() -> str:
    return (
        "Use `mcp__starboard__run_discovery_queries` for deterministic query data only.\n"
        "**Do NOT** call `start_discovery_analysis`, `get_discovery_analysis_progress`, or\n"
        "`synthesize_discovery_report` — those invoke a second server-side LLM.\n"
        "Take the returned data and synthesize the inventory yourself."
    )


def render_ruleset(domain: str, spec: DomainSpec, content: SkillContent) -> str:
    """Render the complete ruleset markdown for *domain*."""
    title = domain.upper() if len(domain) <= 3 else domain.replace("-", " ").title()
    source_path = (
        f"packages/starboard-skills/skills/starboard/{spec.skill_dir}/SKILL.md"
    )
    triggers_yaml = "[" + ", ".join(f'"{t}"' for t in spec.triggers) + "]"
    mcp_tool_id = f"mcp__starboard__{spec.mcp_tool}"

    # Short "when to use" derived from description
    when_to_use = content.description

    # MCP section body — discovery gets a special note
    if domain == "discovery":
        mcp_body = _discovery_mcp_note()
    else:
        mcp_body = (
            f"Dispatch directly to `{mcp_tool_id}`.\n"
            "The full agent stack handles orchestration, analysis, and recommendations.\n"
            "Return the agent response directly."
        )

    tier1_body = _render_tier1(domain, content)
    tier0_body = _render_tier0(content)
    heuristics_body = _render_heuristics(content)
    criteria_body = _render_success_criteria(content)

    return f"""\
---
schema: starboard-ruleset/1
domain: {domain}
title: "Starboard: {title} Agent Rules"
skill: {spec.skill_dir}
mcp_agent: {mcp_tool_id}
triggers: {triggers_yaml}
generated: true
source: {source_path}
---

# Starboard: {title} Agent Rules

> **Scope:** {when_to_use}
>
> Dollar figures are **list-price DBU estimates** — always label them as such.

## When to use

{when_to_use}

## Tool guidance

Prefer the highest available tier. Check in order: Tier-2 → Tier-1 → Tier-0.

### Tier-2 — MCP agent (preferred)

If `mcp__starboard__*` tools are available in your context:

{mcp_body}

### Tier-1 — bundled helper

{tier1_body}

### Tier-0 — raw fetch via `starboard-helper`

{tier0_body}

## Domain heuristics

{heuristics_body}

## Success criteria

A complete analysis for this domain must include:

{criteria_body}

## Ground rules

{_GROUND_RULES}
"""


# ---------------------------------------------------------------------------
# Router / index renderer
# ---------------------------------------------------------------------------

def render_router(domains: list[str]) -> str:
    """Render the updated starboard.md index that routes to per-domain files."""
    domain_list = "\n".join(
        f"- [`{d}.md`]({d}.md) — {DOMAIN_MAP[d].skill_dir} rules" for d in domains
    )
    return f"""\
# Starboard Rules — Index

Baseline guidance injected into agent sessions where Starboard is available.
Copy this directory into `.isaac/rules/` (or `{{project}}/.isaac/rules/`) to activate.

Public path only — no internal data or namespaces. Dollar figures are
**list-price DBU estimates** — always label them as such.

## Per-domain rulesets

Each domain has its own ruleset with MCP path, CLI fallback, heuristics, and
success criteria derived from the canonical skills tree:

{domain_list}

## Quick-start rules (all domains)

- Use `mcp__starboard__*` tools when available; fall back to
  `python -m starboard_x.<capability>` then `starboard-helper`.
- Prefer the **helper CLI over ad-hoc SDK calls** — each emits a compact
  JSON envelope (`{{ok, domain, command, data|error, meta}}`) and standard exit codes
  (`0` ok · `1` auth · `2` not-found · `3` api-error · `4` arg-error).
- **Auth by subtraction**: rely on the resolved Databricks credential chain
  (`--profile` / `STARBOARD_WORKSPACE` or ambient); never hard-code hosts or tokens.
- **Read-only advisory**: Starboard analyzes and recommends; it does not modify the workspace.
- Present findings **highest-priority first** with their evidence (`query_id` + row).

## Full workspace review

```bash
starboard review [--domains jobs,sql,warehouse]   # multi-domain review
starboard genie ask "<question>"                  # NL→SQL
```

## Content-model schema

See [`README.md`](README.md) for the ruleset content-model schema and
regeneration instructions.
"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_all(check: bool = False) -> bool:
    """Generate (or check) all domain rulesets and the router.

    Returns True if files are up-to-date (or were successfully written).
    Returns False (and prints diff summary) if *check* is True and files are stale.
    """
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []

    domains = sorted(DOMAIN_MAP.keys())

    for domain in domains:
        spec = DOMAIN_MAP[domain]
        skill_md = CANONICAL_SKILLS_ROOT / spec.skill_dir / "SKILL.md"
        if not skill_md.exists():
            print(f"WARNING: skill SKILL.md not found: {skill_md}", file=sys.stderr)
            continue

        content = extract_skill_content(skill_md)
        rendered = render_ruleset(domain, spec, content)
        out_path = RULES_DIR / f"{domain}.md"

        if check:
            existing = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
            if existing != rendered:
                stale.append(str(out_path.relative_to(REPO_ROOT)))
        else:
            out_path.write_text(rendered, encoding="utf-8")
            print(f"  wrote {out_path.relative_to(REPO_ROOT)}")

    # Router / index
    router = render_router(domains)
    router_path = RULES_DIR / "starboard.md"
    if check:
        existing_router = router_path.read_text(encoding="utf-8") if router_path.exists() else ""
        if existing_router != router:
            stale.append(str(router_path.relative_to(REPO_ROOT)))
    else:
        router_path.write_text(router, encoding="utf-8")
        print(f"  wrote {router_path.relative_to(REPO_ROOT)}")

    if check and stale:
        print("Stale ruleset files (run `python scripts/gen_rulesets.py` to regenerate):")
        for p in stale:
            print(f"  {p}")
        return False

    if not check:
        print(f"Generated {len(domains)} domain rulesets + router in {RULES_DIR.relative_to(REPO_ROOT)}/")

    return True


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    check = "--check" in args
    ok = generate_all(check=check)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
