# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Governance: internal identifiers are confined to ``starboard-internal``.

The gate is the governance boundary (UNIFIED_PLAN §3.5/§7): internal namespaces,
backend ids, hosts, and ``go/`` shortlinks may appear ONLY inside this
internal-index-only package — never in the public wheels. This test asserts the
**public** package trees (and the public port adapters) contain none of them,
and — as a positive control — that the internal package does name them (proving
the scan is meaningful and the identifiers are confined here).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

#: §0(10) governance red-line identifiers, as regexes (matched case-insensitively).
#: ``go/`` requires a following word char so it matches real shortlinks
#: (``go/global_genie``) but not the prose "no internal go/ links".
_FORBIDDEN = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"centralized_system_tables",
        r"fin_live_gold",
        r"gtm_",
        r"eng_",
        r"logfood",
        r"clickhouse",
        r"hmr_stack_hash",
        r"logs-summariser",
        r"dbr-doctor",
        r"go/\w",
    )
)

# packages/starboard-internal/tests/<this file>
# parents: [0]=tests [1]=starboard-internal [2]=packages
_PACKAGES = Path(__file__).resolve().parents[2]


def _public_source_roots() -> list[Path]:
    roots = [
        _PACKAGES / "starboard" / "starboard",
        _PACKAGES / "starboard-core" / "starboard_core",
        _PACKAGES / "starboard-core" / "starboard_x",
        _PACKAGES / "starboard-skills" / "starboard_skills",
    ]
    return [r for r in roots if r.exists()]


def _hits_in_tree(root: Path) -> list[str]:
    offenders: list[str] = []
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for pattern in _FORBIDDEN:
            if pattern.search(text):
                offenders.append(f"{py}: {pattern.pattern}")
    return offenders


@pytest.mark.unit
class TestPublicTreesHaveNoInternalIdentifiers:
    def test_public_packages_are_clean(self) -> None:
        roots = _public_source_roots()
        assert roots, "expected to locate the public package source trees"
        offenders: list[str] = []
        for root in roots:
            offenders.extend(_hits_in_tree(root))
        assert offenders == [], f"public code names internal identifiers: {offenders}"

    def test_public_port_adapters_are_clean(self) -> None:
        adapters = _PACKAGES / "starboard" / "starboard" / "adapters" / "ports"
        assert adapters.exists()
        assert _hits_in_tree(adapters) == []


@pytest.mark.unit
class TestInternalIdentifiersAreConfinedHere:
    def test_internal_package_does_name_them(self) -> None:
        internal_root = _PACKAGES / "starboard-internal" / "starboard_internal"
        blob = "\n".join(
            p.read_text(encoding="utf-8").lower()
            for p in internal_root.rglob("*.py")
        )
        # Positive control: the confined identifiers really do live here.
        assert "centralized_system_tables" in blob
        assert "hmr_stack_hash" in blob
        assert "go/" in blob
