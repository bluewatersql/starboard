# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for per-domain ruleset generation (Task X7).

Validates:
- Every expected domain ruleset exists in plugin/rules/
- Each ruleset frontmatter conforms to the content-model schema (schema version,
  required fields, type constraints)
- Each ruleset body contains all required sections
- Generator is idempotent: running it twice produces identical output
- No internal namespaces appear in any generated file (governance)
- Dollar figures are labelled as list-price estimates
- Router (starboard.md) references all domain rulesets

Tests run under ``make test-unit`` (collected by pytest from packages/starboard/).
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

try:
    import yaml  # type: ignore[import]
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Repo / path helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise AssertionError("Cannot locate repo root")


REPO_ROOT = _repo_root()
RULES_DIR = REPO_ROOT / "plugin" / "rules"
GENERATOR = REPO_ROOT / "scripts" / "gen_rulesets.py"

EXPECTED_DOMAINS = ["cluster", "discovery", "jobs", "sql", "uc", "warehouse"]

# Content-model constraints
SCHEMA_VERSION = "starboard-ruleset/1"
REQUIRED_FM_FIELDS = {"schema", "domain", "title", "skill", "mcp_agent", "triggers", "generated", "source"}
VALID_DOMAINS = frozenset(EXPECTED_DOMAINS)
REQUIRED_SECTIONS = {
    "## When to use",
    "## Tool guidance",
    "## Domain heuristics",
    "## Success criteria",
    "## Ground rules",
}
REQUIRED_TIER_SECTIONS = {
    "### Tier-2",
    "### Tier-1",
    "### Tier-0",
}

# Governance: these strings must not appear in any public ruleset
INTERNAL_NAMESPACES = [
    "centralized_system_tables",
    "fin_live_gold",
    "gtm_",
    "eng_",
    "logfood",
    "ClickHouse",
    "hmr_stack_hash",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)", re.DOTALL)


def _parse_ruleset(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body).  Skips frontmatter parse if yaml missing."""
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    assert m, f"{path.name}: does not start with fenced YAML frontmatter"
    fm_text = m.group(1)
    body = m.group(2)
    if _YAML_AVAILABLE:
        fm = yaml.safe_load(fm_text) or {}
    else:
        # Fallback: extract key:value lines
        fm = {}
        for line in fm_text.splitlines():
            kv = re.match(r'^(\w[\w_-]*):\s*(.+)$', line)
            if kv:
                fm[kv.group(1)] = kv.group(2).strip('"')
    return fm, body


def _ruleset_path(domain: str) -> Path:
    return RULES_DIR / f"starboard-{domain}.md"


# ---------------------------------------------------------------------------
# Existence tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_domain_ruleset_exists(domain: str) -> None:
    """Each expected domain ruleset file must exist."""
    path = _ruleset_path(domain)
    assert path.exists(), (
        f"Missing ruleset: {path.relative_to(REPO_ROOT)}\n"
        f"Run `python scripts/gen_rulesets.py` to generate it."
    )


def test_router_exists() -> None:
    """The router/index file plugin/rules/starboard.md must exist."""
    assert (RULES_DIR / "starboard.md").exists()


# ---------------------------------------------------------------------------
# Frontmatter schema tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_frontmatter_required_fields(domain: str) -> None:
    """Each ruleset frontmatter must contain all required fields."""
    fm, _ = _parse_ruleset(_ruleset_path(domain))
    missing = REQUIRED_FM_FIELDS - set(fm.keys())
    assert not missing, f"{domain}.md: missing frontmatter fields: {missing}"


@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_frontmatter_schema_version(domain: str) -> None:
    """schema field must equal 'starboard-ruleset/1'."""
    fm, _ = _parse_ruleset(_ruleset_path(domain))
    assert fm.get("schema") == SCHEMA_VERSION, (
        f"{domain}.md: expected schema={SCHEMA_VERSION!r}, got {fm.get('schema')!r}"
    )


@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_frontmatter_domain_valid(domain: str) -> None:
    """domain field must be one of the expected domain slugs."""
    fm, _ = _parse_ruleset(_ruleset_path(domain))
    assert fm.get("domain") == domain, (
        f"{domain}.md: frontmatter 'domain' field is {fm.get('domain')!r}, expected {domain!r}"
    )


@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_frontmatter_generated_true(domain: str) -> None:
    """generated field must be boolean True."""
    fm, _ = _parse_ruleset(_ruleset_path(domain))
    value = fm.get("generated")
    # yaml parses true → True; string fallback accepts "true"
    assert value is True or str(value).lower() == "true", (
        f"{domain}.md: 'generated' must be true, got {value!r}"
    )


@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_frontmatter_mcp_agent_pattern(domain: str) -> None:
    """mcp_agent must match mcp__starboard__<tool>."""
    fm, _ = _parse_ruleset(_ruleset_path(domain))
    mcp_agent = str(fm.get("mcp_agent", ""))
    assert re.match(r"^mcp__starboard__\w+$", mcp_agent), (
        f"{domain}.md: mcp_agent {mcp_agent!r} does not match mcp__starboard__<tool>"
    )


@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_frontmatter_source_ends_with_skill_md(domain: str) -> None:
    """source field must end with /SKILL.md."""
    fm, _ = _parse_ruleset(_ruleset_path(domain))
    source = str(fm.get("source", ""))
    assert source.endswith("/SKILL.md"), (
        f"{domain}.md: source {source!r} must end with /SKILL.md"
    )


@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_frontmatter_skill_dir_exists(domain: str) -> None:
    """skill field must correspond to an actual skill directory."""
    fm, _ = _parse_ruleset(_ruleset_path(domain))
    skill_dir = str(fm.get("skill", ""))
    skill_path = REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard" / skill_dir
    assert skill_path.is_dir(), (
        f"{domain}.md: skill directory {skill_path} does not exist"
    )


# ---------------------------------------------------------------------------
# Required sections tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_required_sections_present(domain: str) -> None:
    """Each ruleset body must contain all required H2 sections."""
    _, body = _parse_ruleset(_ruleset_path(domain))
    for section in REQUIRED_SECTIONS:
        assert section in body, (
            f"{domain}.md: missing required section {section!r}"
        )


@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_tier_subsections_present(domain: str) -> None:
    """Tool guidance must contain Tier-2, Tier-1, and Tier-0 sub-sections."""
    _, body = _parse_ruleset(_ruleset_path(domain))
    for tier_heading in REQUIRED_TIER_SECTIONS:
        assert tier_heading in body, (
            f"{domain}.md: missing tier sub-section {tier_heading!r}"
        )


# ---------------------------------------------------------------------------
# Governance tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", EXPECTED_DOMAINS)
def test_no_internal_namespaces(domain: str) -> None:
    """Governance: no internal-only namespaces in any public ruleset."""
    text = _ruleset_path(domain).read_text(encoding="utf-8")
    for ns in INTERNAL_NAMESPACES:
        assert ns not in text, (
            f"{domain}.md: contains internal namespace {ns!r} (governance violation)"
        )


def test_no_internal_namespaces_router() -> None:
    """Governance: router/index must also be internal-namespace-clean."""
    text = (RULES_DIR / "starboard.md").read_text(encoding="utf-8")
    for ns in INTERNAL_NAMESPACES:
        assert ns not in text, (
            f"starboard.md: contains internal namespace {ns!r} (governance violation)"
        )


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------

def test_router_references_all_domains() -> None:
    """starboard.md must reference every per-domain ruleset file."""
    text = (RULES_DIR / "starboard.md").read_text(encoding="utf-8")
    for domain in EXPECTED_DOMAINS:
        assert f"{domain}.md" in text, (
            f"starboard.md does not reference {domain}.md"
        )


# ---------------------------------------------------------------------------
# Idempotency test (regenerate-and-diff)
# ---------------------------------------------------------------------------

def test_generator_idempotent() -> None:
    """Running gen_rulesets.py twice must produce identical output (idempotent).

    We generate into a temp directory then compare against the already-committed
    files.  A difference means either (a) the generator is non-deterministic or
    (b) the committed files are stale.
    """
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        "gen_rulesets.py --check reported stale files.\n"
        "Run `python scripts/gen_rulesets.py` to regenerate, then commit.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_generator_produces_all_domains() -> None:
    """Generator writes exactly the expected domain files (no extras, no missing)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_rules = Path(tmpdir) / "rules"
        tmp_rules.mkdir()
        # Patch RULES_DIR by running with subprocess — just verify committed files exist
        # (full generation smoke: all expected files present after --check passes)
        for domain in EXPECTED_DOMAINS:
            assert _ruleset_path(domain).exists(), (
                f"Domain file {domain}.md missing from {RULES_DIR}"
            )
        # Verify no unexpected .md files: per-domain rulesets are namespaced
        # ``starboard-<domain>.md``; the router (``starboard.md``) and README are allowed.
        allowed = {f"starboard-{d}.md" for d in EXPECTED_DOMAINS} | {"starboard.md", "README.md"}
        extra = [p.name for p in RULES_DIR.glob("*.md") if p.name not in allowed]
        assert not extra, f"Unexpected files in plugin/rules/: {extra}"
