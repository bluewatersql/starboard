# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared ``argparse`` + envelope plumbing for the ``starboard_x`` sub-commands.

Every ``python -m starboard_x.<domain>`` CLI funnels through the
same parse → dispatch → envelope → exit-code loop so the stable contract
(:mod:`starboard_x.contract`) is emitted identically regardless of capability.

This module is **stdlib-only**: it must be importable from the SDK-free tiers
(``warehouse`` / ``uc`` pure analyzers) without dragging in databricks-sdk,
polars, or pydantic. Capability-specific dependencies are imported lazily inside
each sub-module's verb handlers, never here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from starboard_core.engagement.overlay import detect_overlay
from starboard_core.engagement.policy import (
    LOCAL_FILE_INTAKE_GUIDANCE,
    local_file_intake_allowed,
)
from starboard_core.engagement.sink import (
    EXIT_STORAGE_FAILURE,
    MAX_READ_BYTES,
    storage_exit_code,
    storage_failure_code,
)
from starboard_core.engagement.write_guard import LocalWriteRefused

from starboard_x.contract import (
    EXIT_API,
    EXIT_OK,
    ArgError,
    AuthError,
    HelperError,
    build_meta,
    envelope,
)

#: Exit code of a storage refusal (``LOCAL_STORAGE_REFUSED`` ...): the spec's refusal code.
EXIT_REFUSED = 2

#: Refusal code of a local customer file on an overlay install (W30).
LOCAL_FILE_INTAKE_REFUSED = "LOCAL_FILE_INTAKE_REFUSED"
#: A customer file shared to Drive: ``drive:<object id>`` (W30 intake).
DRIVE_REF_PREFIX = "drive:"
#: Largest ``drive:<id>`` customer file read (held in memory only, never written locally).
#: The kernel's default read cap (64 MiB): one constant for intake and sink reads.
MAX_INTAKE_BYTES = MAX_READ_BYTES


class RefusedError(HelperError):
    """A refusal (exit 2); the message starts with its ``CODE:``."""

    exit_code = EXIT_REFUSED


class LocalFileIntakeRefused(RefusedError):
    """A local customer file on an overlay install (W30): exit 2."""

    code = LOCAL_FILE_INTAKE_REFUSED


class StorageFailureError(HelperError):
    """A storage / integrity / access failure (``BLOCKED_ACCESS`` ...): exit 7.

    ``STORAGE_TRANSIENT`` (a retryable Drive failure) exits 8 and is ``retryable``.
    """

    exit_code = EXIT_STORAGE_FAILURE

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = storage_exit_code(code)
        self.retryable = code == "STORAGE_TRANSIENT"


class BoundedData(dict[str, Any]):
    """An envelope ``data`` already bounded for a covered run.

    :func:`emit` prints an envelope carrying it as compact JSON (no ``indent``): the
    form ``stdout_budget.bound`` measures, so the 24 000-byte budget holds on the
    printed bytes. Every other envelope keeps ``indent=2``.
    """


class ArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises :class:`ArgError` instead of ``exit(2)``.

    Funnels every argparse failure (missing/invalid args, bad choices, unknown
    subcommands) through the envelope + exit-code 4 path.
    """

    def error(self, message: str):  # type: ignore[override]
        raise ArgError(message)


def local_intake_refusal(
    value: str, *, flag: str, hint: str | None = None
) -> LocalFileIntakeRefused:
    """The W30 refusal of local customer file ``value``, led by its code.

    ``hint`` replaces the default "pass ``drive:<object id>``" advice.
    """
    hint = f" Pass {flag} drive:<object id>." if hint is None else f" {hint}"
    return LocalFileIntakeRefused(
        f"{LOCAL_FILE_INTAKE_REFUSED}: {flag} {value!r} is a local file. "
        f"{LOCAL_FILE_INTAKE_GUIDANCE}{hint}"
    )


def refuse_local_intake(value: str, *, flag: str, hint: str | None = None) -> None:
    """Refuse a local customer file on an overlay install (W30): exit 2.

    The overlay seam is this module's :func:`detect_overlay` (tests pin it here). A
    public install is unaffected.
    """
    if not local_file_intake_allowed(detect_overlay()):
        raise local_intake_refusal(value, flag=flag, hint=hint)


def _read_drive_object(value: str, *, flag: str) -> bytes:
    """``drive:<object id>`` through the kernel's verified read, in memory."""
    from starboard_core.engagement.reads import ReadRefusedError, read_verified
    from starboard_core.engagement.sink import (
        StorageUnavailableError,
        load_engagement_storage,
    )
    from starboard_core.ports.engagement_storage import (
        StorageAuthError,
        StorageError,
        StorageNotFoundError,
    )

    object_id = value[len(DRIVE_REF_PREFIX) :]
    if not object_id:
        raise ArgError(f"{flag} {value!r}: expected drive:<object id>")
    try:
        return read_verified(
            load_engagement_storage(), object_id, max_bytes=MAX_INTAKE_BYTES
        )
    except ReadRefusedError as exc:
        raise ArgError(f"{flag} {DRIVE_REF_PREFIX}{exc}") from exc
    except StorageUnavailableError as exc:
        raise RefusedError(f"{exc.code}: {exc}") from exc
    except StorageNotFoundError as exc:
        raise ArgError(f"{flag}: {value} not found: {exc}") from exc
    except StorageAuthError as exc:
        raise AuthError(f"Storage authentication error: {exc}") from exc
    except StorageError as exc:
        failure = storage_failure_code(exc)
        raise StorageFailureError(f"{failure}: {exc}", code=failure) from exc


def read_intake_bytes(value: str, *, flag: str) -> bytes | None:
    """The customer-file intake gate (W30) every local-file analyzer shares.

    * ``drive:<object id>``: the object's bytes, read through the engagement storage
      (bounded by :data:`MAX_INTAKE_BYTES`; nothing is written locally).
    * A local path on an overlay install: refused (exit 2,
      ``LOCAL_FILE_INTAKE_REFUSED``).
    * A local path on a public install: ``None`` (the caller reads it as before).
    """
    if value.startswith(DRIVE_REF_PREFIX):
        return _read_drive_object(value, flag=flag)
    refuse_local_intake(value, flag=flag)
    return None


def read_text_file(
    path_str: str, *, flag: str = "--path", customer_file: bool = True
) -> str:
    """Read a text file, raising :class:`ArgError` (exit 4) when it is missing.

    ``customer_file`` routes the value through :func:`read_intake_bytes` first
    (``drive:<id>`` or a refusal on an overlay install). A caller whose input is
    already gated by its own storage policy passes ``False``.
    """
    if customer_file:
        data = read_intake_bytes(path_str, flag=flag)
        if data is not None:
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ArgError(f"{flag} {path_str} is not UTF-8 text: {exc}") from exc
    path = Path(path_str)
    if not path.is_file():
        raise ArgError(f"{flag} file not found: {path_str}")
    try:
        return path.read_text()
    except OSError as exc:
        raise ArgError(f"could not read {flag} file {path_str}: {exc}") from exc


def read_json_file(
    path_str: str, *, flag: str = "--input", customer_file: bool = True
) -> Any:
    """Read + parse a JSON file, raising :class:`ArgError` (exit 4) on failure."""
    text = read_text_file(path_str, flag=flag, customer_file=customer_file)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArgError(f"{flag} is not valid JSON ({path_str}): {exc}") from exc


def emit(payload: dict[str, Any]) -> None:
    """Write the envelope to stdout: indented JSON, compact for :class:`BoundedData`."""
    compact = isinstance(payload.get("data"), BoundedData)
    print(json.dumps(payload, indent=None if compact else 2, default=str))


def run(
    *,
    domain: str,
    parser: argparse.ArgumentParser,
    argv: list[str] | None,
) -> None:
    """Parse ``argv``, dispatch to ``args.func``, emit the envelope, and exit.

    ``args.func`` must accept the parsed namespace and return the ``data``
    payload (a JSON-able object). Typed :class:`HelperError` subclasses map to
    their exit codes; a write-guard refusal (:class:`LocalWriteRefused`) maps to
    exit 2; a storage / integrity / access failure (``BLOCKED_ACCESS`` ...) maps to
    exit 7; any other exception maps to ``api-error`` (exit 3).
    """
    try:
        args = parser.parse_args(argv)
    except ArgError as exc:
        emit(
            envelope(
                ok=False,
                domain=domain,
                command=None,
                error=exc.message,
                meta=build_meta(),
            )
        )
        sys.exit(exc.exit_code)

    command = getattr(args, "command", None)
    meta = build_meta(getattr(args, "format", "json"))

    try:
        data = args.func(args)
    except HelperError as exc:
        emit(
            envelope(
                ok=False,
                domain=domain,
                command=command,
                error=exc.message,
                meta=meta,
                code=exc.code,
                retryable=exc.retryable,
            )
        )
        sys.exit(exc.exit_code)
    except SystemExit:
        raise
    except LocalWriteRefused as exc:
        # The write guard refused a local write on a covered run: a refusal, not an
        # API failure. The message already starts with ``LOCAL_STORAGE_REFUSED:``.
        emit(
            envelope(
                ok=False, domain=domain, command=command, error=str(exc), meta=meta
            )
        )
        sys.exit(EXIT_REFUSED)
    except Exception as exc:  # noqa: BLE001 - map any stray error to api-error
        code = storage_failure_code(exc)
        emit(
            envelope(
                ok=False,
                domain=domain,
                command=command,
                error=f"{code}: {exc}" if code else f"API error: {exc}",
                meta=meta,
                code=code,
                retryable=code == "STORAGE_TRANSIENT",
            )
        )
        sys.exit(storage_exit_code(code) if code else EXIT_API)

    emit(envelope(ok=True, domain=domain, command=command, data=data, meta=meta))
    sys.exit(EXIT_OK)
