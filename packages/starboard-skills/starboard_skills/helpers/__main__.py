#!/usr/bin/env python3
"""starboard-helper <domain> <command> [options]

Thin Databricks data-fetching helper for Claude skills.

All output is a stable JSON envelope on stdout::

    {"ok": bool, "domain": str|null, "command": str|null,
     "data": <result>|null, "error": str|null,
     "meta": {"format": "json", "contract_version": "1.0"}}

Exit codes:
  0 = ok
  1 = authentication error
  2 = not found
  3 = API error
  4 = argument error
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from starboard_skills.helpers.contract import (
    EXIT_API,
    EXIT_ARG,
    EXIT_OK,
    ArgError,
    HelperError,
    build_meta,
    envelope,
)


class _HelperArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises :class:`ArgError` instead of exiting(2).

    This funnels every argparse failure (missing required args, bad choices,
    unknown subcommands) through the same envelope + exit-code path as runtime
    errors, so bad args deterministically produce exit code 4.
    """

    def error(self, message: str):  # type: ignore[override]
        raise ArgError(message)


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _HelperArgumentParser(
        prog="starboard-helper",
        description="Thin Databricks data-fetching helper for Claude skills.",
    )
    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format (json is the default and only supported format).",
    )
    subparsers = parser.add_subparsers(dest="domain", required=True)

    from starboard_skills.helpers import (
        analyze,
        cluster,
        diagnostic,
        discovery,
        finops,
        job,
        query,
        uc,
        warehouse,
    )

    for mod in [
        job,
        query,
        warehouse,
        uc,
        cluster,
        finops,
        diagnostic,
        analyze,
        discovery,
    ]:
        mod.register(subparsers)

    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()

    try:
        args = parser.parse_args(argv)
    except ArgError as exc:
        _emit(
            envelope(
                ok=False,
                domain=None,
                command=None,
                error=exc.message,
                meta=build_meta(),
            )
        )
        sys.exit(EXIT_ARG)

    domain = getattr(args, "domain", None)
    command = getattr(args, "command", None)
    meta = build_meta(getattr(args, "format", "json"))

    try:
        data = args.func(args)
    except HelperError as exc:
        _emit(
            envelope(
                ok=False,
                domain=domain,
                command=command,
                error=exc.message,
                meta=meta,
            )
        )
        sys.exit(exc.exit_code)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - map any stray error to api-error
        _emit(
            envelope(
                ok=False,
                domain=domain,
                command=command,
                error=f"API error: {exc}",
                meta=meta,
            )
        )
        sys.exit(EXIT_API)

    _emit(
        envelope(
            ok=True,
            domain=domain,
            command=command,
            data=data,
            meta=meta,
        )
    )
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
