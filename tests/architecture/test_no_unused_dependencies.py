# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Architecture test: verify removed unused dependencies are not installed.

These packages were confirmed as having zero imports in the codebase and were
removed from pyproject.toml. This test asserts they cannot be imported, which
would fail if they were accidentally re-added as transitive dependencies that
also export a top-level module.
"""

import importlib
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _assert_not_importable(module_name: str) -> None:
    """Assert that a module cannot be imported (i.e., is not installed)."""
    try:
        importlib.import_module(module_name)
        pytest.fail(
            f"Package '{module_name}' was importable but should not be installed. "
            "It may have been re-added as a dependency."
        )
    except ModuleNotFoundError:
        pass  # Expected - package is not installed


def _assert_not_first_party_dependency(dist_name: str, module_name: str) -> None:
    """Assert a package is neither a declared (direct) dependency nor imported.

    Unlike :func:`_assert_not_importable`, this tolerates the package being
    *installed* as a transitive of some other dependency. It only fails if the
    package is (a) declared directly in any package's ``pyproject.toml`` or
    (b) imported by first-party source. Use this for packages the project must
    never adopt directly but which may legitimately arrive transitively through
    an opt-in extra.
    """
    # (a) not declared as a direct dependency in any pyproject.toml
    declared_in: list[str] = []
    for pyproject in _REPO_ROOT.glob("packages/*/pyproject.toml"):
        text = pyproject.read_text(encoding="utf-8")
        # Match a requirement line for the dist (quoted, PEP 508), ignoring the
        # [tool.*] config tables further down the file.
        if re.search(rf'"{re.escape(dist_name)}(\[[^\]]*\])?[<>=!~ ]', text):
            declared_in.append(str(pyproject.relative_to(_REPO_ROOT)))
    assert not declared_in, (
        f"'{dist_name}' is declared as a direct dependency in: {declared_in}. "
        "It must not be adopted directly (transitive-only is acceptable)."
    )

    # (b) not imported anywhere in first-party source (tests excluded)
    import_re = re.compile(rf"^\s*(import {module_name}|from {module_name}[. ])", re.M)
    offenders: list[str] = []
    for py in _REPO_ROOT.glob("packages/*/starboard*/**/*.py"):
        if "test" in py.parts or py.name.startswith("test_"):
            continue
        if import_re.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(_REPO_ROOT)))
    assert not offenders, (
        f"'{module_name}' is imported by first-party source: {offenders}. "
        "It must not be used directly."
    )


@pytest.mark.unit
def test_chromadb_not_installed() -> None:
    """chromadb was removed from starboard dependencies (zero imports)."""
    _assert_not_importable("chromadb")


@pytest.mark.unit
def test_slack_sdk_not_installed() -> None:
    """slack-sdk was removed from starboard dependencies (zero imports)."""
    _assert_not_importable("slack_sdk")


@pytest.mark.unit
def test_tabulate_not_installed() -> None:
    """tabulate was removed from starboard dependencies (zero imports)."""
    _assert_not_importable("tabulate")


@pytest.mark.unit
def test_rapidfuzz_not_installed() -> None:
    """rapidfuzz was removed from starboard dependencies (zero imports)."""
    _assert_not_importable("rapidfuzz")


@pytest.mark.unit
def test_sqlparse_not_a_first_party_dependency() -> None:
    """sqlparse must not be a direct dependency or first-party import.

    The project parses SQL with sqlglot, not sqlparse. sqlparse legitimately
    arrives as a transitive of the opt-in ``vectorsearch`` extra
    (``databricks-vectorsearch`` -> ``mlflow-skinny`` -> ``sqlparse``), so
    asserting it is *uninstallable* is wrong once that extra is present. What we
    actually guard is that it never becomes a direct dependency or is imported by
    our own code.
    """
    _assert_not_first_party_dependency("sqlparse", "sqlparse")
