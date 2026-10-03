# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for :mod:`starboard_x._bootstrap`.

Covers the four contract cases from the task brief:
  (a) ensure() returns the module when the dep is already installed.
  (b) With STARBOARD_NO_AUTO_INSTALL=1 and a missing module: raises RuntimeError
      with the exact ``pip install '<spec>'`` string; subprocess.run NOT called.
  (c) When auto-install is enabled and the dep is missing: calls subprocess.run
      with the right spec, then re-imports (no actual pip-install in the test —
      both importlib.import_module and subprocess.run are mocked).
  (d) Dep-light guard: importing starboard_x._bootstrap pulls no heavy dep.

All mocking targets ``starboard_x._bootstrap.importlib.import_module`` and
``starboard_x._bootstrap.subprocess.run`` (module-level attribute references)
so that the patch is scoped to _bootstrap.py only and does not interfere with
mock.patch() infrastructure resolving its own target names.
"""
from __future__ import annotations

import subprocess
import sys
from types import ModuleType
from unittest import mock

import pytest
import starboard_x._bootstrap as _bstrap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SPEC = "some-pkg[extra] @ git+https://example.com/repo.git#subdirectory=packages/x"
_LABEL = "test dep"


def _ensure(*args, **kwargs):
    """Late-import ensure so the module is always freshly resolved."""
    from starboard_x._bootstrap import ensure  # noqa: PLC0415

    return ensure(*args, **kwargs)


# ---------------------------------------------------------------------------
# (a) Module present → returns it
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ensure_returns_module_when_present():
    """ensure() returns the real module object when it's importable."""
    import os  # noqa: PLC0415

    result = _ensure("os", spec=_SPEC, label=_LABEL)
    assert result is os


# ---------------------------------------------------------------------------
# (b) Disabled + missing → RuntimeError with pip install hint, no subprocess
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ensure_disabled_raises_with_install_hint(monkeypatch):
    """STARBOARD_NO_AUTO_INSTALL=1: raises RuntimeError; subprocess.run not called."""
    monkeypatch.setenv("STARBOARD_NO_AUTO_INSTALL", "1")

    # Patch at the _bootstrap module's own attribute references so that
    # mock.patch() infrastructure can still import 'subprocess' itself.
    with mock.patch.object(_bstrap.subprocess, "run") as mock_sub:
        with (
            mock.patch.object(
                _bstrap.importlib,
                "import_module",
                side_effect=ImportError("simulated absent"),
            ),
            pytest.raises(RuntimeError) as exc_info,
        ):
            _ensure("_nonexistent_starboard_xyz_", spec=_SPEC, label=_LABEL)
        mock_sub.assert_not_called()

    assert f"pip install '{_SPEC}'" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "YES"])
def test_ensure_disabled_truthy_values(monkeypatch, value):
    """All truthy STARBOARD_NO_AUTO_INSTALL values suppress auto-install."""
    monkeypatch.setenv("STARBOARD_NO_AUTO_INSTALL", value)

    with mock.patch.object(_bstrap.subprocess, "run") as mock_sub:
        with (
            mock.patch.object(
                _bstrap.importlib,
                "import_module",
                side_effect=ImportError("absent"),
            ),
            pytest.raises(RuntimeError),
        ):
            _ensure("_nonexistent_starboard_xyz_", spec=_SPEC, label=_LABEL)
        mock_sub.assert_not_called()


# ---------------------------------------------------------------------------
# (c) Enabled + missing → calls pip install with correct spec, then re-imports
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ensure_calls_pip_and_reimports_on_missing_dep(monkeypatch):
    """Auto-install enabled: subprocess.run called with spec; re-import succeeds."""
    monkeypatch.delenv("STARBOARD_NO_AUTO_INSTALL", raising=False)

    fake_module = ModuleType("_fake_installed_pkg")
    import_side_effects = [ImportError("not installed"), fake_module]

    with (
        mock.patch.object(_bstrap.subprocess, "run") as mock_sub,
        mock.patch.object(
            _bstrap.importlib,
            "import_module",
            side_effect=import_side_effects,
        ) as mock_import,
    ):
        result = _ensure("_fake_installed_pkg", spec=_SPEC, label=_LABEL)

    # pip install must be called with the expected argv.
    mock_sub.assert_called_once_with(
        [sys.executable, "-m", "pip", "install", _SPEC],
        check=True,
    )
    # importlib.import_module called twice: before and after pip install.
    assert mock_import.call_count == 2
    assert result is fake_module


@pytest.mark.unit
def test_ensure_raises_on_failed_pip_install(monkeypatch):
    """If pip install fails (CalledProcessError), ensure raises RuntimeError."""
    monkeypatch.delenv("STARBOARD_NO_AUTO_INSTALL", raising=False)

    with (
        mock.patch.object(
            _bstrap.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, "pip"),
        ),
        mock.patch.object(
            _bstrap.importlib,
            "import_module",
            side_effect=ImportError("not installed"),
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        _ensure("_nonexistent_starboard_xyz_", spec=_SPEC, label=_LABEL)

    assert f"pip install '{_SPEC}'" in str(exc_info.value)


@pytest.mark.unit
def test_ensure_raises_when_reimport_still_fails(monkeypatch):
    """pip exits 0 but the module is still un-importable: raise RuntimeError with
    the install hint rather than letting a raw ImportError propagate."""
    monkeypatch.delenv("STARBOARD_NO_AUTO_INSTALL", raising=False)

    with (
        mock.patch.object(_bstrap.subprocess, "run") as mock_sub,
        mock.patch.object(
            _bstrap.importlib,
            "import_module",
            side_effect=[ImportError("not installed"), ImportError("still missing")],
        ) as mock_import,
        pytest.raises(RuntimeError) as exc_info,
    ):
        _ensure("_nonexistent_starboard_xyz_", spec=_SPEC, label=_LABEL)

    # pip ran (exit 0), and import was attempted twice: before and after install.
    mock_sub.assert_called_once()
    assert mock_import.call_count == 2
    assert f"pip install '{_SPEC}'" in str(exc_info.value)


# ---------------------------------------------------------------------------
# (d) Dep-light guard: importing _bootstrap pulls no heavy deps
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bootstrap_import_pulls_no_heavy_deps():
    """Importing starboard_x._bootstrap must not load any heavy/SDK dependency."""
    body = (
        "import sys\n"
        "import starboard_x._bootstrap\n"
        "banned = sorted(\n"
        "    m for m in sys.modules\n"
        "    if m in {'databricks', 'openai', 'fastapi', 'mcp', 'pydantic'}\n"
        "    or m.startswith('databricks.')\n"
        "    or m.startswith('openai.')\n"
        ")\n"
        "assert not banned, f'heavy deps leaked: {banned}'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout
