# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Kernel boundary tests (Phase-1 B1).

Prove that the pure ``starboard-core`` kernel surface imports **without**
``databricks-sdk`` present, that the DBFS loader fails with an actionable
error when the optional extra is missing, that ``databricks-sdk`` is no longer
a hard dependency, and that the import-linter contract holds.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[2]
_REPO_ROOT = Path(__file__).parents[4]

# A tiny prelude that installs a meta-path finder blocking any ``databricks``
# import, simulating an environment where ``databricks-sdk`` is not installed.
_BLOCK_DATABRICKS = """
import sys
import importlib.abc


class _Blocker(importlib.abc.MetaPathFinder):
    def __init__(self, prefix):
        self._prefix = prefix

    def find_spec(self, name, path, target=None):
        if name == self._prefix or name.startswith(self._prefix + "."):
            raise ImportError(f"simulated-absent: {name}")
        return None


sys.meta_path.insert(0, _Blocker("databricks"))
"""


def _run_isolated(body: str) -> subprocess.CompletedProcess[str]:
    """Run ``body`` in a clean subprocess with ``databricks`` import blocked."""
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_DATABRICKS + body],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


@pytest.mark.unit
class TestKernelImportsWithoutSDK:
    """The pure kernel surface must import with ``databricks-sdk`` absent."""

    def test_domain_surface_imports_without_databricks_sdk(self) -> None:
        body = """
import importlib
import sys

for mod in (
    "starboard_core.domain.models",
    "starboard_core.domain.analyzers.uc_analyzer",
    "starboard_core.domain.analyzers.warehouse_analyzer",
    "starboard_core.domain.transformers.job_transformers",
    "starboard_core.domain.transformers.uc_transformers",
):
    importlib.import_module(mod)

leaked = sorted(m for m in sys.modules if m == "databricks" or m.startswith("databricks."))
assert not leaked, f"databricks imported: {leaked}"
print("OK")
"""
        result = _run_isolated(body)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout

    def test_log_parser_imports_without_databricks_sdk(self) -> None:
        # This is the deep-chain guarantee: importing the public log_parser
        # surface (which reaches the factory that selects the dbfs loader) must
        # NOT transitively import databricks.sdk at module load.
        body = """
import importlib
import sys

lp = importlib.import_module("starboard_core.log_parser")
# Public API stays intact.
assert hasattr(lp, "create_spark_application")
assert hasattr(lp, "DBFSClient")

leaked = sorted(m for m in sys.modules if m == "databricks" or m.startswith("databricks."))
assert not leaked, f"databricks imported: {leaked}"
print("OK")
"""
        result = _run_isolated(body)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout


@pytest.mark.unit
class TestDBFSLoaderActionableError:
    """The DBFS loader must fail with an actionable error without the extra."""

    def test_dbfs_client_raises_actionable_error_when_sdk_missing(self) -> None:
        body = """
from starboard_core.log_parser.loaders.dbfs import DBFSFileLinesDataLoader

loader = DBFSFileLinesDataLoader()
try:
    _ = loader.client
except RuntimeError as exc:
    msg = str(exc)
    assert "databricks-sdk" in msg, msg
    assert "pip install" in msg, msg
    assert "starboard-kernel[databricks]" in msg, msg
    print("OK")
else:
    raise AssertionError("expected RuntimeError when databricks-sdk is absent")
"""
        result = _run_isolated(body)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout


@pytest.mark.unit
class TestPackagingBoundary:
    """``databricks-sdk`` must be an optional extra, not a hard dependency."""

    def _pyproject(self) -> dict:
        with (_CORE_DIR / "pyproject.toml").open("rb") as fh:
            return tomllib.load(fh)

    def test_databricks_sdk_absent_from_hard_dependencies(self) -> None:
        deps = self._pyproject()["project"]["dependencies"]
        offenders = [d for d in deps if "databricks-sdk" in d]
        assert not offenders, f"databricks-sdk must not be a hard dep: {offenders}"

    def test_databricks_sdk_present_in_databricks_extra(self) -> None:
        extras = self._pyproject()["project"]["optional-dependencies"]
        assert "databricks" in extras, f"missing 'databricks' extra: {list(extras)}"
        joined = " ".join(extras["databricks"])
        assert "databricks-sdk" in joined, extras["databricks"]


@pytest.mark.unit
class TestImportLinterContract:
    """The import-linter kernel-boundary contract must pass."""

    def test_lint_imports_passes(self) -> None:
        if shutil.which("lint-imports") is None:
            try:
                import importlinter  # noqa: F401
            except ImportError:
                pytest.skip("import-linter not installed in this environment")
            cmd = [sys.executable, "-m", "importlinter", "lint"]
        else:
            cmd = ["lint-imports"]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"lint-imports failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
