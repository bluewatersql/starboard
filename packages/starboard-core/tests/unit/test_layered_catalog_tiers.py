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

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[2]
_REPO_ROOT = Path(__file__).parents[4]


def _dep_dist(spec: str) -> str:
    """Extract the distribution name from a PEP 508 dependency specifier."""
    return re.split(r"[\s>=<!~;\[]", spec, maxsplit=1)[0].strip()


def _load_project(rel: str) -> dict:
    """Load the ``[project]`` table of a pyproject.toml relative to the repo root."""
    with (_REPO_ROOT / rel).open("rb") as fh:
        return tomllib.load(fh)["project"]


def _find_package_named(dist_name: str) -> dict | None:
    """Return the ``[project]`` table of the packages/* member named *dist_name*."""
    for pp in sorted((_REPO_ROOT / "packages").glob("*/pyproject.toml")):
        with pp.open("rb") as fh:
            proj = tomllib.load(fh).get("project", {})
        if proj.get("name") == dist_name:
            return proj
    return None

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
        # X3 / D-1.2: the tier extras now name the four published tier wheels —
        # kernel -> starboard-kernel, capability -> starboard-capability,
        # experience -> starboard.
        extras = self._root_project()["optional-dependencies"]
        assert any(_dep_dist(d) == "starboard-kernel" for d in extras["kernel"])
        assert any(_dep_dist(d) == "starboard-capability" for d in extras["capability"])
        assert any(
            d == "starboard" or d.startswith("starboard[") for d in extras["experience"]
        )

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


@pytest.mark.unit
class TestTierWheelDistributions:
    """X3 / D-1.2: four independently-published tier wheels.

    The distribution name of the kernel wheel is renamed ``starboard-core`` ->
    ``starboard-kernel`` (the *import* package ``starboard_core`` is unchanged),
    ``starboard-capability`` is published as the kernel + ``starboard_x`` bundle,
    and ``starboard-core`` stays installable as a thin one-release deprecation
    alias so existing ``pip install starboard-core`` keeps working.
    """

    def test_kernel_distribution_renamed_to_starboard_kernel(self) -> None:
        proj = _load_project("packages/starboard-core/pyproject.toml")
        assert proj["name"] == "starboard-kernel"

    def test_kernel_import_package_unchanged(self) -> None:
        # The wheel still ships the starboard_core (+ starboard_x) import
        # packages — only the DISTRIBUTION name changed.
        with (_CORE_DIR / "pyproject.toml").open("rb") as fh:
            data = tomllib.load(fh)
        pkgs = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        assert "starboard_core" in pkgs
        assert "starboard_x" in pkgs

    def test_kernel_self_referential_extras_use_new_name(self) -> None:
        # The intra-package extras (sparklog-aws, all, ...) must reference the
        # package by its new distribution name, or `uv sync` warns / errors.
        extras = _load_project("packages/starboard-core/pyproject.toml")[
            "optional-dependencies"
        ]
        self_refs = [
            d
            for deps in extras.values()
            for d in deps
            if _dep_dist(d) in {"starboard-core", "starboard-kernel"}
        ]
        assert self_refs, "expected intra-package self-references in kernel extras"
        assert all(_dep_dist(d) == "starboard-kernel" for d in self_refs), self_refs

    def test_starboard_core_alias_depends_on_kernel(self) -> None:
        alias = _find_package_named("starboard-core")
        assert alias is not None, "starboard-core deprecation alias package missing"
        assert any(
            _dep_dist(d) == "starboard-kernel" for d in alias.get("dependencies", [])
        ), alias.get("dependencies")

    def test_capability_distribution_bundles_kernel_and_starboard_x(self) -> None:
        cap = _find_package_named("starboard-capability")
        assert cap is not None, "starboard-capability package missing"
        assert any(
            _dep_dist(d) == "starboard-kernel" and "all" in d
            for d in cap.get("dependencies", [])
        ), cap.get("dependencies")

    def test_experience_and_skills_distribution_names_unchanged(self) -> None:
        assert _load_project("packages/starboard/pyproject.toml")["name"] == "starboard"
        assert (
            _load_project("packages/starboard-skills/pyproject.toml")["name"]
            == "starboard-skills"
        )

    def test_four_tier_wheels_are_workspace_members(self) -> None:
        # All four published tiers must be declared workspace members + sources.
        root = _REPO_ROOT / "pyproject.toml"
        with root.open("rb") as fh:
            data = tomllib.load(fh)
        sources = data["tool"]["uv"]["sources"]
        for dist in (
            "starboard-kernel",
            "starboard-capability",
            "starboard",
            "starboard-skills",
            "starboard-core",  # deprecation alias
        ):
            assert dist in sources, f"missing [tool.uv.sources] entry for {dist!r}"
            assert sources[dist] == {"workspace": True}
