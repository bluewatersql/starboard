# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.diagnostic`` — dep-light diagnostic CLI (Phase-1 B2).

Thin ``argparse`` wrappers over the re-homed stdlib-only trio. Every invocation
emits the stable JSON envelope (:mod:`starboard_x.contract`) on stdout and uses
the Phase-0 exit-code contract::

    0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error

Verbs:
    triage-exit      --exit-code N [--context TEXT | --text FILE]
    extract-evidence --text FILE
    rca              --text FILE [--exit-code N]

The wrappers import the **existing** classes and call their methods — no logic
duplication (progressive_helpers/technical.md §3).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields, is_dataclass
from enum import Enum
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
from starboard_x.diagnostic.evidence_extractor import (
    EvidenceWindowExtractor,
    ExtractionResult,
)
from starboard_x.diagnostic.exit_code_triager import ExitCodeTriager, TriageResult
from starboard_x.diagnostic.root_cause_synthesizer import RootCauseSynthesizer

_DOMAIN = "diagnostic"


# --------------------------------------------------------------------------- #
# Serialization: dataclass/enum/tuple -> JSON-able primitives.
# --------------------------------------------------------------------------- #
def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses/enums/tuples into JSON-able primitives."""
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    return obj


# --------------------------------------------------------------------------- #
# argparse plumbing (mirrors starboard_skills.helpers.__main__).
# --------------------------------------------------------------------------- #
class _ArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises :class:`ArgError` instead of ``exit(2)``.

    Funnels every argparse failure (missing/invalid args, bad choices, unknown
    subcommands) through the envelope + exit-code 4 path.
    """

    def error(self, message: str):  # type: ignore[override]
        raise ArgError(message)


def _read_text(path_str: str) -> str:
    """Read a text file, raising :class:`ArgError` (exit 4) when it is missing."""
    path = Path(path_str)
    if not path.is_file():
        raise ArgError(f"--text file not found: {path_str}")
    try:
        return path.read_text()
    except OSError as exc:
        raise ArgError(f"could not read --text file {path_str}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Verb handlers — each returns the ``data`` payload (a JSON-able dict).
# --------------------------------------------------------------------------- #
def _triage_result_to_data(result: TriageResult) -> dict[str, Any]:
    return _to_jsonable(result)


def _extraction_result_to_data(result: ExtractionResult) -> dict[str, Any]:
    data = _to_jsonable(result)
    # ``window_count`` is a property (not a dataclass field) — add it explicitly.
    data["window_count"] = result.window_count
    return data


def _cmd_triage_exit(args: argparse.Namespace) -> dict[str, Any]:
    context = args.context or ""
    if args.text:
        context = f"{context}\n{_read_text(args.text)}".strip()
    result = ExitCodeTriager().triage(exit_code=args.exit_code, context=context)
    return _triage_result_to_data(result)


def _cmd_extract_evidence(args: argparse.Namespace) -> dict[str, Any]:
    text = _read_text(args.text)
    result = EvidenceWindowExtractor().extract(text)
    return _extraction_result_to_data(result)


def _cmd_rca(args: argparse.Namespace) -> dict[str, Any]:
    text = _read_text(args.text)

    # 1) Exit-code triage (optional).
    triage_data: dict[str, Any] | None = None
    if args.exit_code is not None:
        triage = ExitCodeTriager().triage(exit_code=args.exit_code, context=text)
        triage_data = _triage_result_to_data(triage)

    # 2) Evidence extraction.
    extraction = EvidenceWindowExtractor().extract(text)
    evidence_data = _extraction_result_to_data(extraction)

    # 3) Synthesis over the extracted evidence. The stdlib-only tier has no
    #    pattern matcher (that lives behind the ``diagnostics`` extra), so
    #    ``matched_patterns`` is empty here; the pattern-aware RCA is available
    #    through the full agent (Tier-2) or the ``diagnostics`` extra.
    evidence_refs = [w.window_id for w in extraction.windows]
    initial_confidence = (
        extraction.primary_evidence.confidence
        if extraction.primary_evidence is not None
        else 0.3
    )
    synthesis = RootCauseSynthesizer().synthesize(
        tool_outputs=[],
        exploration_findings={
            "matched_patterns": [],
            "evidence_refs": evidence_refs,
            "initial_confidence": initial_confidence,
        },
    )

    return {
        "triage": triage_data,
        "evidence": evidence_data,
        "synthesis": _to_jsonable(synthesis),
    }


# --------------------------------------------------------------------------- #
# Parser construction.
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _ArgumentParser(
        prog="python -m starboard_x.diagnostic",
        description="Dep-light Databricks failure diagnostics (stdlib-only trio).",
    )
    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format (json is the default and only supported format).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_triage = subparsers.add_parser(
        "triage-exit", help="Triage a process exit code into ranked hypotheses."
    )
    p_triage.add_argument("--exit-code", type=int, required=True)
    p_triage.add_argument(
        "--context", default="", help="Extra context (logs/error text) for evidence."
    )
    p_triage.add_argument(
        "--text", default=None, help="File whose contents to use as context."
    )
    p_triage.set_defaults(func=_cmd_triage_exit)

    p_extract = subparsers.add_parser(
        "extract-evidence", help="Extract evidence windows from an error log."
    )
    p_extract.add_argument("--text", required=True, help="Path to the log/error file.")
    p_extract.set_defaults(func=_cmd_extract_evidence)

    p_rca = subparsers.add_parser(
        "rca", help="End-to-end root-cause analysis (triage + evidence + synthesis)."
    )
    p_rca.add_argument("--text", required=True, help="Path to the log/error file.")
    p_rca.add_argument("--exit-code", type=int, default=None)
    p_rca.set_defaults(func=_cmd_rca)

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
                domain=_DOMAIN,
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
        _emit(
            envelope(
                ok=False,
                domain=_DOMAIN,
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
                domain=_DOMAIN,
                command=command,
                error=f"API error: {exc}",
                meta=meta,
            )
        )
        sys.exit(EXIT_API)

    _emit(
        envelope(
            ok=True,
            domain=_DOMAIN,
            command=command,
            data=data,
            meta=meta,
        )
    )
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
