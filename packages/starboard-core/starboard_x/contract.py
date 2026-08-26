# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Stable JSON envelope + exit-code contract for the ``starboard-x`` CLIs.

Mirrors the Phase-0 ``starboard-helper`` contract
(``starboard_skills.helpers.contract``) so every ``python -m starboard_x.*``
sub-module emits the same envelope on stdout and uses the same process exit
codes. This module is **stdlib-only** on purpose — it must be importable in the
``diagnostics-core`` tier with no pydantic / pyyaml / databricks-sdk.

Envelope shape (always emitted to stdout, success or failure)::

    {
      "ok": bool,
      "domain": str | None,
      "command": str | None,
      "data": <result> | None,
      "error": str | None,
      "meta": {"format": "json", "contract_version": "1.0"}
    }

Exit codes::

    0  ok
    1  auth   — could not authenticate / build a client
    2  not-found — the requested resource does not exist
    3  api-error — Databricks API / unexpected runtime error
    4  arg-error — bad CLI arguments
"""

from __future__ import annotations

from typing import Any

CONTRACT_VERSION = "1.0"

# --- Exit codes ----------------------------------------------------------- #
EXIT_OK = 0
EXIT_AUTH = 1
EXIT_NOT_FOUND = 2
EXIT_API = 3
EXIT_ARG = 4


# --- Typed errors --------------------------------------------------------- #
class HelperError(Exception):
    """Base class for CLI errors carrying a process exit code."""

    exit_code: int = EXIT_API

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthError(HelperError):
    """Authentication / client-construction failure."""

    exit_code = EXIT_AUTH


class NotFoundError(HelperError):
    """Requested resource does not exist."""

    exit_code = EXIT_NOT_FOUND


class ApiError(HelperError):
    """API or other unexpected runtime failure."""

    exit_code = EXIT_API


class ArgError(HelperError):
    """Bad CLI arguments."""

    exit_code = EXIT_ARG


# --- Envelope ------------------------------------------------------------- #
def build_meta(output_format: str = "json") -> dict[str, Any]:
    """Return the standard ``meta`` block for an envelope."""
    return {"format": output_format, "contract_version": CONTRACT_VERSION}


def envelope(
    *,
    ok: bool,
    domain: str | None,
    command: str | None,
    data: Any = None,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable stdout envelope."""
    return {
        "ok": ok,
        "domain": domain,
        "command": command,
        "data": data,
        "error": error,
        "meta": meta if meta is not None else build_meta(),
    }
