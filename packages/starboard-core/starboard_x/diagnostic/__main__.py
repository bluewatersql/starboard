# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.diagnostic`` — dep-light diagnostic CLI (Phase-1 B2).

Thin ``argparse`` wrappers over the re-homed stdlib-only trio. Every invocation
emits the stable JSON envelope (:mod:`starboard_x.contract`) on stdout and uses
the Phase-0 exit-code contract::

    0 ok · 1 auth · 2 not-found/refused · 3 api-error · 4 arg-error · 7 storage

Verbs:
    triage-exit      --exit-code N [--context TEXT | --text FILE]
    extract-evidence --text FILE
    rca              --text FILE [--exit-code N]
    profile          --input drive:<id>|FILE   (query-profile JSON summary)

The wrappers import the **existing** classes and call their methods — no logic
duplication (progressive_helpers/technical.md §3).
"""

from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from starboard_x.contract import ArgError
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
    """Read ``--text`` through the shared customer-file intake (W30).

    A missing file is an :class:`ArgError` (exit 4); a local file on an overlay
    install is refused (exit 2); ``drive:<object id>`` is read from Drive in memory.
    Imported lazily so the trio stays stdlib-only at import time.
    """
    from starboard_x import _cli

    return _cli.read_text_file(path_str, flag="--text")


def _read_profile_bytes(value: str) -> bytes:
    """Read ``--input`` (``drive:<id>`` or a local file) bounded by the intake cap.

    A local file larger than :data:`starboard_x._cli.MAX_INTAKE_BYTES` is refused
    (exit 4) before it is read; a local file on an overlay install is refused (exit 2).
    """
    from starboard_x import _cli

    data = _cli.read_intake_bytes(value, flag="--input")
    if data is not None:
        return data
    path = Path(value)
    if not path.is_file():
        raise ArgError(f"--input file not found: {value}")
    try:
        if path.stat().st_size > _cli.MAX_INTAKE_BYTES:
            raise ArgError(
                f"--input {value} is larger than {_cli.MAX_INTAKE_BYTES} bytes"
            )
        return path.read_bytes()
    except OSError as exc:
        raise ArgError(f"could not read --input file {value}: {exc}") from exc


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


def _cmd_profile(args: argparse.Namespace) -> dict[str, Any]:
    """Summarize a query profile (stdlib parser; read-only, writes nothing)."""
    from starboard_x import _cli
    from starboard_x.diagnostic.query_profile import parse_profile

    content = _read_profile_bytes(args.input)
    try:
        summary = parse_profile(content)
    except ValueError as exc:
        raise ArgError(f"--input is not valid JSON ({args.input}): {exc}") from exc
    data = summary.to_dict()
    if _cli.detect_overlay().enabled:
        from starboard_x.discovery._authorization import bounded_stdout

        return bounded_stdout(data)
    return data


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

    p_profile = subparsers.add_parser(
        "profile", help="Summarize a Databricks query profile (JSON)."
    )
    p_profile.add_argument(
        "--input",
        required=True,
        help="Query-profile JSON: drive:<object id> or a local file (public install).",
    )
    p_profile.set_defaults(func=_cmd_profile)

    return parser


def main(argv: list[str] | None = None) -> None:
    from starboard_x import _cli

    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
