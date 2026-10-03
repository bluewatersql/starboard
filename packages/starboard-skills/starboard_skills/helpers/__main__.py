#!/usr/bin/env python3
"""starboard-helper <domain> <command> [options]

Thin Databricks data-fetching helper for Starboard skills (any host).

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
from pathlib import Path
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
        description="Thin Databricks data-fetching helper for Starboard skills (any host).",
    )
    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format (json is the default and only supported format).",
    )
    parser.add_argument(
        "--out",
        metavar="FILE",
        default=None,
        help=(
            "Write the full result envelope to FILE (parent dirs created) and "
            "print a compact summary to stdout instead. Use for large fetches "
            "(query history, job/table lists) to avoid truncating the payload "
            "in the tool result, then read FILE for the rows. May be placed "
            "before or after the subcommand. Errors are always printed, never "
            "redirected."
        ),
    )
    subparsers = parser.add_subparsers(dest="domain", required=True)

    from starboard_skills.helpers import (
        analyze,
        charts_render,
        cluster,
        database,
        diagnostic,
        discovery,
        finops,
        job,
        notebook,
        query,
        run,
        uc,
        verify,
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
        charts_render,
        database,
        run,
        verify,
        notebook,
    ]:
        mod.register(subparsers)

    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, default=str))


# Domains whose subcommand owns ``--out`` as a real output path (not the global
# envelope-redirect). For these, the global ``--out`` extraction is skipped so
# the flag reaches the subparser intact. ``charts render --out chart.png`` writes
# a rendered PNG/SVG; redirecting its JSON envelope to that path would clobber the
# image and starve the subparser of its required argument. ``verify run`` and
# ``notebook render`` take ``--out DIR`` (the evidence / notebook directory).
_OUT_OWNING_DOMAINS = frozenset({"charts", "verify", "notebook"})


def _leading_domain(argv: list[str]) -> str | None:
    """Return the domain (first positional) token, skipping global value-flags.

    Global options that take a value (``--format``/``--out``) and their values,
    plus any other leading flags, are skipped so the first positional token —
    the subcommand domain — is found regardless of preceding global flags.
    """
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--format", "--out"):
            i += 2  # skip the flag and its value
            continue
        if a.startswith(("--format=", "--out=")):
            i += 1
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a
    return None


def _extract_out(argv: list[str]) -> tuple[str | None, list[str]]:
    """Pull ``--out FILE`` / ``--out=FILE`` from anywhere in argv.

    Returns ``(out_path, remaining_argv)``. Stripping it before argparse lets
    ``--out`` appear either before or after the subcommand (argparse otherwise
    only accepts a top-level option before the subcommand). A trailing ``--out``
    with no value is left in place so argparse reports the argument error.

    For domains whose subcommand owns ``--out`` as a real output path
    (:data:`_OUT_OWNING_DOMAINS`, e.g. ``charts render``), extraction is skipped
    entirely so the flag reaches the subparser — the global envelope-redirect
    does not apply there.
    """
    if _leading_domain(argv) in _OUT_OWNING_DOMAINS:
        return None, list(argv)

    out: str | None = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--out":
            if i + 1 < len(argv):
                out = argv[i + 1]
                i += 2
                continue
            rest.append(arg)  # dangling --out → let argparse error on it
            i += 1
            continue
        if arg.startswith("--out="):
            out = arg.split("=", 1)[1]
            i += 1
            continue
        rest.append(arg)
        i += 1
    return out, rest


def _count_rows(data: Any) -> int | None:
    """Best-effort total row count for the stdout summary (no shape coupling).

    Prefers ``data["row_count"]`` when present (W27: avoids counting the
    ``columns`` list as rows, which inflated the count when a query result dict
    contained both ``columns`` and ``rows`` keys).
    """
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        # Prefer an explicit row_count — avoids counting column-name lists as rows.
        if isinstance(data.get("row_count"), int):
            return data["row_count"]
        total = 0
        found = False
        for value in data.values():
            if isinstance(value, list):
                total += len(value)
                found = True
        return total if found else None
    return None


def _write_out(payload: dict[str, Any], path: str) -> None:
    """Write the full envelope to ``path``; print a compact summary to stdout."""
    text = json.dumps(payload, indent=2, default=str)
    out_path = Path(path)
    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)

    summary: dict[str, Any] = {
        "ok": payload.get("ok"),
        "domain": payload.get("domain"),
        "command": payload.get("command"),
        "out": str(out_path),
        "bytes": len(text.encode("utf-8")),
        "meta": payload.get("meta"),
    }
    rows = _count_rows(payload.get("data"))
    if rows is not None:
        summary["rows"] = rows
    summary["note"] = f"Full JSON written to {out_path}. Read that file for the data."
    print(json.dumps(summary, indent=2, default=str))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    out_path, raw_argv = _extract_out(raw_argv)

    try:
        args = parser.parse_args(raw_argv)
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

    # Expose the extracted global --out to commands that emit their own envelope (run check).
    # (Never set for _OUT_OWNING_DOMAINS: their extraction is skipped, so out_path is None.)
    if out_path is not None:
        args.out = out_path
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

    success = envelope(
        ok=True,
        domain=domain,
        command=command,
        data=data,
        meta=meta,
    )
    if out_path:
        _write_out(success, out_path)
    else:
        _emit(success)
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
