"""Stable CLI contract for ``starboard-helper``.

Centralizes the pieces every domain module and the dispatcher share:

* the JSON *envelope* wrapping all stdout output,
* the documented process *exit codes*,
* typed *exceptions* that map 1:1 to those exit codes, and
* bare-SDK *client* factories (no dependency on the heavy ``starboard`` pkg).

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
    """Base class for helper errors carrying a process exit code."""

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
    """Databricks API or other unexpected runtime failure."""

    exit_code = EXIT_API


class ArgError(HelperError):
    """Bad CLI arguments."""

    exit_code = EXIT_ARG


# --- Error translation helper -------------------------------------------- #
def raise_api_error(exc: Exception, not_found_message: str | None = None) -> None:
    """Translate a caught SDK exception into a typed :class:`HelperError`.

    If ``not_found_message`` is provided and the exception text looks like a
    "not found" error, raises :class:`NotFoundError`; otherwise
    :class:`ApiError`. Never returns.
    """
    if not_found_message and "not found" in str(exc).lower():
        raise NotFoundError(not_found_message) from exc
    raise ApiError(f"API error: {exc}") from exc


# --- Client factories (bare SDK) ----------------------------------------- #
def make_client() -> Any:
    """Return a bare :class:`databricks.sdk.WorkspaceClient`.

    Raises :class:`AuthError` (exit 1) if the client cannot be constructed.
    """
    try:
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient()
    except Exception as exc:  # pragma: no cover - exercised via mocks
        raise AuthError(f"Authentication error: {exc}") from exc


def make_account_client() -> Any:
    """Return a bare :class:`databricks.sdk.AccountClient`.

    Raises :class:`AuthError` (exit 1) if the client cannot be constructed.
    """
    try:
        from databricks.sdk import AccountClient

        return AccountClient()
    except Exception as exc:  # pragma: no cover - exercised via mocks
        raise AuthError(f"Authentication error: {exc}") from exc


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
