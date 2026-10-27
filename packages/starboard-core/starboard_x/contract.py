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
    2  not-found — the requested resource does not exist; also a refusal
       (``LOCAL_STORAGE_REFUSED`` / ``LOCAL_FILE_INTAKE_REFUSED`` /
       ``STORAGE_UNAVAILABLE`` ...)
    3  api-error — Databricks API / unexpected runtime error
    4  arg-error — bad CLI arguments
    7  storage — a storage / integrity / access failure on an engagement run
       (``BLOCKED_ACCESS`` / ``STORAGE_INTEGRITY`` / ``NOT_FOUND`` / ``STORAGE_ERROR``:
       the message starts with the code)
    8  storage-transient — Drive failed transiently (``STORAGE_TRANSIENT``; retryable,
       nothing refused: run the same command again)
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum
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
    #: Machine code of the failure (``errors[0].code``); ``None`` = none beyond the exit code.
    code: str | None = None
    #: True when the same command can simply be run again.
    retryable: bool = False

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


# --- Serialization -------------------------------------------------------- #
def to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses/enums/tuples into JSON-able primitives.

    Stdlib-only (dataclass + enum aware) so every ``python -m starboard_x.*``
    sub-module can serialize the pure analyzers' frozen-dataclass results into
    the stable envelope without a pydantic/orjson dependency. ``datetime`` /
    ``date`` fall through to ``isoformat`` for a deterministic string.
    """
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, date):  # covers datetime (subclass of date)
        return obj.isoformat()
    return obj


# --- Identity scrub (D3-24) ----------------------------------------------- #
# The same rules as the helper scrub (``starboard_skills.helpers.contract``), which
# this stdlib-only tier cannot import: identity keys are dropped and every
# email-shaped value (``@`` or ``%40``, NFKC-folded) becomes ``<email>``.
_IDENTITY_KEY = re.compile(r"(^|_)user_name$|email|(^|_)user_id$")
_EMAIL_PART = r"[^@%\s'\"`(),;:<>\[\]{}/=]+"
_EMAIL_CHAR = _EMAIL_PART[:-1]
_EMAIL = re.compile(
    rf"(?<!{_EMAIL_CHAR}){_EMAIL_PART}(?:@|%40){_EMAIL_PART}\.{_EMAIL_PART}",
    re.IGNORECASE,
)
EMAIL_PLACEHOLDER = "<email>"


def redact_emails(text: str) -> str:
    """``text`` with every email-shaped substring replaced by ``<email>``."""
    if not text:
        return text
    out = _EMAIL.sub(EMAIL_PLACEHOLDER, text)
    folded = unicodedata.normalize("NFKC", out)
    if folded != out and _EMAIL.search(folded):
        return _EMAIL.sub(EMAIL_PLACEHOLDER, folded)
    return out


def scrub_identity(obj: Any) -> Any:
    """A copy of ``obj`` without identity keys and with every string email-redacted."""
    if isinstance(obj, str):
        return redact_emails(obj)
    if isinstance(obj, Mapping):
        return {
            k: scrub_identity(v)
            for k, v in obj.items()
            if not (isinstance(k, str) and _IDENTITY_KEY.search(k))
        }
    if isinstance(obj, list | tuple):
        return [scrub_identity(v) for v in obj]
    return obj


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
    code: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    """Build the stable stdout envelope.

    A failure with a machine ``code`` (and whether the same command can be retried)
    also carries ``errors: [{code, message, retryable}]``; ``error`` stays the message.
    """
    out: dict[str, Any] = {
        "ok": ok,
        "domain": domain,
        "command": command,
        "data": data,
        "error": error,
        "meta": meta if meta is not None else build_meta(),
    }
    if code:
        out["errors"] = [{"code": code, "message": error, "retryable": retryable}]
    return out
