# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.review`` — pure Workload Review CLI (Phase-3 D1b).

Thin ``argparse`` wrapper over the kernel's deterministic Workload Review engine.
Every invocation emits the stable JSON envelope (:mod:`starboard_x.contract`) and
uses the Phase-0 exit-code contract (``0 ok · 1 auth · 2 not-found · 3 api-error
· 4 arg-error``).

Verbs:
    score --rows <json> [--domains jobs,sql,warehouse] [--workspace NAME]
          [--run-folder ID [--out REL] [--manifest-out REL]]

The ``score`` verb is I/O-free: it loads query-pack rows from ``--rows`` and
scores them against the seed :class:`~starboard_core.domain.rules.registry.RuleRegistry`
entirely in-process, importing only the pure kernel engine (no ``databricks-sdk``).

``--rows`` accepts either:
    * a bare object mapping ``query_id`` → list of row objects, e.g.
      ``{"W-W02": [{"warehouse_id": "wh1", "auto_stop_waste_pct": 80.0}]}``, or
    * an object of the form ``{"rows_by_query_id": {...}, "failed_query_ids":
      [...], "workspace": "..."}`` for full control over degradation signals.

``--run-folder ID`` targets the run's Drive folder: ``--rows`` is read
from the run (a run-relative path, or ``drive:<object id>`` for an object outside
it), and the review is written there as ``analysis/review.json``,
``analysis/review.md`` and ``findings-manifest.json`` (``--out`` / ``--manifest-out``
override the relpaths; each object is recorded in ``evidence/index.json``). Nothing is
written to local disk, and stdout carries a bounded summary (IDs, refs, counts, the top
findings) instead of the evidence rows. With the internal overlay enabled the run is
covered: the write guard is armed and a local ``--rows`` path is refused with exit 2
(``LOCAL_STORAGE_REFUSED``). Without ``--run-folder`` the verb is unchanged.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

from starboard_core.engagement.enforce import (
    WriterContext,
    covered,
    refuse_local,
    writer_context,
)
from starboard_core.engagement.evidence import (
    DEFAULT_INTERNAL_SOURCE,
    input_source_kinds,
    record_run_evidence,
)
from starboard_core.engagement.overlay import detect_overlay
from starboard_core.engagement.reads import ReadRefusedError, read_verified, run_relpath
from starboard_core.engagement.records import StorageRef
from starboard_core.engagement.sink import (
    EVIDENCE_INDEX,
    ArtifactSink,
    load_engagement_storage,
)
from starboard_core.ports.engagement_storage import (
    EngagementStoragePort,
    StorageNotFoundError,
)

from starboard_x import _cli
from starboard_x.contract import ArgError
from starboard_x.discovery._authorization import bounded_stdout, storage_refusals

_DOMAIN = "review"

#: Canonical run-relative outputs of ``score --run-folder`` (spec §A).
REVIEW_JSON_RELPATH = "analysis/review.json"
REVIEW_MD_RELPATH = "analysis/review.md"
MANIFEST_RELPATH = "findings-manifest.json"
_METHOD_VERSION = "review_score_v1"
_JSON_MIME = "application/json"
_MARKDOWN_MIME = "text/markdown"
#: Largest ``--rows`` object read from outside the run (``drive:<id>``).
_MAX_ROWS_BYTES = 64 * 2**20
_TOP_FINDINGS = 10


def _parse_domains(raw: str | None) -> list[str]:
    """Split a comma-separated ``--domains`` value into a clean list."""
    from starboard_core.domain.rules.evaluator import DEFAULT_DOMAINS

    if not raw:
        return list(DEFAULT_DOMAINS)
    domains = [d.strip() for d in raw.split(",") if d.strip()]
    if not domains:
        raise ArgError("--domains was empty after parsing; omit it or pass names")
    return domains


def _load_rows(
    args: argparse.Namespace, payload: Any = None
) -> tuple[dict[str, list[dict[str, Any]]], list[str], str | None]:
    """Return ``(rows_by_query_id, failed_query_ids, workspace)`` from ``--rows``.

    ``payload`` is the already-parsed ``--rows`` document (the ``--run-folder`` path
    reads it from Drive); by default ``--rows`` is read as a local JSON file.
    """
    if payload is None:
        # Not customer-file intake (W30): ``score`` is gated by its own storage policy.
        payload = _cli.read_json_file(args.rows, flag="--rows", customer_file=False)

    if not isinstance(payload, dict):
        raise ArgError("--rows must be a JSON object keyed by query_id")

    if "rows_by_query_id" in payload:
        rows = payload.get("rows_by_query_id")
        failed = payload.get("failed_query_ids", [])
        workspace = payload.get("workspace")
    else:
        rows, failed, workspace = payload, [], None

    if not isinstance(rows, dict):
        raise ArgError("'rows_by_query_id' must be an object keyed by query_id")
    if not isinstance(failed, list):
        raise ArgError("'failed_query_ids' must be a list of query_id strings")

    normalized: dict[str, list[dict[str, Any]]] = {}
    for query_id, query_rows in rows.items():
        if not isinstance(query_rows, list):
            raise ArgError(f"rows for query_id '{query_id}' must be a list")
        normalized[str(query_id)] = [r for r in query_rows if isinstance(r, dict)]

    ws = str(workspace) if workspace is not None else args.workspace
    return normalized, [str(q) for q in failed], ws


def _score(
    args: argparse.Namespace, payload: Any = None
) -> Any:  # -> WorkloadReview
    # Import the pure engine lazily so the envelope/arg-error paths never need
    # it and the import stays visibly SDK-free.
    from starboard_core.domain.rules.evaluator import build_review
    from starboard_core.domain.rules.registry import RuleRegistry

    domains = _parse_domains(args.domains)
    rows_by_query_id, failed_query_ids, workspace = _load_rows(args, payload)

    registry = RuleRegistry.from_seed()
    return build_review(
        registry=registry,
        domains=domains,
        rows_by_query_id=rows_by_query_id,
        failed_query_ids=failed_query_ids,
        workspace=workspace,
    )


def _cmd_score(args: argparse.Namespace) -> dict[str, Any]:
    """Score rows; on an overlay install this is a gated writer (D-11).

    * ``--run-folder``: rows from and review to the Drive run (covered on overlay).
    * No ``--run-folder`` on an overlay install: refused (exit 2) unless ``--run-dir``
      is an internal-only local run.
    * Public install without ``--run-folder``: the unchanged stdout-only path.
    """
    run_folder: str | None = getattr(args, "run_folder", None)
    if not run_folder:
        for flag in ("out", "manifest_out"):
            if getattr(args, flag, None):
                raise ArgError(f"--{flag.replace('_', '-')} needs --run-folder")
    cache: list[EngagementStoragePort] = []

    def storage_factory() -> EngagementStoragePort:
        if not cache:
            cache.append(load_engagement_storage())
        return cache[0]

    with (
        storage_refusals(),
        writer_context(
            run_folder_id=run_folder,
            local_root=getattr(args, "run_dir", None),
            acquires_customer_data=False,
            storage_factory=storage_factory,
            overlay=detect_overlay(),
        ) as ctx,
    ):
        if run_folder:
            refuse_local(ctx.decision, run_dir=getattr(args, "run_dir", None))
            return _score_to_run(args, ctx, storage_factory())
        return _score(args).model_dump(mode="json")


def _md(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(review: dict[str, Any]) -> str:
    """The ranked review as Markdown (no evidence rows: they are in review.json)."""
    lines = ["# Workload Review", ""]
    if review.get("workspace"):
        lines += [f"Workspace: {_md(review['workspace'])}", ""]
    lines += [
        f"Domains: {', '.join(review.get('requested_domains') or []) or 'none'}",
        f"Findings: {review.get('finding_count', 0)}",
        f"Degraded: {'yes' if review.get('degraded') else 'no'}",
        f"Cost basis: {_md(review.get('cost_basis', ''))}",
        "",
    ]
    unavailable = review.get("unavailable_queries") or []
    if unavailable:
        lines += [f"Unavailable evidence queries: {', '.join(unavailable)}", ""]
    findings = review.get("findings") or []
    if not findings:
        lines.append("No findings.")
    else:
        lines += [
            "| # | Severity | Score | Category | Summary | Evidence |",
            "|---|---|---|---|---|---|",
        ]
        for rank, rf in enumerate(findings, start=1):
            f = rf.get("finding", {})
            cites = ", ".join(
                f"{e.get('query_id')}[{e.get('row_index')}]"
                for e in rf.get("evidence") or []
            )
            lines.append(
                f"| {rank} | {_md(f.get('severity'))} | {f.get('score', 0):.1f} | "
                f"{_md(f.get('category'))} | {_md(f.get('summary'))} | {_md(cites)} |"
            )
    return "\n".join(lines) + "\n"


def _read_rows_from_run(
    sink: ArtifactSink, storage: EngagementStoragePort, value: str, *, covered_run: bool
) -> Any:
    """``--rows`` with ``--run-folder``: a run-relative path or ``drive:<object id>``."""
    if value.startswith("drive:"):
        object_id = value[len("drive:") :]
        try:
            data = read_verified(storage, object_id, max_bytes=_MAX_ROWS_BYTES)
        except StorageNotFoundError as exc:
            raise ArgError(f"--rows: {value} not found: {exc}") from exc
        except ReadRefusedError as exc:
            raise ArgError(f"--rows: {exc}") from exc
    else:
        rel = run_relpath("--rows", value, covered_run=covered_run, arg_error=ArgError)
        try:
            data = sink.get_bytes(rel, max_bytes=_MAX_ROWS_BYTES)
        except StorageNotFoundError as exc:
            raise ArgError(f"--rows: {rel} is not in the run folder") from exc
        except ReadRefusedError as exc:
            raise ArgError(f"--rows: {exc}") from exc
    try:
        return json.loads(data)
    except ValueError as exc:
        raise ArgError(f"--rows is not valid JSON ({value}): {exc}") from exc


def _relpath_option(args: argparse.Namespace, flag: str, default: str, *, covered_run: bool) -> str:
    value = getattr(args, flag, None)
    if not value:
        return default
    name = "--" + flag.replace("_", "-")
    return run_relpath(name, value, covered_run=covered_run, arg_error=ArgError)


def _put_manifest(sink: ArtifactSink, rel: str, data: bytes) -> StorageRef:
    """Write the findings manifest.

    The canonical manifest is a kernel record (``put_record``). A host-chosen
    ``--manifest-out`` is an ordinary artifact: ``put_bytes`` refuses a reserved name.
    """
    if rel == MANIFEST_RELPATH:
        return sink.put_record(rel, data, _JSON_MIME)
    return sink.put_bytes(rel, data, _JSON_MIME)


def _is_internal_payload(payload: Any) -> bool:
    """Whether a ``--rows`` document says it came from the internal mirror."""
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    return payload.get("source") == "internal" or (
        isinstance(data, dict) and data.get("source") == "internal"
    )


def _score_to_run(
    args: argparse.Namespace, ctx: WriterContext, storage: EngagementStoragePort
) -> dict[str, Any]:
    """``score --run-folder``: rows from the run, review written to the run."""
    from starboard_core.domain.rules.action_rate import FindingsManifest

    sink = ctx.sink
    is_covered = covered(ctx.decision)
    review_rel = _relpath_option(args, "out", REVIEW_JSON_RELPATH, covered_run=is_covered)
    manifest_rel = _relpath_option(
        args, "manifest_out", MANIFEST_RELPATH, covered_run=is_covered
    )
    md_rel = (
        review_rel[: -len(".json")] + ".md"
        if review_rel.endswith(".json") and review_rel != REVIEW_JSON_RELPATH
        else REVIEW_MD_RELPATH
    )
    payload = _read_rows_from_run(sink, storage, args.rows, covered_run=is_covered)
    review = _score(args, payload)

    dump = review.model_dump(mode="json")
    manifest = FindingsManifest.from_review(
        review, run_date=datetime.now(UTC).date().isoformat()
    ).model_dump(mode="json")
    written: list[StorageRef] = [
        sink.put_bytes(
            review_rel, json.dumps(dump, indent=2, default=str).encode(), _JSON_MIME
        ),
        sink.put_bytes(md_rel, render_markdown(dump).encode("utf-8"), _MARKDOWN_MIME),
        _put_manifest(
            sink, manifest_rel, json.dumps(manifest, indent=2, default=str).encode()
        ),
    ]
    input_kinds = input_source_kinds(sink, [args.rows])
    if _is_internal_payload(payload):
        input_kinds.append(DEFAULT_INTERNAL_SOURCE)
    recorded = record_run_evidence(
        sink,
        storage,
        args.run_folder,
        [(ref, f"review:{ref.path}", None, False) for ref in written],
        input_kinds=input_kinds,
        method_version=_METHOD_VERSION,
    )
    index = [r for r in sink.refs() if r.path == EVIDENCE_INDEX][-1:] if recorded else []
    refs = [*written, *index]

    ranked = [
        {
            "id": rf["finding"]["id"],
            "severity": rf["finding"]["severity"],
            "score": rf["finding"]["score"],
            "category": rf["finding"]["category"],
            "summary": rf["finding"]["summary"],
        }
        for rf in dump["findings"][:_TOP_FINDINGS]
    ]
    data: dict[str, Any] = {
        "run_id": sink.run_id,
        "run_folder_id": args.run_folder,
        "refs": [r.to_dict() for r in refs],
        "counts": {
            "findings": dump["finding_count"],
            "unavailable_queries": len(dump["unavailable_queries"]),
        },
        "summary": {
            "degraded": dump["degraded"],
            "unavailable_domains": dump["unavailable_domains"],
            "cost_basis": dump["cost_basis"],
            "top_findings": ranked,
        },
        "note": "The full review and evidence rows are in the run folder (refs).",
    }
    return bounded_stdout(data) if is_covered else data


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.review",
        description="Pure Workload Review scoring over query-pack rows (no I/O).",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_score = subparsers.add_parser(
        "score",
        help="Score query-pack rows against the seed rules → ranked findings.",
    )
    p_score.add_argument(
        "--rows",
        required=True,
        help="Path to a JSON file of query-pack rows keyed by query_id.",
    )
    p_score.add_argument(
        "--domains",
        default=None,
        help="Comma-separated review domains (default: jobs,sql,warehouse).",
    )
    p_score.add_argument(
        "--workspace",
        default=None,
        help="Workspace identifier to record in the review envelope.",
    )
    p_score.add_argument(
        "--run-folder",
        dest="run_folder",
        default=None,
        metavar="ID",
        help=(
            "Drive run folder ID. --rows is then a run-relative path (or drive:<id>); "
            "the review is written to the run (analysis/review.json, "
            "analysis/review.md, findings-manifest.json), never to local disk, and "
            "stdout is a bounded summary."
        ),
    )
    p_score.add_argument(
        "--out",
        default=None,
        metavar="RELPATH",
        help="With --run-folder: run-relative path of the review JSON "
        f"(default {REVIEW_JSON_RELPATH}).",
    )
    p_score.add_argument(
        "--manifest-out",
        dest="manifest_out",
        default=None,
        metavar="RELPATH",
        help="With --run-folder: run-relative path of the findings manifest "
        f"(default {MANIFEST_RELPATH}).",
    )
    p_score.add_argument(
        "--run-dir",
        dest="run_dir",
        default=None,
        metavar="DIR",
        help=(
            "Overlay installs without --run-folder only: the local run directory of an "
            "internal-only local run (its analysis/run-authorization.json must record "
            "storage policy internal_only_local). Customer runs use --run-folder."
        ),
    )
    p_score.set_defaults(func=_cmd_score)

    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
