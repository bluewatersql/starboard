# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Layered-catalog / tier tests (Phase-3 B5).

Prove the kernel tier is independently installable — the pure ``starboard-core``
surface imports **without** the experience-tier ``starboard`` package present —
and that the root packaging declares the additive tier extras
(kernel -> capability -> experience) plus the ``starboard.mcp_tools`` per-domain
plugin contract, without breaking the existing extras / single-wheel install.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[2]
_REPO_ROOT = Path(__file__).parents[4]

# A prelude that blocks any ``starboard`` (experience-tier) import, simulating a
# kernel-only install where the experience wheel is absent. Note ``starboard``
# and ``starboard_core`` are DISTINCT top-level names (dot vs underscore), so
# blocking ``starboard`` leaves the kernel package importable.
_BLOCK_EXPERIENCE = """
import sys
import importlib.abc


class _Blocker(importlib.abc.MetaPathFinder):
    def __init__(self, prefix):
        self._prefix = prefix

    def find_spec(self, name, path, target=None):
        if name == self._prefix or name.startswith(self._prefix + "."):
            raise ImportError(f"simulated-absent: {name}")
        return None


sys.meta_path.insert(0, _Blocker("starboard"))
"""


def _run_isolated(body: str) -> subprocess.CompletedProcess[str]:
    """Run ``body`` in a clean subprocess with the ``starboard`` package blocked."""
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_EXPERIENCE + body],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


@pytest.mark.unit
class TestKernelTierInstallsStandalone:
    """The kernel tier imports without the experience-tier ``starboard`` present."""

    def test_kernel_surface_imports_without_experience_tier(self) -> None:
        body = """
import importlib
import sys

for mod in (
    "starboard_core",
    "starboard_core.domain.models",
    "starboard_core.domain.rules.registry",
):
    importlib.import_module(mod)

leaked = sorted(m for m in sys.modules if m == "starboard" or m.startswith("starboard."))
assert not leaked, f"experience tier imported: {leaked}"
print("OK")
"""
        result = _run_isolated(body)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout

    def test_capability_tier_analyzers_import_without_experience_tier(self) -> None:
        # The starboard_x middle tier (capability tier) must also stand alone.
        body = """
import importlib
import sys

for mod in (
    "starboard_x.warehouse",
    "starboard_x.uc",
    "starboard_x.review",
):
    importlib.import_module(mod)

leaked = sorted(m for m in sys.modules if m == "starboard" or m.startswith("starboard."))
assert not leaked, f"experience tier imported: {leaked}"
print("OK")
"""
        result = _run_isolated(body)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout


@pytest.mark.unit
class TestTierExtrasDeclared:
    """Root packaging names the three tiers as additive extras."""

    def _root_project(self) -> dict:
        with (_REPO_ROOT / "pyproject.toml").open("rb") as fh:
            return tomllib.load(fh)["project"]

    def test_tier_extras_present(self) -> None:
        extras = self._root_project()["optional-dependencies"]
        for tier in ("kernel", "capability", "experience"):
            assert tier in extras, f"missing tier extra {tier!r}: {list(extras)}"

    def test_tiers_compose_kernel_to_experience(self) -> None:
        extras = self._root_project()["optional-dependencies"]
        assert any("starboard-core" in d for d in extras["kernel"])
        assert any("starboard-core[" in d for d in extras["capability"])
        assert any(d == "starboard" or d.startswith("starboard[") for d in extras["experience"])

    def test_existing_extras_preserved(self) -> None:
        # Back-compat: B5 is additive — the pre-existing extras still exist.
        extras = self._root_project()["optional-dependencies"]
        for legacy in ("core", "server", "cli", "sdk", "all", "dev"):
            assert legacy in extras, f"B5 must not drop existing extra {legacy!r}"


@pytest.mark.unit
class TestPluginContractDocumented:
    """The per-domain plugin entry-point group is documented in root packaging."""

    def test_mcp_tools_group_named_in_root_pyproject(self) -> None:
        text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "starboard.mcp_tools" in text
