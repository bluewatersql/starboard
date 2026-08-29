# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for the hero/persona example validator (Task E2, D-3.3).

Validates:
- ``validate_examples.py --check`` passes on every shipped example.
- A deliberately-broken example (missing surface) FAILS the job.
- The PUBLIC pages (hero workflows, validated-examples registry) pass the
  governance grep — no internal namespaces.
- The internal-persona page lives under a clearly-scoped INTERNAL section and is
  NOT part of the public governance set.
- Every shipped example resolves to a real catalogued surface (public via the
  live catalog collectors; gated via ``starboard.ports.registry.Port``).
- The mocked runner produces a non-empty structured report and never touches a
  live workspace; freshness (>N days) is enforced under ``--check``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import pytest

# packages/starboard/tests/unit/examples/test_validate_examples.py → repo root [5]
_REPO_ROOT = Path(__file__).resolve().parents[5]
_VALIDATOR = _REPO_ROOT / "scripts" / "validate_examples.py"
_EXAMPLES_DIR = _REPO_ROOT / "docs" / "examples"
_HERO = _EXAMPLES_DIR / "HERO_WORKFLOWS.md"
_PERSONAS = _EXAMPLES_DIR / "PERSONAS.md"
_REGISTRY = _EXAMPLES_DIR / "VALIDATED_EXAMPLES.md"
_MKDOCS = _REPO_ROOT / "mkdocs.yml"

_INTERNAL_NAMESPACES = [
    "centralized_system_tables",
    "fin_live_gold",
    "gtm_",
    "eng_",
    "logfood",
    "ClickHouse",
    "hmr_stack_hash",
]


def _load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_examples", _VALIDATOR)
    assert spec is not None and spec.loader is not None, (
        f"Could not load validate_examples.py from {_VALIDATOR}"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


ve = _load_validator()


# ---------------------------------------------------------------------------
# End-to-end: the shipped examples pass --check
# ---------------------------------------------------------------------------


def test_validator_check_passes() -> None:
    """`validate_examples.py --check` must pass on every shipped example."""
    result = subprocess.run(
        [sys.executable, str(_VALIDATOR), "--check"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        "validate_examples.py --check failed.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_registry_is_non_empty() -> None:
    examples = ve.load_registry()
    assert len(examples) >= 5, "expected at least 5 (3-5 public + personas) examples"
    public = [e for e in examples if e.audience == "public"]
    internal = [e for e in examples if e.audience == "internal"]
    assert 3 <= len(public) <= 5, "3-5 public hero flows required"
    assert 1 <= len(internal) <= 2, "1-2 internal personas required"


# ---------------------------------------------------------------------------
# No dead references — a missing surface fails the job
# ---------------------------------------------------------------------------


def test_every_shipped_surface_resolves() -> None:
    pub = ve.public_surfaces()
    gated = ve.gated_ports()
    for ex in ve.load_registry():
        for surface in ex.surfaces:
            assert ve.resolve_surface(surface, pub, gated), (
                f"[{ex.id}] surface {surface.kind}:{surface.name} does not resolve"
            )


def test_broken_example_missing_surface_fails() -> None:
    """A reference to a non-existent surface must be reported as a failure."""
    examples = ve.load_registry()
    broken = examples[0]
    broken.surfaces = broken.surfaces + (
        ve.Surface(kind="mcp-tools", name="this_tool_does_not_exist"),
    )
    failures = ve.validate([broken], today=date(2026, 8, 29), check=True)
    assert any("non-existent surface" in f and "this_tool_does_not_exist" in f for f in failures), (
        f"missing-surface reference was not flagged: {failures}"
    )


def test_broken_gated_port_fails() -> None:
    """A persona referencing a non-existent gated port must fail too."""
    examples = ve.load_registry()
    ex = next(e for e in examples if e.audience == "internal")
    ex.surfaces = ex.surfaces + (
        ve.Surface(kind="internal-gated", name="not_a_real_port", gated=True),
    )
    failures = ve.validate([ex], today=date(2026, 8, 29), check=True)
    assert any("not_a_real_port" in f for f in failures), failures


# ---------------------------------------------------------------------------
# Mocked run — structure/non-emptiness, no live workspace
# ---------------------------------------------------------------------------


def test_run_example_produces_nonempty_structured_report() -> None:
    for ex in ve.load_registry():
        envelope = ve.run_example(ex)
        assert envelope["ok"] is True
        report = envelope["report"]
        assert report["findings"], f"[{ex.id}] produced no findings"
        assert report["recommendations"], f"[{ex.id}] produced no recommendations"
        # Every declared expect key is present and non-empty.
        assert ve.check_structure(envelope, ex.expect) == [], ex.id


def test_mock_runner_uses_no_live_workspace() -> None:
    ws = ve.MockWorkspace()
    assert getattr(ws, "is_mock", False) is True
    # A non-mock workspace must be rejected by the runner.
    ex = ve.load_registry()[0]

    class _NotAMock:
        is_mock = False

    with pytest.raises(AssertionError):
        ve.run_example(ex, workspace=_NotAMock())  # type: ignore[arg-type]


def test_public_example_cost_is_list_price() -> None:
    for ex in ve.load_registry():
        report = ve.run_example(ex)["report"]
        unit = report["cost_estimate"]["unit"]
        if ex.audience == "public":
            assert "list-price" in unit, f"[{ex.id}] public cost not labelled list-price"
        else:
            assert "list-price" not in unit, f"[{ex.id}] internal cost mislabelled"


# ---------------------------------------------------------------------------
# Freshness enforcement
# ---------------------------------------------------------------------------


def test_stale_example_fails_check() -> None:
    ex = ve.load_registry()[0]
    ex.last_verified = date(2026, 8, 29) - timedelta(days=ve.MAX_AGE_DAYS + 10)
    failures = ve.validate([ex], today=date(2026, 8, 29), check=True)
    assert any("stale" in f for f in failures), failures


def test_every_page_has_matching_validated_tag() -> None:
    for ex in ve.load_registry():
        assert ve._page_has_tag(ex), (
            f"[{ex.id}] page {ex.page} missing <!-- VALIDATED: {ex.last_verified} --> tag"
        )


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", [_HERO, _REGISTRY], ids=lambda p: p.name)
def test_public_pages_have_no_internal_namespaces(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    for ns in _INTERNAL_NAMESPACES:
        assert ns not in text, f"{page.name}: contains internal namespace {ns!r}"


def test_governance_scan_is_clean() -> None:
    assert ve.governance_scan() == []


def test_personas_page_excluded_from_public_governance() -> None:
    """The personas page is the one place gated references live; it must not be
    in the public governance set."""
    assert _PERSONAS not in ve.PUBLIC_PAGES
    assert _HERO in ve.PUBLIC_PAGES
    assert _REGISTRY in ve.PUBLIC_PAGES


def test_personas_page_is_clearly_scoped_internal() -> None:
    text = _PERSONAS.read_text(encoding="utf-8")
    assert "INTERNAL" in text, "personas page must be clearly labelled INTERNAL"
    # The gated path is referenced by public port identifier only.
    assert any(port in text for port in ("fleet_sql", "log_retrieval", "nl_query", "diagnostic_backend"))
    # Even the internal page must not leak red-lined internal namespaces.
    for ns in _INTERNAL_NAMESPACES:
        assert ns not in text, f"personas page leaks internal namespace {ns!r}"


# ---------------------------------------------------------------------------
# mkdocs nav wiring (strict build requires every page in nav)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", [_HERO, _PERSONAS, _REGISTRY], ids=lambda p: p.name)
def test_example_page_wired_into_nav(page: Path) -> None:
    nav_ref = str(page.relative_to(_REPO_ROOT / "docs"))
    mkdocs = _MKDOCS.read_text(encoding="utf-8")
    assert nav_ref in mkdocs, f"{nav_ref} is not referenced in mkdocs.yml nav"
