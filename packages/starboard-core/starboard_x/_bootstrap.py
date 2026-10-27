"""Optional runtime dep bootstrap for the lightweight wrappers.

On a missing optional dependency, pip-install the right extra FROM THE PUBLIC
MIRROR and retry — unless disabled. Stdlib-only (kernel purity): no heavy import
at module load; pip runs only on a caught ImportError at call time.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from typing import Any


def _disabled() -> bool:
    return os.environ.get("STARBOARD_NO_AUTO_INSTALL", "").strip().lower() in {"1", "true", "yes"}


def ensure(module: str, *, spec: str, label: str) -> Any:
    """Import `module`; if missing, pip-install `spec` (a pip requirement string,
    typically '<pkg>[extra] @ <mirror>#subdirectory=packages/<dir>') and retry.

    Raises RuntimeError with the exact install command if auto-install is
    disabled or the install/import still fails.
    """
    try:
        return importlib.import_module(module)
    except ImportError:
        cmd = [sys.executable, "-m", "pip", "install", spec]
        if _disabled():
            raise RuntimeError(
                f"{label} requires a dependency that is not installed. "
                f"Install it with: pip install '{spec}'  "
                f"(auto-install is disabled by STARBOARD_NO_AUTO_INSTALL)."
            ) from None
        print(f"[starboard] {label}: installing missing dependency — {' '.join(cmd)}", file=sys.stderr)
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"{label}: auto-install failed ({exc}). Install manually: pip install '{spec}'."
            ) from exc
        try:
            return importlib.import_module(module)
        except ImportError as exc:
            raise RuntimeError(
                f"{label}: install appeared to succeed but the module is still missing. "
                f"Install manually: pip install '{spec}'."
            ) from exc
