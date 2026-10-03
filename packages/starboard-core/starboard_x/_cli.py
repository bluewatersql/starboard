# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared ``argparse`` + envelope plumbing for the ``starboard_x`` sub-commands.

Every ``python -m starboard_x.<domain>`` CLI (Phase-2 D4) funnels through the
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

from starboard_x.contract import (
    EXIT_API,
    EXIT_OK,
    ArgError,
    HelperError,
    build_meta,
    envelope,
)


class ArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises :class:`ArgError` instead of ``exit(2)``.

    Funnels every argparse failure (missing/invalid args, bad choices, unknown
    subcommands) through the envelope + exit-code 4 path.
    """

    def error(self, message: str):  # type: ignore[override]
        raise ArgError(message)


def read_text_file(path_str: str, *, flag: str = "--path") -> str:
    """Read a text file, raising :class:`ArgError` (exit 4) when it is missing."""
    path = Path(path_str)
    if not path.is_file():
        raise ArgError(f"{flag} file not found: {path_str}")
    try:
        return path.read_text()
    except OSError as exc:
        raise ArgError(f"could not read {flag} file {path_str}: {exc}") from exc


def read_json_file(path_str: str, *, flag: str = "--input") -> Any:
    """Read + parse a JSON file, raising :class:`ArgError` (exit 4) on failure."""
    text = read_text_file(path_str, flag=flag)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArgError(f"{flag} is not valid JSON ({path_str}): {exc}") from exc


def emit(payload: dict[str, Any]) -> None:
    """Write the envelope to stdout as indented JSON."""
    print(json.dumps(payload, indent=2, default=str))


def run(
    *,
    domain: str,
    parser: argparse.ArgumentParser,
    argv: list[str] | None,
) -> None:
    """Parse ``argv``, dispatch to ``args.func``, emit the envelope, and exit.

    ``args.func`` must accept the parsed namespace and return the ``data``
    payload (a JSON-able object). Typed :class:`HelperError` subclasses map to
    their exit codes; any other exception maps to ``api-error`` (exit 3).
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
                ok=False, domain=domain, command=command, error=exc.message, meta=meta
            )
        )
        sys.exit(exc.exit_code)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - map any stray error to api-error
        emit(
            envelope(
                ok=False,
                domain=domain,
                command=command,
                error=f"API error: {exc}",
                meta=meta,
            )
        )
        sys.exit(EXIT_API)

    emit(envelope(ok=True, domain=domain, command=command, data=data, meta=meta))
    sys.exit(EXIT_OK)
