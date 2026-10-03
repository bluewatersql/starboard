"""Run domain helper — validate an engagement run directory and run the recur beat.

Commands:
  check <run-dir> [--internal]   Validate the §4 checklist from convergence-contracts.md.
  recur <run-dir> --workspace-root <dir> [--prior <dir> | --baseline]
                                 Deterministic recur beat: trend history append (idempotent by
                                 run_date), trend chart data + PNGs, delta-vs-<prior-date>.md
                                 skeleton from the saved review JSON's cost_delta plus the
                                 backlog.json catalog-id delta, README '## Recur', and
                                 analysis/recur-result.json (read back by ``run check``).

Exit codes for ``run check``:
  0   All checks passed.
  1   One or more checklist items failed.  There is no dedicated "check-failed" code in
      the shared contract exit table; exit 1 is used here and callers should inspect
      ``data.summary.all_passed`` together with ``data.failed`` for details.
  4   Bad arguments (arg-error), e.g. run-dir does not exist.

This domain uses a direct-print-and-exit pattern inside cmd_check so that it can emit a
fully-populated envelope (with data.passed/failed even on failure) *and* return a non-zero
exit code.  The standard dispatcher always exits 0 on a successful return, which would hide
check failures.  main() re-raises SystemExit, so this is safe and does not double-print.

NOTE: for ``run check`` the global ``--out FILE`` flag writes the envelope to FILE *as well
as* stdout (not a redirect + summary), e.g.
``run check "$RUN_DIR" --internal --out "$RUN_DIR/analysis/run-check.json"`` — that file is
the run's check record (README needs no ``## Run check`` section).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starboard_skills.helpers.contract import EXIT_OK, ArgError, build_meta, envelope

# Exit code when ≥1 checks fail (re-purposes slot 1 — documented above).
_EXIT_CHECK_FAILED = 1

# §2 canonical opportunity-id pattern
_OPP_ID_RE = re.compile(r"^OPP-[A-Z0-9-]+$")

# Valid values for backlog item fields
_VALID_TIERS = frozenset({"act_now", "investigate", "not_now"})
_VALID_SIZING_KINDS = frozenset({"bounded_dbu", "perf_metric", "pilot", "none"})

#: Canonical ``perf_metric`` per catalog id: ``id -> (sizing.metric, sizing.unit)``.  Mirrors the
#: "Canonical perf metrics" table in ``starboard-action-plan/references/opportunity-catalog.md``
#: (a unit test parses that table and asserts equality, so the two cannot drift).  A backlog item
#: with ``sizing.kind == "perf_metric"`` must carry exactly this metric and unit; ids not listed here
#: have no perf_metric sizing (OPP-OTHER may use any non-empty metric + unit).
_PERF_METRICS: dict[str, tuple[str, str]] = {
    "OPP-WH-QUEUE": ("peak_daily_queued_pct", "%"),
    "OPP-WH-SCAN": ("avg_read_gb_per_query", "GB/query"),
    "OPP-WH-RESIZE": ("dbus_per_billed_hour_after", "DBU/hour"),
    "OPP-JOB-OVERLAP": ("pct_runs_started_while_running", "%"),
    "OPP-JOB-TIMEOUT": ("max_run_mins", "min"),
}

#: ``items[].target``: the entity the item acts on, ``<kind>:<id>`` or ``workspace``.  Unique per
#: (id, target) within a backlog; compare-runs keys items on (id, target).
_TARGET_RE = re.compile(
    r"^(workspace|(job|warehouse|pipeline|cluster|dashboard|genie|schema|endpoint|instance):\S+)$"
)

#: ``cut[].rule`` — why a fired id is cut rather than carried as Not now (catalog cut rule).
_VALID_CUT_RULES = frozenset({"disqualifier", "no_evidence", "duplicate"})

#: Verify templates per catalog id — mirrors each entry's ``| Verify | vt-a, vt-b |`` row in
#: ``opportunity-catalog.md`` (a unit test parses the rows and asserts equality).  A
#: ``cut[].rule == "no_evidence"`` is valid only when the evidence was unavailable from the
#: source, i.e. at least one of these templates was attempted: an ``analysis/verify/<vt-id>*.json``
#: exists (``ok`` true or false).  Not running a template is not "no evidence".
_VERIFY_TEMPLATES: dict[str, tuple[str, ...]] = {
    "OPP-WH-QUEUE": ("vt-warehouse-queue", "vt-warehouse-drivers", "vt-warehouse-config-history"),
    "OPP-WH-IDLE": ("vt-warehouse-dbu", "vt-warehouse-config-history"),
    "OPP-WH-CLASSIC-TO-SERVERLESS": ("vt-warehouse-dbu", "vt-warehouse-config-history"),
    "OPP-WH-SCAN": ("vt-warehouse-drivers", "vt-heavy-statements"),
    "OPP-WH-RESIZE": ("vt-warehouse-config-history", "vt-warehouse-change-rate"),
    "OPP-JOB-OVERLAP": ("vt-job-overlap", "vt-job-runs", "vt-job-settings-history"),
    "OPP-JOB-TIMEOUT": ("vt-job-runs", "vt-job-run-tail", "vt-job-settings-history"),
    "OPP-JOB-FAILURE": ("vt-job-failures", "vt-job-runs"),
    "OPP-JOB-WAIT-TASK": ("vt-task-durations",),
    "OPP-SERVERLESS-STANDARD-MODE": ("vt-perf-target-mix", "vt-job-runs"),
    "OPP-STEP-CHANGE": ("vt-step-change", "vt-daily-totals"),
    "OPP-DLT-CADENCE": ("vt-pipeline-updates",),
    "OPP-CLUSTER-RIGHTSIZE": ("vt-cluster-driver-attribution", "vt-job-runs"),
    "OPP-LAKEBASE": ("vt-product-totals",),
    "OPP-PO": ("vt-product-totals",),
}

#: Allowed ``items[].target`` kinds per catalog id — mirrors each entry's ``| Target kind | … |``
#: row in ``opportunity-catalog.md`` (a unit test parses the rows and asserts equality).  The kind
#: is the ``<kind>`` of ``<kind>:<id>``, or ``workspace``.  Ids not listed (OPP-OTHER) take any kind.
_TARGET_KINDS: dict[str, frozenset[str]] = {
    "OPP-WH-QUEUE": frozenset({"warehouse"}),
    "OPP-WH-IDLE": frozenset({"warehouse", "cluster"}),
    "OPP-WH-CLASSIC-TO-SERVERLESS": frozenset({"warehouse"}),
    "OPP-WH-SCAN": frozenset({"warehouse", "dashboard"}),
    "OPP-WH-RESIZE": frozenset({"warehouse"}),
    "OPP-JOB-OVERLAP": frozenset({"job"}),
    "OPP-JOB-TIMEOUT": frozenset({"job"}),
    "OPP-JOB-FAILURE": frozenset({"job", "workspace"}),
    "OPP-JOB-WAIT-TASK": frozenset({"job"}),
    "OPP-SERVERLESS-STANDARD-MODE": frozenset({"job"}),
    "OPP-STEP-CHANGE": frozenset({"workspace"}),
    "OPP-DLT-CADENCE": frozenset({"pipeline"}),
    "OPP-CLUSTER-RIGHTSIZE": frozenset({"cluster", "job"}),
    "OPP-LAKEBASE": frozenset({"workspace"}),
    "OPP-PO": frozenset({"workspace"}),
}


def _target_kind(target: str) -> str:
    """``job:123`` → ``job``; ``workspace`` → ``workspace``."""
    return target.split(":", 1)[0]


def _verify_attempted(run_dir: Path, templates: tuple[str, ...]) -> bool:
    """True when any ``analysis/verify/<vt-id>*.json`` exists for one of ``templates``."""
    verify_dir = run_dir / "analysis" / "verify"
    if not verify_dir.is_dir():
        return False
    return any(next(verify_dir.glob(f"{vt}*.json"), None) is not None for vt in templates)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(subparsers) -> None:
    """Register the ``run`` domain and its subcommands."""
    p = subparsers.add_parser(
        "run",
        help="Validate an engagement run directory",
    )
    sp = p.add_subparsers(dest="command", required=True)

    chk = sp.add_parser(
        "check",
        help=(
            "Validate the §4 run checklist.  "
            "Exit 0 if all pass, exit 1 if any fail.  "
            "--out FILE also writes the envelope to FILE (e.g. analysis/run-check.json)."
        ),
    )
    chk.add_argument("run_dir", metavar="run-dir", help="Path to the run directory")
    chk.add_argument(
        "--internal",
        action="store_true",
        help=(
            "Also enforce item 12 (every deliverables/*.md and notebook has a .clean "
            "sibling) and item 16 (no sanitizer findings left in .clean prose)."
        ),
    )
    chk.add_argument(
        "--out",
        metavar="FILE",
        default=None,
        help=(
            "Write the envelope to FILE as well as stdout (parent dirs created). "
            "E.g. `run check \"$RUN_DIR\" --out \"$RUN_DIR/analysis/run-check.json\"`. "
            "The global --out flag works identically."
        ),
    )
    chk.set_defaults(func=cmd_check)

    rec = sp.add_parser(
        "recur",
        help=(
            "Recur beat: update the workspace trend history, write trend chart data + PNGs, "
            "the delta-vs-<prior-date>.md skeleton, and the README '## Recur' section."
        ),
    )
    rec.add_argument("run_dir", metavar="run-dir", help="Path to the current run directory")
    rec.add_argument(
        "--workspace-root",
        required=True,
        help="Workspace-level trend root, e.g. starboard-reports/<workspace> (holds trend/history.json)",
    )
    prior_grp = rec.add_mutually_exclusive_group()
    prior_grp.add_argument(
        "--prior",
        default=None,
        help=(
            "Prior run directory (default: auto-locate the newest older sibling run dir that has "
            "a findings-manifest.json — siblings under --workspace-root, or "
            "'<root-name>-YYYY-MM-DD*' dirs beside it; nothing else is scanned)"
        ),
    )
    prior_grp.add_argument(
        "--baseline",
        action="store_true",
        help="Record this run as the baseline: no prior lookup, no delta",
    )
    rec.set_defaults(func=cmd_recur)


# ---------------------------------------------------------------------------
# Command implementation
# ---------------------------------------------------------------------------


def cmd_check(args: Any) -> None:
    """Run the checklist; prints the envelope and exits — never returns normally."""
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        raise ArgError(f"run-dir not found or not a directory: {run_dir}")

    internal = bool(getattr(args, "internal", False))
    passed: list[str] = []
    failed: list[dict[str, str]] = []
    warnings: list[str] = []

    def _ok(item: str) -> None:
        passed.append(item)

    def _fail(item: str, reason: str) -> None:
        failed.append({"item": item, "reason": reason})

    # ------------------------------------------------------------------
    # Item 1: README.md must have ## Delivery and ## Recur sections
    # ------------------------------------------------------------------
    _check_readme_sections(run_dir, _ok, _fail)

    # ------------------------------------------------------------------
    # Item 2: discovery.json must contain data.facts
    # ------------------------------------------------------------------
    _check_discovery_facts(run_dir, _ok, _fail)

    # ------------------------------------------------------------------
    # Item 3: discovery/domains/ must have ≥3 .md files
    # ------------------------------------------------------------------
    item = "3:discovery/domains/ >=3 .md files"
    domains_dir = run_dir / "discovery" / "domains"
    domain_md = sorted(domains_dir.glob("*.md")) if domains_dir.is_dir() else []
    if len(domain_md) >= 3:
        _ok(item)
    else:
        _fail(item, f"found {len(domain_md)} file(s) in discovery/domains/; need >=3")

    # ------------------------------------------------------------------
    # Item 4: discovery/analysis.md must contain a line with "Grade"
    # ------------------------------------------------------------------
    item = "4:discovery/analysis.md has 'Grade'"
    analysis_md = run_dir / "discovery" / "analysis.md"
    if not analysis_md.is_file():
        _fail(item, "discovery/analysis.md not found")
    elif "Grade" in analysis_md.read_text(errors="replace"):
        _ok(item)
    else:
        _fail(item, "discovery/analysis.md present but contains no 'Grade' keyword")

    # ------------------------------------------------------------------
    # Item 5: analysis/verify/ .sql/.json pairs — every .sql has a .json,
    #          and count >= min(8, N_act_now_investigate from backlog)
    # ------------------------------------------------------------------
    _check_verify_pairs(run_dir, _ok, _fail, warnings)

    # ------------------------------------------------------------------
    # Item 6: analysis/backlog.json valid per §3
    # ------------------------------------------------------------------
    backlog_items: list[dict[str, Any]] | None = _check_backlog(run_dir, _ok, _fail, warnings)

    # ------------------------------------------------------------------
    # Item 7: analysis/action-plan.md exists
    # ------------------------------------------------------------------
    item = "7:analysis/action-plan.md"
    if (run_dir / "analysis" / "action-plan.md").is_file():
        _ok(item)
    else:
        _fail(item, "analysis/action-plan.md not found")

    # ------------------------------------------------------------------
    # Item 8: analysis/technical-review.md must have a ## Humanize section
    # ------------------------------------------------------------------
    item = "8:analysis/technical-review.md has '## Humanize'"
    tr = run_dir / "analysis" / "technical-review.md"
    if not tr.is_file():
        _fail(item, "analysis/technical-review.md not found")
    else:
        lines = tr.read_text(errors="replace").splitlines()
        if any(ln.strip() == "## Humanize" for ln in lines):
            _ok(item)
        else:
            _fail(item, "analysis/technical-review.md present but no '## Humanize' section found")

    # ------------------------------------------------------------------
    # Item 9: required deliverables (4 files)
    # ------------------------------------------------------------------
    item = "9:deliverables/ required files"
    required = [
        "exec-summary.md",
        "evidence-pack.md",
        "action-plan.md",
        "slack-post.md",
    ]
    missing = [n for n in required if not (run_dir / "deliverables" / n).is_file()]
    if missing:
        _fail(item, f"missing: {', '.join(missing)}")
    else:
        _ok(item)

    # ------------------------------------------------------------------
    # Item 10: one notebook per act_now/investigate backlog item
    # ------------------------------------------------------------------
    # Item 10 checks notebook coverage even when item 6 failed on another field, so a
    # missing notebook is reported by name rather than as "cannot verify".
    if backlog_items is None:
        backlog_items = _raw_backlog_items(run_dir)
    _check_notebooks(run_dir, backlog_items, _ok, _fail)

    # ------------------------------------------------------------------
    # Item 11: deliverables/charts/ must have ≥1 .png
    # ------------------------------------------------------------------
    item = "11:deliverables/charts/ >=1 .png"
    charts_dir = run_dir / "deliverables" / "charts"
    pngs = sorted(charts_dir.glob("*.png")) if charts_dir.is_dir() else []
    if pngs:
        _ok(item)
    else:
        _fail(item, "no .png files found in deliverables/charts/")

    # ------------------------------------------------------------------
    # Item 12: --internal only — .clean siblings for deliverables
    # ------------------------------------------------------------------
    item = "12:internal: .clean siblings for deliverables"
    if not internal:
        _ok(item)  # vacuously pass when not running in internal mode
    else:
        clean_errors = _check_clean_siblings(run_dir)
        if clean_errors:
            _fail(item, "; ".join(clean_errors))
        else:
            _ok(item)

    # ------------------------------------------------------------------
    # Item 13: findings-manifest.json (recurrence keystone) — both paths
    # ------------------------------------------------------------------
    _check_findings_manifest(run_dir, _ok, _fail)
    degraded_note = _degraded_review_warning(run_dir)
    if degraded_note:
        warnings.append(degraded_note)  # warn, never fail: a degraded review is still a review

    # ------------------------------------------------------------------
    # Item 14: every catalog id whose trigger fired is in items or cut
    # ------------------------------------------------------------------
    _check_catalog_coverage(run_dir, _ok, _fail)

    # ------------------------------------------------------------------
    # Item 15: analysis/recur-result.json ok (or baseline) + history entry
    # ------------------------------------------------------------------
    _check_recur_result(run_dir, _ok, _fail)

    # ------------------------------------------------------------------
    # Item 16: --internal only — .clean prose passes the sanitizer
    # ------------------------------------------------------------------
    item ="16:internal: .clean prose has no sanitizer findings"
    if not internal:
        _ok(item)  # vacuously pass when not running in internal mode
    else:
        san_errors = _check_clean_sanitized(run_dir, warnings)
        if san_errors:
            _fail(item, "; ".join(san_errors))
        else:
            _ok(item)

    # ------------------------------------------------------------------
    # Emit and exit
    # ------------------------------------------------------------------
    all_passed = not failed
    data: dict[str, Any] = {
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "summary": {
            "all_passed": all_passed,
            "total": len(passed) + len(failed),
            "pass_count": len(passed),
            "fail_count": len(failed),
            "run_dir": str(run_dir),
            "internal": internal,
        },
    }
    result = envelope(
        ok=all_passed,
        domain="run",
        command="check",
        data=data,
        meta=build_meta(getattr(args, "format", "json")),
    )
    text = json.dumps(result, indent=2, default=str)
    out = getattr(args, "out", None)
    if out:
        out_path = Path(out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n")
    print(text)
    sys.exit(EXIT_OK if all_passed else _EXIT_CHECK_FAILED)


# ---------------------------------------------------------------------------
# Per-item helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Delivery section content patterns (item 1)
# ---------------------------------------------------------------------------

#: A valid artifact entry line in '## Delivery' references a deliverables/ path, an
#: https:// URL, or records an explicit ``local:`` / ``not delivered:`` outcome.
_DELIVERY_ARTIFACT_RE = re.compile(
    r"deliverables/|https?://|local:|not\s+delivered:",
    re.IGNORECASE,
)

#: Placeholder text that indicates the section was not yet filled in.
_DELIVERY_PLACEHOLDER_RE = re.compile(
    r"\(filled at delivery\)|\bTBD\b|\bpending\b",
    re.IGNORECASE,
)


def _check_readme_sections(
    run_dir: Path,
    ok: Any,
    fail: Any,
) -> None:
    # No '## Run check' section is required: the check record is analysis/run-check.json
    # (`run check … --out`), which this item cannot validate from inside the run it checks.
    item = "1:README.md has '## Delivery' and '## Recur' sections"
    readme = run_dir / "README.md"
    if not readme.is_file():
        fail(item, "README.md not found")
        return
    lines = readme.read_text(errors="replace").splitlines()
    has_delivery = any(ln.strip() == "## Delivery" for ln in lines)
    has_recur = any(ln.strip() == "## Recur" for ln in lines)
    if has_delivery and has_recur:
        delivery_body = _section_body(lines, "## Delivery")
        if not any(_DELIVERY_ARTIFACT_RE.search(ln) for ln in delivery_body):
            if any(_DELIVERY_PLACEHOLDER_RE.search(ln) for ln in delivery_body):
                fail(
                    item,
                    "'## Delivery' section contains only placeholder text — replace with "
                    "actual delivery outcomes: reference a deliverables/ path, an https:// "
                    "URL, or write 'local: <reason>' / 'not delivered: <reason>' for each artifact",
                )
            else:
                fail(
                    item,
                    "'## Delivery' section has no artifact entries — add at least one line "
                    "that references a deliverables/ path, an https:// URL, or records the "
                    "outcome as 'local: <reason>' or 'not delivered: <reason>'",
                )
        elif not _section_body(lines, "## Recur"):
            fail(
                item,
                "'## Recur' section is empty — add the baseline note or the delta summary "
                "(`starboard-helper run recur` writes it)",
            )
        else:
            ok(item)
    else:
        missing = []
        if not has_delivery:
            missing.append("## Delivery")
        if not has_recur:
            missing.append("## Recur")
        fail(item, f"missing section(s): {', '.join(missing)}")


def _section_body(lines: list[str], heading: str) -> list[str]:
    """Return the non-blank lines under ``heading`` up to the next ``#``/``##`` heading."""
    body: list[str] = []
    inside = False
    for ln in lines:
        stripped = ln.strip()
        if stripped == heading:
            inside = True
            continue
        if inside:
            if re.match(r"^#{1,2}\s", stripped):
                break
            if stripped:
                body.append(stripped)
    return body


def _check_findings_manifest(
    run_dir: Path,
    ok: Any,
    fail: Any,
) -> None:
    item = "13:findings-manifest.json"
    path = run_dir / "findings-manifest.json"
    if not path.is_file():
        fail(
            item,
            "findings-manifest.json not found — run `starboard review … --json "
            "--manifest-out <run-dir>/findings-manifest.json` (--profile or --internal-workspace-id)",
        )
        return
    try:
        m = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        fail(item, f"findings-manifest.json parse error: {exc}")
        return
    if isinstance(m, dict) and isinstance(m.get("findings"), list):
        ok(item)
    else:
        fail(item, "findings-manifest.json present but has no 'findings' list")


def _check_discovery_facts(
    run_dir: Path,
    ok: Any,
    fail: Any,
) -> None:
    item = "2:discovery.json has data.facts"
    djson = _discovery_path(run_dir)
    if djson is None:
        fail(item, f"discovery.json not found (looked for {' and '.join(_DISCOVERY_PATHS)})")
        return
    rel = djson.relative_to(run_dir).as_posix()
    try:
        d = json.loads(djson.read_text())
    except Exception as exc:  # noqa: BLE001
        fail(item, f"{rel} parse error: {exc}")
        return
    if "facts" in ((d.get("data") if isinstance(d, dict) else None) or {}):
        ok(item)
    else:
        fail(item, f"{rel} present but data.facts is absent")


# Discovery envelope locations, in lookup order: the run-dir root copy, then the
# ``starboard --discover --out-dir <run-dir>/discovery`` output.
_DISCOVERY_PATHS = ("discovery.json", "discovery/discovery.json")


def _discovery_path(run_dir: Path) -> Path | None:
    for rel in _DISCOVERY_PATHS:
        p = run_dir / rel
        if p.is_file():
            return p
    return None


def _raw_backlog_items(run_dir: Path) -> list[dict[str, Any]] | None:
    """Parsed ``items`` list from backlog.json regardless of §3 validity, or None."""
    try:
        bl = json.loads((run_dir / "analysis" / "backlog.json").read_text())
    except Exception:  # noqa: BLE001
        return None
    items = bl.get("items") if isinstance(bl, dict) else None
    return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else None


def _count_backlog_act_investigate(run_dir: Path) -> int | None:
    """Return count of act_now+investigate items from backlog.json, or None if absent."""
    bl_path = run_dir / "analysis" / "backlog.json"
    if not bl_path.is_file():
        return None
    try:
        bl = json.loads(bl_path.read_text())
        return sum(
            1
            for it in bl.get("items", [])
            if it.get("tier") in ("act_now", "investigate")
        )
    except Exception:  # noqa: BLE001
        return None


def _verify_failed(path: Path) -> bool:
    """True when a verify ``.json`` records a failed statement (top-level ``ok: false``)."""
    try:
        doc = json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - unreadable is not a recorded failure; pairs only
        return False
    return isinstance(doc, dict) and doc.get("ok") is False


def _check_verify_pairs(
    run_dir: Path,
    ok: Any,
    fail: Any,
    warnings: list[str] | None = None,
) -> None:
    """Item 5: every ``.sql`` has a ``.json``; enough *successful* pairs; evidence is not all failures.

    A ``.json`` with ``ok: false`` (``verify run`` writes one when the statement fails) is
    recorded — the pair is complete — but it is not evidence: it does not count toward the
    minimum, and an act_now/investigate backlog item whose cited verify files are all
    ``ok: false`` fails this item.
    """
    item = "5:analysis/verify/ .sql/.json pairs (min count)"
    verify_dir = run_dir / "analysis" / "verify"
    sql_files = sorted(verify_dir.glob("*.sql")) if verify_dir.is_dir() else []

    unpaired = [sf.name for sf in sql_files if not sf.with_suffix(".json").is_file()]
    if unpaired:
        fail(item, f"unpaired .sql files (no matching .json): {', '.join(unpaired)}")
        return

    failed_json = [sf.with_suffix(".json").name for sf in sql_files if _verify_failed(sf.with_suffix(".json"))]
    if failed_json and warnings is not None:
        warnings.append(
            f"{len(failed_json)} verify result(s) recorded as failed (ok:false; not evidence — "
            f"re-run them): {', '.join(failed_json)}"
        )
    errors: list[str] = []
    n_ok = len(sql_files) - len(failed_json)
    n_act = _count_backlog_act_investigate(run_dir)
    min_pairs = min(8, n_act) if n_act is not None else 8
    if n_ok < min_pairs:
        errors.append(
            f"only {n_ok} successful .sql/.json pair(s); need >= {min_pairs}"
            + (f" (from backlog: {n_act} act_now/investigate items)" if n_act is not None else " (no backlog.json; defaulting to 8)")
            + (f"; {len(failed_json)} ok:false result(s) do not count" if failed_json else "")
        )

    for idx, it in enumerate(_raw_backlog_items(run_dir) or []):
        if it.get("tier") not in ("act_now", "investigate"):
            continue
        refs = [
            e for e in it.get("evidence") or []
            if isinstance(e, str) and "analysis/verify/" in e and e.endswith(".json") and (run_dir / e).is_file()
        ]
        if refs and all(_verify_failed(run_dir / e) for e in refs):
            errors.append(
                f"items[{idx}] ({it.get('id')} {it.get('target') or ''}".rstrip()
                + "): cites only failed verify results (ok:false), which are not evidence — "
                f"re-run and cite a successful result: {', '.join(refs)}"
            )

    if errors:
        fail(item, "; ".join(errors))
    else:
        ok(item)


def _check_perf_metric(prefix: str, bid: Any, sizing: dict[str, Any]) -> list[str]:
    """``sizing.metric``/``sizing.unit`` must match the catalog's canonical perf metric for the id."""
    metric, unit = sizing.get("metric"), sizing.get("unit")
    canonical = _PERF_METRICS.get(bid) if isinstance(bid, str) else None
    if canonical is not None:
        if (metric, unit) == canonical:
            return []
        fragment = json.dumps({"metric": canonical[0], "unit": canonical[1]})
        got = "missing" if metric is None and unit is None else f"metric={metric!r}, unit={unit!r}"
        return [
            f"{prefix} ({bid}): perf_metric sizing.metric/sizing.unit {got}; expected exactly "
            f'{fragment} inside "sizing" (catalog canonical perf metrics) — '
            "put any other figure in sizing.formula"
        ]
    if bid == "OPP-OTHER":
        if isinstance(metric, str) and metric.strip() and isinstance(unit, str) and unit.strip():
            return []
        return [f"{prefix} ({bid}): perf_metric needs a non-empty sizing.metric and sizing.unit"]
    return [
        f"{prefix} ({bid}): the catalog defines no perf_metric sizing for this id "
        f"(perf_metric ids: {', '.join(sorted(_PERF_METRICS))}, OPP-OTHER) — use the entry's sizing kind"
    ]


#: Hint appended to notebook-missing errors in items 6 and 10.
_NB_RENDER_HINT = (
    "run `starboard-helper notebook render …` "
    "(it now registers notebook paths into backlog.json by default)"
)


#: Confidence-rubric components (verify.md "Confidence rubric"): letter -> (max points, aliases).
_CONF_COMPONENTS: dict[str, tuple[int, tuple[str, ...]]] = {
    "V": (3, ("verified", "verified_live", "verify")),
    "R": (2, ("reconciled",)),
    "A": (2, ("attributed",)),
    "L": (1, ("lever", "lever_confirmed")),
    "S": (1, ("stable",)),
    "C": (1, ("caveat", "no_caveat", "no_open_caveat")),
}
_CONF_ALIASES = {alias: letter for letter, (_, names) in _CONF_COMPONENTS.items() for alias in names}
_CONF_STRING_RE = re.compile(r"\b([VRALSC])\s*=?\s*(\d+)\b")


def _check_confidence_breakdown(prefix: str, bid: Any, it: dict[str, Any], missing: list[str] | None) -> list[str]:
    """Validate the optional ``confidence_breakdown`` against ``confidence`` and the rubric maxima.

    Accepts an object (``{"verified": 3, "R": 2, ...}``) or the evidence-pack string
    (``"V3 R2 A2 L0 S1 C0"``).  Absent on an act_now/investigate item → warning only (older
    backlogs); present but malformed, over a component maximum, or not summing to ``confidence``
    (floor 1) → error.  Items lacking it are appended to ``missing`` (the caller emits one warning).
    """
    bd = it.get("confidence_breakdown")
    if bd is None:
        if it.get("tier") in ("act_now", "investigate") and missing is not None:
            missing.append(f"{prefix} ({bid})")
        return []
    points: dict[str, Any] = {}
    if isinstance(bd, str):
        points = {m.group(1): int(m.group(2)) for m in _CONF_STRING_RE.finditer(bd)}
        if not points:
            return [f"{prefix} ({bid}): confidence_breakdown string {bd!r} has no V/R/A/L/S/C<points> tokens"]
    elif isinstance(bd, dict):
        for key, val in bd.items():
            letter = str(key) if str(key) in _CONF_COMPONENTS else _CONF_ALIASES.get(str(key).lower())
            if letter is None:
                return [
                    f"{prefix} ({bid}): confidence_breakdown has unknown component {key!r} — use "
                    f"{', '.join(_CONF_COMPONENTS)} (or verified/reconciled/attributed/lever/stable/caveat)"
                ]
            points[letter] = val
    else:
        return [f"{prefix} ({bid}): confidence_breakdown must be an object or 'V3 R2 A2 L0 S1 C0' string"]
    errors: list[str] = []
    for letter, val in points.items():
        cap = _CONF_COMPONENTS[letter][0]
        if isinstance(val, bool) or not isinstance(val, int) or not (0 <= val <= cap):
            errors.append(f"{prefix} ({bid}): confidence_breakdown {letter}={val!r} must be an int 0..{cap}")
    if errors:
        return errors
    total = sum(points.values())
    conf = it.get("confidence")
    if isinstance(conf, int) and conf != max(1, total):
        return [
            f"{prefix} ({bid}): confidence {conf} != confidence_breakdown sum {total} "
            f"({' '.join(f'{k}{v}' for k, v in points.items())}) — the score is the rubric sum (min 1)"
        ]
    return []


def _validate_backlog(bl: Any, run_dir: Path, warnings: list[str] | None = None) -> list[str]:
    """Validate the backlog.json structure. Returns a list of error strings.

    Advisory findings (a Not-now item with no sized value — the catalog cut rule says that is a
    ``cut``) are appended to ``warnings`` when given.
    """
    errors: list[str] = []

    if not isinstance(bl, dict):
        return ["backlog.json must be a JSON object"]

    if not isinstance(bl.get("workspace_id"), str) or not bl["workspace_id"]:
        errors.append("workspace_id must be a non-empty string")
    if not isinstance(bl.get("generated_at"), str):
        errors.append("generated_at must be an ISO 8601 string")
    fw = bl.get("facts_window")
    if not isinstance(fw, dict) or "start" not in fw or "end" not in fw:
        errors.append("facts_window must be an object with 'start' and 'end'")
    # ``cut`` is optional (older backlogs predate it → treated as an empty list).
    cut = bl.get("cut", [])
    if not isinstance(cut, list):
        errors.append("cut must be a list of {id, reason} objects")
    else:
        for idx, c in enumerate(cut):
            if not isinstance(c, dict):
                errors.append(f"cut[{idx}]: must be an object with 'id' and 'reason'")
                continue
            cid = c.get("id")
            if not isinstance(cid, str) or not _OPP_ID_RE.match(cid):
                errors.append(f"cut[{idx}]: id must match ^OPP-[A-Z0-9-]+$, got {cid!r}")
            if not isinstance(c.get("reason"), str) or not c["reason"].strip():
                errors.append(f"cut[{idx}] ({cid}): reason must be a non-empty string")
            if c.get("rule") not in _VALID_CUT_RULES:
                errors.append(
                    f"cut[{idx}] ({cid}): rule must be one of {sorted(_VALID_CUT_RULES)}, "
                    f"got {c.get('rule')!r} (a real, sized signal below priority is a not_now item)"
                )
            if "target" in c and (not isinstance(c["target"], str) or not _TARGET_RE.match(c["target"])):
                errors.append(
                    f"cut[{idx}] ({cid}): target, when given, must be '<kind>:<id>' or 'workspace', "
                    f"got {c['target']!r}"
                )
            templates = _VERIFY_TEMPLATES.get(cid) if isinstance(cid, str) else None
            if c.get("rule") == "no_evidence" and templates and not _verify_attempted(run_dir, templates):
                label = f"{cid} {c.get('target') or ''}".rstrip()
                errors.append(
                    f"cut[{idx}] ({label}): rule no_evidence means the evidence is unavailable from the "
                    f"source, but none of its verify templates ({', '.join(templates)}) was attempted — "
                    "no analysis/verify/<vt-id>*.json (ok true or false). Run one (`verify run` records a "
                    "failure or timeout as ok:false) and cut only if it fails, or carry the id as an item; "
                    "the verify budget is not a reason to cut"
                )

    if not isinstance(bl.get("items"), list):
        errors.append("items must be a list")
        return errors

    seen_targets: set[tuple[Any, str]] = set()
    no_breakdown: list[str] = []
    for idx, it in enumerate(bl["items"]):
        prefix = f"items[{idx}]"
        if not isinstance(it, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        bid = it.get("id", f"<item {idx}>")

        raw_id = it.get("id", "")
        if not isinstance(raw_id, str) or not _OPP_ID_RE.match(raw_id):
            errors.append(f"{prefix}: id must match ^OPP-[A-Z0-9-]+$, got {raw_id!r}")

        if not isinstance(it.get("title"), str) or not it["title"]:
            errors.append(f"{prefix}: title must be a non-empty string")

        target = it.get("target")
        if not isinstance(target, str) or not _TARGET_RE.match(target):
            errors.append(
                f"{prefix} ({bid}): target is required — '<kind>:<raw id>' (job|warehouse|pipeline|cluster|"
                f"dashboard|genie|schema|endpoint|instance) or 'workspace', got {target!r}"
            )
        elif (bid, target) in seen_targets:
            errors.append(
                f"{prefix} ({bid}): duplicate (id, target) ({bid}, {target}) — one item per target"
            )
        else:
            seen_targets.add((bid, target))
            kinds = _TARGET_KINDS.get(bid) if isinstance(bid, str) else None
            if kinds and _target_kind(target) not in kinds:
                errors.append(
                    f"{prefix} ({bid}): target kind {_target_kind(target)!r} ({target}) is not allowed "
                    f"for this id — catalog Target kind: {', '.join(sorted(kinds))}"
                )

        tier = it.get("tier")
        if tier not in _VALID_TIERS:
            errors.append(
                f"{prefix}: tier must be one of {sorted(_VALID_TIERS)}, got {tier!r}"
            )

        conf = it.get("confidence")
        if not isinstance(conf, int) or not (1 <= conf <= 10):
            errors.append(
                f"{prefix}: confidence must be an int 1..10, got {conf!r}"
            )

        errors.extend(_check_confidence_breakdown(prefix, bid, it, no_breakdown))

        sizing = it.get("sizing")
        if not isinstance(sizing, dict):
            errors.append(f"{prefix}: sizing must be an object")
        else:
            if sizing.get("kind") not in _VALID_SIZING_KINDS:
                errors.append(
                    f"{prefix}: sizing.kind must be one of {sorted(_VALID_SIZING_KINDS)}, got {sizing.get('kind')!r}"
                )
            if "formula" not in sizing:
                errors.append(f"{prefix}: sizing.formula is required")
            value = sizing.get("value")
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                errors.append(
                    f"{prefix} ({bid}): sizing.value must be a number or null, got {value!r} — "
                    "put the number in sizing.value, the unit in sizing.unit, and any prose in "
                    "sizing.formula"
                )
            unit = sizing.get("unit")
            if unit is not None and not isinstance(unit, str):
                errors.append(f"{prefix} ({bid}): sizing.unit must be a string or null, got {unit!r}")
            if sizing.get("kind") == "perf_metric":
                errors.extend(_check_perf_metric(prefix, bid, sizing))
            if tier == "not_now" and value is None and warnings is not None:
                warnings.append(
                    f"{prefix} ({bid}): not_now with no sized value — per the catalog cut rule an "
                    "unsized fired id belongs in cut[] (rule disqualifier/no_evidence)"
                )

        evidence = it.get("evidence", [])
        if not isinstance(evidence, list):
            errors.append(f"{prefix}: evidence must be a list")
        elif tier in ("act_now", "investigate"):
            verify_refs = [
                e
                for e in evidence
                if isinstance(e, str)
                and "analysis/verify/" in e
                and e.endswith(".json")
            ]
            if not verify_refs:
                errors.append(
                    f"{prefix} ({bid}): act_now/investigate needs >=1 evidence entry"
                    " referencing an analysis/verify/*.json file"
                )
            else:
                for ref in verify_refs:
                    if not (run_dir / ref).is_file():
                        errors.append(
                            f"{prefix} ({bid}): evidence file not found: {ref}"
                        )

        if not isinstance(it.get("lever"), str):
            errors.append(f"{prefix}: lever must be a string")

        nb = it.get("notebook")
        if tier in ("act_now", "investigate"):
            if not nb:
                errors.append(
                    f"{prefix} ({bid}): notebook is required for {tier} items — "
                    + _NB_RENDER_HINT
                )
            elif not (run_dir / nb).is_file():
                errors.append(
                    f"{prefix} ({bid}): notebook path not found: {nb} — "
                    + _NB_RENDER_HINT
                )

    if no_breakdown and warnings is not None:
        warnings.append(
            f"{len(no_breakdown)} act_now/investigate item(s) lack confidence_breakdown "
            f"({', '.join(no_breakdown[:3])}{', …' if len(no_breakdown) > 3 else ''}) — add the rubric "
            'components, e.g. "confidence_breakdown": {"V": 3, "R": 2, "A": 2, "L": 0, "S": 1, "C": 0}, '
            "so confidence is a rubric sum (verify.md confidence rubric)"
        )

    return errors


def _check_backlog(
    run_dir: Path,
    ok: Any,
    fail: Any,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]] | None:
    """Check item 6.  Returns parsed items list on success, None on failure."""
    item = "6:analysis/backlog.json valid per §3"
    bl_path = run_dir / "analysis" / "backlog.json"
    if not bl_path.is_file():
        fail(item, "analysis/backlog.json not found")
        return None
    try:
        bl = json.loads(bl_path.read_text())
    except Exception as exc:  # noqa: BLE001
        fail(item, f"parse error: {exc}")
        return None

    errs = _validate_backlog(bl, run_dir, warnings)
    if errs:
        fail(item, "; ".join(errs))
        return None

    ok(item)
    return bl.get("items", [])


def _check_notebooks(
    run_dir: Path,
    backlog_items: list[dict[str, Any]] | None,
    ok: Any,
    fail: Any,
) -> None:
    item = "10:one notebook per Act-now/Investigate item (Not-now needs none)"
    if backlog_items is None:
        fail(item, "cannot verify notebook coverage — analysis/backlog.json absent or invalid")
        return

    nb_errors: list[str] = []
    for bi in backlog_items:
        tier = bi.get("tier", "")
        if tier not in ("act_now", "investigate"):
            continue
        nb = bi.get("notebook")
        bid = bi.get("id", "?")
        if not nb:
            nb_errors.append(f"{bid}: notebook field is null/absent — {_NB_RENDER_HINT}")
        elif not (run_dir / nb).is_file():
            nb_errors.append(f"{bid}: notebook path not found: {nb} — {_NB_RENDER_HINT}")

    if nb_errors:
        fail(item, "; ".join(nb_errors))
    else:
        ok(item)


def _check_clean_siblings(run_dir: Path) -> list[str]:
    """Return error strings for any missing .clean siblings (item 12, --internal)."""
    errors: list[str] = []

    deliv = run_dir / "deliverables"
    if not deliv.is_dir():
        return ["deliverables/ missing — see item 9"]

    # Top-level .md files (skip .clean. files and .doc. intermediate files)
    for md_file in sorted(deliv.glob("*.md")):
        name = md_file.name
        if ".clean." in name or name.endswith(".doc.md"):
            continue
        stem = md_file.stem  # e.g. "action-plan" from "action-plan.md"
        clean_name = f"{stem}.clean.md"
        if not (deliv / clean_name).is_file():
            errors.append(f"deliverables/{name}: missing .clean sibling ({clean_name})")

    if not any(deliv.glob("*.md")):
        errors.append("deliverables/ has no .md files — see item 9")

    # Notebooks
    nb_dir = deliv / "notebooks"
    if nb_dir.is_dir():
        for nb_file in sorted(nb_dir.glob("*.py")):
            name = nb_file.name
            if ".clean." in name:
                continue
            stem = nb_file.stem
            clean_name = f"{stem}.clean.py"
            if not (nb_dir / clean_name).is_file():
                errors.append(
                    f"deliverables/notebooks/{name}: missing .clean sibling ({clean_name})"
                )

    return errors


# ---------------------------------------------------------------------------
# Item 14 — catalog coverage: every fired trigger is carried or cut
# ---------------------------------------------------------------------------


def _num(v: Any) -> float | None:
    """Pack cells arrive as strings ("45.40"); coerce to float, None when not numeric."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rows_by_query(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Rows keyed by query id from ``data.packs[].results[]`` (and a legacy flat ``data.queries[]``)."""
    results: list[Any] = []
    for pack in data.get("packs") or []:
        if isinstance(pack, dict):
            results.extend(pack.get("results") or [])
    results.extend(data.get("queries") or [])
    out: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        if not isinstance(r, dict) or not isinstance(r.get("query_id"), str):
            continue
        rows = r.get("rows")
        out.setdefault(r["query_id"], []).extend(
            row for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict)
        )
    return out


def _any_row(rows: dict[str, list[dict[str, Any]]], qids: tuple[str, ...], pred: Callable[[dict[str, Any]], bool]) -> bool:
    return any(pred(row) for q in qids for row in rows.get(q, []))


def _ge(row: dict[str, Any], col: str, threshold: float) -> bool:
    v = _num(row.get(col))
    return v is not None and v >= threshold


def _mix_dbus(facts: dict[str, Any], product: str) -> float:
    for m in facts.get("product_mix") or []:
        if isinstance(m, dict) and str(m.get("product", "")).upper() == product:
            return _num(m.get("dbus")) or 0.0
    return 0.0


def _sub(facts: dict[str, Any], key: str) -> dict[str, Any]:
    v = facts.get(key)
    return v if isinstance(v, dict) else {}


_WAIT_TASK_RE = re.compile(r"wait|poll|sensor|readiness", re.IGNORECASE)
_OVERSIZED_RE = re.compile(r"OVERPROVISIONED|OVERSIZED", re.IGNORECASE)

_Facts = dict[str, Any]
_Rows = dict[str, list[dict[str, Any]]]

#: Catalog trigger map for item 14 (A1).  ``(catalog id, trigger description, predicate)``;
#: the predicate reads ``data.facts`` and the pack rows keyed by query id, and is True when the
#: id's trigger fired in this run's discovery envelope.  Thresholds mirror the ``Trigger`` row of
#: each entry in ``starboard-action-plan/references/opportunity-catalog.md`` (deliberately the
#: simple, mechanical part only — the host still applies the disqualifiers and the tier rule):
#:
#: =============================  ==========================================================
#: OPP-WH-QUEUE                   W-W01 queued_query_pct >= 10 or avg_capacity_wait_secs >= 10
#:                                on a warehouse with total_queries >= 1000
#: OPP-WH-IDLE                    W-W02 auto_stop_waste_pct >= 20 with est_idle_dbus not null;
#:                                or any C-C02 row
#: OPP-WH-CLASSIC-TO-SERVERLESS   facts.warehouses.classic_dbus >= 1% of facts.total.dbus
#: OPP-WH-SCAN                    W-W06 pct_of_warehouse_duration >= 30; or C-Q02 read_gb >= 1000
#: OPP-WH-RESIZE                  facts.recent_config_changes non-empty
#: OPP-JOB-OVERLAP                C-J08 runs_started_while_running >= 10% of total_runs and
#:                                max_concurrent_runs >= 2
#: OPP-JOB-TIMEOUT                C-J03 max_runtime_mins >= 3 x avg_runtime_mins (avg > 0)
#: OPP-JOB-FAILURE                C-J04 failure_dbus > 0; or facts.job_reliability.failure_rate_pct > 0
#: OPP-JOB-WAIT-TASK              C-J09 / P-WF01 task_key contains wait|poll|sensor|readiness
#: OPP-SERVERLESS-STANDARD-MODE   facts.performance_mode.performance_optimized_pct >= 50
#: OPP-STEP-CHANGE                facts.step_change not null
#: OPP-DLT-CADENCE                facts.top_pipelines non-empty
#: OPP-CLUSTER-RIGHTSIZE          CRS-01 / CRS-06 sizing_reason or sizing_direction names
#:                                OVERPROVISIONED/OVERSIZED; or any C-C02 row
#: OPP-LAKEBASE                   facts.product_mix LAKEBASE dbus > 0; or any P-LB01 / P-LB04 row
#: OPP-PO                         facts.product_mix PREDICTIVE_OPTIMIZATION dbus > 0; or any PO-01 row
#: =============================  ==========================================================
#:
#: A fired id must appear in backlog ``items`` (any tier) or in backlog ``cut`` with a reason.
_CATALOG_TRIGGERS: tuple[tuple[str, str, Callable[[_Facts, _Rows], bool]], ...] = (
    (
        "OPP-WH-QUEUE",
        "W-W01 queued_query_pct>=10 or avg_capacity_wait_secs>=10 with total_queries>=1000",
        lambda _f, r: _any_row(
            r, ("W-W01",),
            lambda x: _ge(x, "total_queries", 1000)
            and (_ge(x, "queued_query_pct", 10) or _ge(x, "avg_capacity_wait_secs", 10)),
        ),
    ),
    (
        "OPP-WH-IDLE",
        "W-W02 auto_stop_waste_pct>=20 with est_idle_dbus, or a C-C02 row",
        lambda _f, r: _any_row(
            r, ("W-W02",),
            lambda x: _ge(x, "auto_stop_waste_pct", 20) and _num(x.get("est_idle_dbus")) is not None,
        ) or bool(r.get("C-C02")),
    ),
    (
        "OPP-WH-CLASSIC-TO-SERVERLESS",
        "facts.warehouses.classic_dbus >= 1% of facts.total.dbus",
        lambda f, _r: (_num(_sub(f, "warehouses").get("classic_dbus")) or 0.0) > 0
        and (_num(_sub(f, "warehouses").get("classic_dbus")) or 0.0)
        >= 0.01 * (_num(_sub(f, "total").get("dbus")) or 0.0),
    ),
    (
        "OPP-WH-SCAN",
        "W-W06 pct_of_warehouse_duration>=30 or C-Q02 read_gb>=1000",
        lambda _f, r: _any_row(r, ("W-W06",), lambda x: _ge(x, "pct_of_warehouse_duration", 30))
        or _any_row(r, ("C-Q02",), lambda x: _ge(x, "read_gb", 1000)),
    ),
    (
        "OPP-WH-RESIZE",
        "facts.recent_config_changes non-empty",
        lambda f, _r: bool(f.get("recent_config_changes")),
    ),
    (
        "OPP-JOB-OVERLAP",
        "C-J08 runs_started_while_running>=10% of total_runs and max_concurrent_runs>=2",
        lambda _f, r: _any_row(
            r, ("C-J08",),
            lambda x: _ge(x, "max_concurrent_runs", 2)
            and (_num(x.get("total_runs")) or 0) > 0
            and (_num(x.get("runs_started_while_running")) or 0) >= 0.1 * (_num(x.get("total_runs")) or 0),
        ),
    ),
    (
        "OPP-JOB-TIMEOUT",
        "C-J03 max_runtime_mins >= 3 x avg_runtime_mins",
        lambda _f, r: _any_row(
            r, ("C-J03",),
            lambda x: (_num(x.get("avg_runtime_mins")) or 0) > 0
            and (_num(x.get("max_runtime_mins")) or 0) >= 3 * (_num(x.get("avg_runtime_mins")) or 0),
        ),
    ),
    (
        "OPP-JOB-FAILURE",
        "C-J04 failure_dbus>0 or facts.job_reliability.failure_rate_pct>0",
        lambda f, r: _any_row(r, ("C-J04",), lambda x: (_num(x.get("failure_dbus")) or 0) > 0)
        or (_num(_sub(f, "job_reliability").get("failure_rate_pct")) or 0) > 0,
    ),
    (
        "OPP-JOB-WAIT-TASK",
        "C-J09/P-WF01 task_key contains wait|poll|sensor|readiness",
        lambda _f, r: _any_row(
            r, ("C-J09", "P-WF01"), lambda x: bool(_WAIT_TASK_RE.search(str(x.get("task_key") or "")))
        ),
    ),
    (
        "OPP-SERVERLESS-STANDARD-MODE",
        "facts.performance_mode.performance_optimized_pct>=50",
        lambda f, _r: (_num(_sub(f, "performance_mode").get("performance_optimized_pct")) or 0) >= 50,
    ),
    (
        "OPP-STEP-CHANGE",
        "facts.step_change not null",
        lambda f, _r: bool(f.get("step_change")),
    ),
    (
        "OPP-DLT-CADENCE",
        "facts.top_pipelines non-empty",
        lambda f, _r: bool(f.get("top_pipelines")),
    ),
    (
        "OPP-CLUSTER-RIGHTSIZE",
        "CRS-01/CRS-06 sizing_reason|sizing_direction OVERPROVISIONED/OVERSIZED, or a C-C02 row",
        lambda _f, r: _any_row(
            r, ("CRS-01", "CRS-06"),
            lambda x: bool(
                _OVERSIZED_RE.search(f"{x.get('sizing_reason') or ''} {x.get('sizing_direction') or ''}")
            ),
        ) or bool(r.get("C-C02")),
    ),
    (
        "OPP-LAKEBASE",
        "facts.product_mix LAKEBASE dbus>0 or a P-LB01/P-LB04 row",
        lambda f, r: _mix_dbus(f, "LAKEBASE") > 0 or bool(r.get("P-LB01")) or bool(r.get("P-LB04")),
    ),
    (
        "OPP-PO",
        "facts.product_mix PREDICTIVE_OPTIMIZATION dbus>0 or a PO-01 row",
        lambda f, r: _mix_dbus(f, "PREDICTIVE_OPTIMIZATION") > 0 or bool(r.get("PO-01")),
    ),
)


def _fired_triggers(envelope_doc: Any) -> list[tuple[str, str]]:
    """``[(catalog id, trigger description)]`` for every trigger that fired in the envelope."""
    data = envelope_doc.get("data") if isinstance(envelope_doc, dict) else None
    if not isinstance(data, dict):
        return []
    raw_facts = data.get("facts")
    facts: dict[str, Any] = raw_facts if isinstance(raw_facts, dict) else {}
    rows = _rows_by_query(data)
    fired: list[tuple[str, str]] = []
    for opp_id, desc, pred in _CATALOG_TRIGGERS:
        try:
            hit = pred(facts, rows)
        except Exception:  # noqa: BLE001 - a malformed cell never fires a trigger
            hit = False
        if hit:
            fired.append((opp_id, desc))
    return fired


def _check_catalog_coverage(run_dir: Path, ok: Any, fail: Any) -> None:
    item = "14:backlog carries or cuts every fired catalog trigger"
    djson = _discovery_path(run_dir)
    if djson is None:
        fail(item, "cannot verify catalog coverage — discovery.json not found")
        return
    try:
        doc = json.loads(djson.read_text())
        bl = json.loads((run_dir / "analysis" / "backlog.json").read_text())
    except Exception as exc:  # noqa: BLE001
        fail(item, f"cannot verify catalog coverage — discovery.json/backlog.json unreadable: {exc}")
        return
    if not isinstance(bl, dict):
        fail(item, "cannot verify catalog coverage — backlog.json is not an object")
        return
    covered: set[Any] = set()
    for key in ("items", "cut"):
        entries = bl.get(key)
        if isinstance(entries, list):
            covered.update(e.get("id") for e in entries if isinstance(e, dict))
    missing = [f"{opp_id} ({desc})" for opp_id, desc in _fired_triggers(doc) if opp_id not in covered]
    if missing:
        fail(
            item,
            "trigger fired but id is in neither backlog items nor cut[{id, reason}]: "
            + "; ".join(missing),
        )
    else:
        ok(item)


# ---------------------------------------------------------------------------
# Item 15 — recur outcome
# ---------------------------------------------------------------------------


def _check_recur_result(run_dir: Path, ok: Any, fail: Any) -> None:
    item = "15:analysis/recur-result.json ok + history entry"
    path = run_dir / _RECUR_RESULT
    if not path.is_file():
        fail(
            item,
            f"{_RECUR_RESULT} not found — run `starboard-helper run recur <run-dir> "
            "--workspace-root <dir> [--prior <dir> | --baseline]`",
        )
        return
    try:
        rr = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        fail(item, f"{_RECUR_RESULT} parse error: {exc}")
        return
    if not isinstance(rr, dict):
        fail(item, f"{_RECUR_RESULT} must be a JSON object")
        return
    errors = rr.get("errors") or ([rr["error"]] if rr.get("error") else [])
    if not (rr.get("ok") is True or (rr.get("baseline") is True and not errors)):
        fail(item, f"recur did not succeed (ok={rr.get('ok')!r}): {'; '.join(map(str, errors)) or 'no errors recorded'}")
        return
    entry = rr.get("history_entry")
    hist_raw = rr.get("history_path")
    if not isinstance(entry, dict) or not isinstance(hist_raw, str):
        fail(item, f"{_RECUR_RESULT} lacks history_path/history_entry")
        return
    hist_path = Path(hist_raw)
    if not hist_path.is_absolute():
        hist_path = run_dir / hist_path
    try:
        history = json.loads(hist_path.read_text())
    except Exception as exc:  # noqa: BLE001
        fail(item, f"trend history unreadable at {hist_path}: {exc}")
        return
    found = isinstance(history, list) and any(
        isinstance(h, dict)
        and h.get("run_date") == entry.get("run_date")
        and h.get("run", run_dir.name) == run_dir.name
        for h in history
    )
    if found:
        ok(item)
    else:
        fail(item, f"no trend history entry for this run ({entry.get('run_date')}, {run_dir.name}) in {hist_path}")


# ---------------------------------------------------------------------------
# Item 16 — sanitizer findings left in .clean files (--internal)
# ---------------------------------------------------------------------------

#: Generic fallback when the internal sanitizer is not installed: the customer-confusing
#: wording it flags.  The concrete denylist lives only in the internal package.
_FALLBACK_SANITIZE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mirror", re.compile(r"\bmirror\b", re.IGNORECASE)),
)
_INTERNAL_PKG = "starboard_internal"
_CODE_CLEAN_SUFFIXES = frozenset({".py", ".sql", ".ipynb", ".scala", ".r"})


def _internal_sanitizer_available() -> bool:
    """Locate (never import) the internal package — keeps the import-linter contract KEPT."""
    import importlib.util

    try:
        return importlib.util.find_spec(_INTERNAL_PKG) is not None
    except (ImportError, ValueError):
        return False


def _sanitizer_findings(path: Path) -> list[str]:
    """Tokens the internal sanitizer CLI would still strip or warn on for ``path``.

    Runs ``python -m <internal>.sanitize --in <path>`` out of process (stdout discarded) and
    parses its stderr report; code mode is chosen by the CLI from the file suffix.
    """
    proc = subprocess.run(
        [sys.executable, "-m", f"{_INTERNAL_PKG}.sanitize", "--in", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        return [f"sanitizer error (exit {proc.returncode}): {proc.stderr.strip()[:200]}"]
    found: list[str] = []
    for line in proc.stderr.splitlines():
        for marker in ("stripped internal provenance -> ", "warnings (review suggested): "):
            if marker in line:
                found.extend(t.strip() for t in line.split(marker, 1)[1].split(",") if t.strip())
    return list(dict.fromkeys(found))


def _check_clean_sanitized(run_dir: Path, warnings: list[str]) -> list[str]:
    """Item 16: prose ``.clean`` deliverables must sanitize to a no-op with no warnings.

    Code ``.clean`` files (notebooks/SQL) are reported in ``warnings`` only.
    """
    deliv = run_dir / "deliverables"
    files = sorted(p for p in deliv.rglob("*") if p.is_file() and ".clean." in p.name) if deliv.is_dir() else []
    if not files:
        return ["deliverables/ missing — see item 9 (no .clean files to sanitize)"]
    use_cli = _internal_sanitizer_available()
    if not use_cli:
        warnings.append("internal sanitizer not installed — item 16 checked generic wording only")
    errors: list[str] = []
    for p in files:
        rel = p.relative_to(run_dir).as_posix()
        if use_cli:
            found = _sanitizer_findings(p)
        else:
            text = p.read_text(errors="replace")
            found = [name for name, pat in _FALLBACK_SANITIZE_PATTERNS if pat.search(text)]
        if not found:
            continue
        msg = f"{rel}: {', '.join(found)}"
        if p.suffix.lower() in _CODE_CLEAN_SUFFIXES:
            warnings.append(f"sanitizer (code, warn-only) {msg}")
        else:
            errors.append(msg)
    return errors


# ---------------------------------------------------------------------------
# run recur — deterministic recur beat (stdlib-only; charts render is optional)
# ---------------------------------------------------------------------------

_MANIFEST_NAME = "findings-manifest.json"
_RECUR_RESULT = "analysis/recur-result.json"
_BACKLOG_TIERS = ("act_now", "investigate", "not_now")
_TIER_RANK = {t: i for i, t in enumerate(_BACKLOG_TIERS)}
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_TREND_SEVERITIES = ("critical", "high", "medium")
_TREND_CHARTS = ("spend-over-time", "finding-count-over-time")
_DELTA_PLACEHOLDER = "_Analyst: what changed, why, and what to do next (replace this line)._"
# cost_delta classes in the order the delta narrative presents them.
_DELTA_CLASSES: tuple[tuple[str, str], ...] = (
    ("improved", "Improved"),
    ("regressed", "Regressed"),
    ("newly_expensive", "Newly expensive"),
    ("persisting", "Persisting"),
    ("new_low_cost", "New (low-cost)"),
)


def _names(v: Any) -> list[str]:
    """``unavailable_queries``/``unavailable_domains`` as a sorted list of names.

    Accepts a list of strings, a list of ``{"query_id"|"domain"|"id": …}`` objects, or a
    ``{name: reason}`` mapping; anything else → ``[]``.
    """
    if isinstance(v, dict):
        return sorted(str(k) for k in v)
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for e in v:
        if isinstance(e, str):
            out.append(e)
        elif isinstance(e, dict):
            name = e.get("query_id") or e.get("domain") or e.get("id")
            if isinstance(name, str):
                out.append(name)
    return sorted(dict.fromkeys(out))


def _review_coverage(manifest: dict[str, Any]) -> dict[str, Any]:
    """Review coverage from a findings manifest: ``degraded`` (None when the manifest predates the
    key), ``unavailable_queries``, ``unavailable_domains``.  A manifest that lists unavailable
    domains/queries but no ``degraded`` flag counts as degraded."""
    queries = _names(manifest.get("unavailable_queries"))
    domains = _names(manifest.get("unavailable_domains"))
    raw = manifest.get("degraded")
    degraded: bool | None = bool(raw) if raw is not None else (True if queries or domains else None)
    return {"degraded": degraded, "unavailable_queries": queries, "unavailable_domains": domains}


def _degraded_review_warning(run_dir: Path) -> str | None:
    """A warning when this run's review is degraded (manifest flag, else ``analysis/review.json``)."""
    cov: dict[str, Any] | None = None
    try:
        m = json.loads((run_dir / _MANIFEST_NAME).read_text())
        if isinstance(m, dict):
            cov = _review_coverage(m)
    except Exception:  # noqa: BLE001 - item 13 reports the manifest itself
        cov = None
    if cov is None or cov["degraded"] is None:
        try:
            review = json.loads((run_dir / "analysis" / "review.json").read_text())
        except Exception:  # noqa: BLE001
            review = None
        holder = review.get("data") if isinstance(review, dict) and isinstance(review.get("data"), dict) else review
        if isinstance(holder, dict) and holder.get("degraded") is not None:
            cov = _review_coverage(holder)
            # Saved review output names degraded domains per domain report, not top-level lists.
            reports = [r for r in holder.get("domain_reports") or [] if isinstance(r, dict) and r.get("degraded")]
            if reports and not cov["unavailable_domains"]:
                cov["unavailable_domains"] = sorted({str(r.get("domain")) for r in reports})
            if reports and not cov["unavailable_queries"]:
                cov["unavailable_queries"] = sorted({
                    q.strip()
                    for r in reports
                    for q in str(r.get("degraded_reason") or "").partition(":")[2].split(",")
                    if q.strip()
                })
    if not cov or not cov["degraded"]:
        return None
    domains = ", ".join(cov["unavailable_domains"]) or "unnamed"
    return (
        f"review degraded: unavailable domains {domains}; {len(cov['unavailable_queries'])} evidence "
        "query(ies) unavailable — finding counts are partial; recur marks these domains not comparable"
    )


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        raise ArgError(f"{label} is not valid JSON ({path}): {exc}") from exc


def _run_date_of(run_dir: Path, manifest: dict[str, Any]) -> str:
    """The run date: manifest ``run_date``, else the date in the dir name, else today (UTC)."""
    rd = manifest.get("run_date")
    if isinstance(rd, str) and _DATE_RE.fullmatch(rd[:10]):
        return rd[:10]
    m = _DATE_RE.search(run_dir.name)
    if m:
        return m.group(1)
    from datetime import UTC, datetime

    return datetime.now(UTC).date().isoformat()


def _locate_prior(run_dir: Path, workspace_root: Path, current_key: tuple[str, str]) -> Path | None:
    """Newest OTHER sibling run dir of ``run_dir`` that has a findings-manifest.json and is older
    than the current run.  The current run is excluded.  Only ``run_dir``'s own parent is listed
    (never recursively), and only in one of two layouts:

    * nested — the run dir sits under ``workspace_root`` (e.g. ``<root>/<run>``): any sibling;
    * flat — the run dir sits beside ``workspace_root`` (``starboard-reports/ws-1`` +
      ``starboard-reports/ws-1-2026-10-01``): only siblings named ``<root-name>-YYYY-MM-DD…``.

    Any other placement → no auto-locate (baseline unless ``--prior`` is given).
    """
    parent = run_dir.parent
    nested = parent == workspace_root or workspace_root in parent.parents
    flat = parent == workspace_root.parent
    if not (nested or flat) or not parent.is_dir():
        return None
    pattern = re.compile(rf"^{re.escape(workspace_root.name)}-\d{{4}}-\d{{2}}-\d{{2}}")
    best: tuple[tuple[str, str], Path] | None = None
    for cand in parent.iterdir():
        if not cand.is_dir() or (not nested and not pattern.match(cand.name)):
            continue
        if cand.resolve() == run_dir:
            continue
        mpath = cand / _MANIFEST_NAME
        if not mpath.is_file():
            continue
        try:
            cm = json.loads(mpath.read_text())
        except Exception:  # noqa: BLE001 - an unreadable prior is skipped, not fatal
            continue
        key = (_run_date_of(cand, cm if isinstance(cm, dict) else {}), cand.name)
        if key >= current_key:
            continue
        if best is None or key > best[0]:
            best = (key, cand)
    return best[1].resolve() if best else None


def _history_entry(
    run_date: str, manifest: dict[str, Any], run_dir: Path
) -> tuple[dict[str, Any], str]:
    """Build the trend entry from a manifest (+ the run's backlog tier counts and per-item
    sizing); returns (entry, total_dbu_source).  ``act_now``/``investigate``/``not_now`` and
    ``backlog_items`` are null when the run has no readable ``analysis/backlog.json``."""
    findings = [f for f in manifest.get("findings") or [] if isinstance(f, dict)]
    products = manifest.get("products_dbu") or {}
    total: float | None
    if isinstance(products, dict) and products:
        total = round(sum(float(v) for v in products.values() if isinstance(v, (int, float))), 4)
        source = "products_dbu"
    else:
        dbus = [
            float(f["evidence_dbu_estimate"])
            for f in findings
            if isinstance(f.get("evidence_dbu_estimate"), (int, float))
        ]
        total = round(sum(dbus), 4) if dbus else None
        source = "finding_evidence_dbu" if dbus else "none"
    sev = [str(f.get("severity", "")).lower() for f in findings]
    bl = _read_backlog(run_dir)
    tiers = [it.get("tier") for it in bl.get("items") or [] if isinstance(it, dict)] if bl else None
    entry = {
        "run_date": run_date,
        "run": run_dir.name,
        "total_dbu_estimate": total,
        "finding_count": len(findings),
        "critical": sev.count("critical"),
        "high": sev.count("high"),
        "medium": sev.count("medium"),
        **{t: (tiers.count(t) if tiers is not None else None) for t in _BACKLOG_TIERS},
        "backlog_items": _backlog_items_sizing(bl) if bl else None,
        **_review_coverage(manifest),
        "coverage_note": manifest.get("coverage_note") if isinstance(manifest.get("coverage_note"), str) else None,
    }
    return entry, source


def _read_backlog(run_dir: Path) -> dict[str, Any] | None:
    """``analysis/backlog.json`` as a dict, or None when absent/unreadable (never raises)."""
    try:
        bl = json.loads((run_dir / "analysis" / "backlog.json").read_text())
    except Exception:  # noqa: BLE001
        return None
    return bl if isinstance(bl, dict) else None


def _backlog_items_sizing(bl: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-item sizing records ``[{id, target, tier, sizing_metric, value, unit}]`` (primary trend)."""
    out: list[dict[str, Any]] = []
    for it in bl.get("items") or []:
        if not isinstance(it, dict) or not isinstance(it.get("id"), str):
            continue
        raw_sizing = it.get("sizing")
        sizing: dict[str, Any] = raw_sizing if isinstance(raw_sizing, dict) else {}
        value = sizing.get("value")
        out.append({
            "id": it["id"],
            "target": it.get("target") if isinstance(it.get("target"), str) else None,
            "tier": it.get("tier"),
            "sizing_metric": sizing.get("metric") if isinstance(sizing.get("metric"), str) else sizing.get("kind"),
            "value": value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
            "unit": sizing.get("unit") if isinstance(sizing.get("unit"), str) else None,
        })
    return sorted(out, key=lambda r: (r["id"], r["target"] or ""))


def _backlog_sizing_delta(
    current: list[dict[str, Any]], prior: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Per-(id, target) sizing rows: prior value → current value, unit, Δ, status.

    Δ is only computed when both values are numbers on the same sizing metric and unit;
    otherwise ``delta`` is null and ``status`` says why.
    """
    def _key(r: dict[str, Any]) -> tuple[str, str]:
        return (r["id"], r.get("target") or "")

    cur = {_key(r): r for r in current}
    pri = {_key(r): r for r in prior}
    rows: list[dict[str, Any]] = []
    for key in sorted(set(cur) | set(pri)):
        c, p = cur.get(key), pri.get(key)
        ref = c or p or {}
        row: dict[str, Any] = {
            "id": key[0],
            "target": key[1] or None,
            "prior_tier": p.get("tier") if p else None,
            "current_tier": c.get("tier") if c else None,
            "sizing_metric": ref.get("sizing_metric"),
            "unit": ref.get("unit"),
            "prior_value": p.get("value") if p else None,
            "current_value": c.get("value") if c else None,
            "delta": None,
        }
        if p is None:
            row["status"] = "new"
        elif c is None:
            row["status"] = "resolved"
        elif (c.get("sizing_metric"), c.get("unit")) != (p.get("sizing_metric"), p.get("unit")):
            row["status"] = "metric changed"
        elif isinstance(c.get("value"), (int, float)) and isinstance(p.get("value"), (int, float)):
            row["delta"] = round(float(c["value"]) - float(p["value"]), 4)
            row["status"] = "changed" if row["delta"] else "unchanged"
        else:
            row["status"] = "unsized"
        rows.append(row)
    return rows


def _sizing_markdown(prior_date: str, rows: list[dict[str, Any]] | None, note: str | None) -> list[str]:
    lines = ["## Backlog sizing (primary trend)", ""]
    if rows is None:
        return [*lines, f"> {note or 'no backlog sizing available'}", ""]
    if not rows:
        return [*lines, "No backlog items in either run.", ""]
    lines += [
        f"Per (id, target) sizing vs {prior_date} — the items the customer acts on.",
        "",
        "| Id | Target | Tier (prior → current) | Metric | Prior | Current | Unit | Δ | Status |",
        "|---|---|---|---|---:|---:|---|---:|---|",
    ]
    for r in rows:
        delta = r.get("delta")
        delta_txt = f"{float(delta):+,.2f}" if isinstance(delta, (int, float)) else "—"
        lines.append(
            f"| {r['id']} | {r.get('target') or '—'} | {r.get('prior_tier') or '—'} → "
            f"{r.get('current_tier') or '—'} | {r.get('sizing_metric') or '—'} | "
            f"{_fmt_dbu(r.get('prior_value'))} | {_fmt_dbu(r.get('current_value'))} | "
            f"{r.get('unit') or '—'} | {delta_txt} | {r['status']} |"
        )
    lines.append("")
    return lines


def _backlog_by_id(bl: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collapse items per catalog id: the highest tier wins, confidence = max at that tier."""
    out: dict[str, dict[str, Any]] = {}
    for it in bl.get("items") or []:
        if not isinstance(it, dict) or not isinstance(it.get("id"), str):
            continue
        tier = it.get("tier")
        rank = _TIER_RANK.get(tier, len(_TIER_RANK)) if isinstance(tier, str) else len(_TIER_RANK)
        conf = it.get("confidence") if isinstance(it.get("confidence"), int) else None
        cur = out.get(it["id"])
        if cur is None or rank < cur["_rank"]:
            out[it["id"]] = {"tier": tier, "confidence": conf, "_rank": rank}
        elif rank == cur["_rank"] and conf is not None and (cur["confidence"] is None or conf > cur["confidence"]):
            cur["confidence"] = conf
    return out


def _backlog_delta(current: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    """Diff two backlogs by catalog id: new / resolved / tier_changed / confidence_changed."""
    cur, pri = _backlog_by_id(current), _backlog_by_id(prior)
    cut_reasons = {
        c["id"]: c.get("reason")
        for c in current.get("cut") or []
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    tier_changed: list[dict[str, Any]] = []
    confidence_changed: list[dict[str, Any]] = []
    unchanged: list[str] = []
    for i in sorted(set(cur) & set(pri)):
        c, p = cur[i], pri[i]
        if c["tier"] != p["tier"]:
            tier_changed.append({
                "id": i, "prior_tier": p["tier"], "current_tier": c["tier"],
                "prior_confidence": p["confidence"], "current_confidence": c["confidence"],
            })
        elif c["confidence"] != p["confidence"]:
            confidence_changed.append({
                "id": i, "tier": c["tier"],
                "prior_confidence": p["confidence"], "current_confidence": c["confidence"],
            })
        else:
            unchanged.append(i)
    return {
        "new": [{"id": i, "tier": cur[i]["tier"], "confidence": cur[i]["confidence"]} for i in sorted(set(cur) - set(pri))],
        "resolved": [
            {"id": i, "prior_tier": pri[i]["tier"], "prior_confidence": pri[i]["confidence"],
             "cut_reason": cut_reasons.get(i)}
            for i in sorted(set(pri) - set(cur))
        ],
        "tier_changed": tier_changed,
        "confidence_changed": confidence_changed,
        "unchanged": unchanged,
    }


def _backlog_delta_markdown(prior_date: str, delta: dict[str, Any] | None, note: str | None) -> list[str]:
    lines = ["## Backlog delta (catalog ids)", ""]
    if delta is None:
        return [*lines, f"> {note}", ""]
    lines.append(
        f"vs {prior_date}: {len(delta['new'])} new, {len(delta['resolved'])} resolved, "
        f"{len(delta['tier_changed'])} tier changed, {len(delta['confidence_changed'])} confidence "
        f"changed, {len(delta['unchanged'])} unchanged."
    )
    lines.append("")
    if delta["new"]:
        lines.append("- New: " + ", ".join("`{}` ({})".format(e["id"], e["tier"]) for e in delta["new"]))
    if delta["resolved"]:
        lines.append(
            "- Resolved: "
            + ", ".join(
                "`{}` (was {}{})".format(
                    e["id"], e["prior_tier"], f"; cut: {e['cut_reason']}" if e["cut_reason"] else ""
                )
                for e in delta["resolved"]
            )
        )
    if delta["tier_changed"] or delta["confidence_changed"]:
        lines += ["", "| Id | Prior tier | Current tier | Prior conf | Current conf |", "|---|---|---|---:|---:|"]
        for e in delta["tier_changed"]:
            lines.append(
                f"| {e['id']} | {e['prior_tier']} | {e['current_tier']} | "
                f"{e['prior_confidence'] if e['prior_confidence'] is not None else '—'} | "
                f"{e['current_confidence'] if e['current_confidence'] is not None else '—'} |"
            )
        for e in delta["confidence_changed"]:
            lines.append(
                f"| {e['id']} | {e['tier']} | {e['tier']} | "
                f"{e['prior_confidence'] if e['prior_confidence'] is not None else '—'} | "
                f"{e['current_confidence'] if e['current_confidence'] is not None else '—'} |"
            )
    lines.append("")
    return lines


def _upsert_history(history: list[dict[str, Any]], entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Idempotent by run_date: replace any same-date entry, keep the list sorted."""
    kept = [h for h in history if h.get("run_date") != entry["run_date"]]
    kept.append(entry)
    return sorted(kept, key=lambda h: str(h.get("run_date")))


def _render_available() -> bool:
    """True when the optional chart-render extra (vl-convert-python) is importable.

    Checked up front so ``run recur`` never triggers the charts helper's auto-install
    (scheduled/unattended runs must not pip-install); a missing extra degrades to
    data-only output with a reported reason.
    """
    import importlib.util

    return importlib.util.find_spec("vl_convert") is not None


def _render_trend_charts(data_dir: Path, trend_dir: Path) -> tuple[list[str], str | None]:
    """Render both trend PNGs via the charts helper; returns (rendered paths, skip/err reason)."""
    if not _render_available():
        return [], (
            "chart render extra not installed (vl-convert-python) — wrote chart data only; "
            "install starboard-skills[render] and re-run `starboard-helper run recur` to render"
        )
    from types import SimpleNamespace

    # lazy — pulls the kernel charts module
    from starboard_skills.helpers import charts_render

    rendered: list[str] = []
    errors: list[str] = []
    for kind in _TREND_CHARTS:
        ns = SimpleNamespace(
            kind=kind,
            data=str(data_dir / f"{kind}.json"),
            out=str(trend_dir / f"{kind}.png"),
            format="png",
        )
        try:
            res = charts_render.cmd_render(ns)
            rendered.append(res["out_path"])
        except Exception as exc:  # noqa: BLE001 - surface, keep the data
            errors.append(f"{kind}: {exc}")
    return rendered, ("; ".join(errors) if errors else None)


def _fmt_dbu(v: Any) -> str:
    return f"{float(v):,.2f}" if isinstance(v, (int, float)) else "—"


def _fmt_pct(v: Any) -> str:
    return f"{float(v) * 100:+.1f}%" if isinstance(v, (int, float)) else "—"


def _extract_cost_delta(review: Any) -> dict[str, Any] | None:
    """cost_delta from a saved ``starboard review --json`` output (envelope or bare data)."""
    if not isinstance(review, dict):
        return None
    for holder in (review.get("data"), review):
        if isinstance(holder, dict) and isinstance(holder.get("cost_delta"), dict):
            return holder["cost_delta"]
    return None


def _delta_counts(cd: dict[str, Any]) -> dict[str, int]:
    return {key: len(cd.get(key) or []) for key, _ in _DELTA_CLASSES}


def _delta_markdown(
    run_date: str,
    prior_date: str,
    prior_dir: Path,
    cost_delta: dict[str, Any] | None,
    prior_entry: dict[str, Any],
    entry: dict[str, Any],
    backlog_delta: dict[str, Any] | None = None,
    backlog_note: str | None = None,
    sizing_rows: list[dict[str, Any]] | None = None,
) -> str:
    any_degraded = entry.get("degraded") is True or prior_entry.get("degraded") is True
    not_comparable = set(entry.get("unavailable_domains") or []) | set(prior_entry.get("unavailable_domains") or [])
    lines = [
        f"# Delta vs {prior_date}",
        "",
        f"Current run: {run_date} · prior run: {prior_date} (`{prior_dir.name}`).",
        "DBU = list-price DBU estimate. Product-level DBU totals are account-scoped; finding-level DBU",
        "is workspace/entity-attributable.",
        "",
        f"Total DBU estimate: {_fmt_dbu(prior_entry.get('total_dbu_estimate'))} → "
        f"{_fmt_dbu(entry.get('total_dbu_estimate'))} · findings: "
        f"{prior_entry.get('finding_count', '—')} → {entry.get('finding_count', '—')}"
        + (" (not comparable: a review was degraded)" if any_degraded else ""),
        "",
        "![Spend over time](../charts/trend/spend-over-time.png)",
        "![Finding count over time](../charts/trend/finding-count-over-time.png)",
        "",
    ]
    if any_degraded:
        lines += [
            "## Review coverage",
            "",
            "A degraded review lost evidence queries, so its findings in those domains are partial.",
            "Domains marked not comparable are excluded from any run-over-run claim; degraded runs are",
            "left out of the finding-count trend.",
            "",
            "| Run | Degraded | Unavailable domains | Unavailable queries |",
            "|---|---|---|---:|",
        ]
        for label, e in (("current", entry), ("prior", prior_entry)):
            lines.append(
                f"| {label} ({e.get('run_date', '—')}) | {'yes' if e.get('degraded') is True else 'no'} | "
                f"{', '.join(e.get('unavailable_domains') or []) or '—'} | "
                f"{len(e.get('unavailable_queries') or [])} |"
            )
        lines.append("")
        if not_comparable:
            lines += [
                "| Domain | Comparable |",
                "|---|---|",
                *[f"| {d} | not comparable |" for d in sorted(not_comparable)],
                "",
            ]
    # Primary trend: the verified backlog's per-(id, target) sizing. The review findings'
    # cost_delta below is secondary — it tracks review rules, not what the customer acts on.
    lines += _sizing_markdown(prior_date, sizing_rows, backlog_note)
    lines += _backlog_delta_markdown(prior_date, backlog_delta, backlog_note)
    if isinstance(entry.get("coverage_note"), str):
        lines += [f"Review coverage: {entry['coverage_note']}", ""]
    lines += [
        "## Review findings cost delta (secondary)",
        "",
        "Run-over-run delta of the workload-review findings (rule × entity); secondary to the",
        "backlog sizing above.",
        "",
    ]
    if cost_delta is None:
        lines += [
            "> cost_delta not found in `analysis/review.json`. Re-run the review with",
            f"> `--since {prior_dir}/{_MANIFEST_NAME}` and save its `--json` output to",
            "> `analysis/review.json`, then re-run `starboard-helper run recur`.",
            "",
        ]
    else:
        for key, title in _DELTA_CLASSES:
            entries = [e for e in cost_delta.get(key) or [] if isinstance(e, dict)]
            lines += [f"### {title} ({len(entries)})", ""]
            if not entries:
                lines += ["None.", ""]
                continue
            lines += [
                "| Entity | Rule | Prior DBU | Current DBU | Δ % | Note |",
                "|---|---|---:|---:|---:|---|",
            ]
            for e in entries:
                entity = e.get("entity_id") or e.get("composite_key") or "—"
                note = e.get("note") or e.get("severity_changed") or ""
                if (e.get("category") or e.get("domain")) in not_comparable:
                    note = f"{note}; not comparable (domain degraded)" if note else "not comparable (domain degraded)"
                lines.append(
                    f"| {entity} | {e.get('rule_id') or '—'} | {_fmt_dbu(e.get('prior_dbu'))} | "
                    f"{_fmt_dbu(e.get('current_dbu'))} | {_fmt_pct(e.get('dbu_delta_pct'))} | {note} |"
                )
            lines.append("")
        products = cost_delta.get("products_dbu_delta") or {}
        if isinstance(products, dict) and products:
            lines += [
                "### Product DBU delta (account-scoped)",
                "",
                "| Product | Δ DBU |",
                "|---|---:|",
            ]
            lines += [f"| {p} | {_fmt_dbu(v)} |" for p, v in products.items()]
            lines.append("")
    lines += ["## Narrative", "", _DELTA_PLACEHOLDER, ""]
    return "\n".join(lines)


def _upsert_readme_recur(readme: Path, body: list[str], title: str) -> None:
    """Replace (or append) the README ``## Recur`` section with ``body``."""
    text = readme.read_text(errors="replace") if readme.is_file() else f"# {title}\n"
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        if lines[i].strip() == "## Recur" and not replaced:
            out.append("## Recur")
            out.extend(body)
            i += 1
            while i < len(lines) and not re.match(r"^#{1,2}\s", lines[i].strip()):
                i += 1
            if i < len(lines):
                out.append("")
            replaced = True
            continue
        out.append(lines[i])
        i += 1
    if not replaced:
        while out and not out[-1].strip():
            out.pop()
        out += ["", "## Recur", *body]
    readme.write_text("\n".join(out).rstrip("\n") + "\n")


def _write_recur_result(run_dir: Path, result: dict[str, Any]) -> Path:
    path = run_dir / _RECUR_RESULT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=str) + "\n")
    return path


def cmd_recur(args: Any) -> dict[str, Any]:
    """Deterministic recur beat over a run dir that already holds findings-manifest.json.

    Always leaves ``analysis/recur-result.json`` behind — ``ok: false`` with ``errors`` when the
    beat fails on a bad argument/input — so ``run check`` (item 15) can read the outcome.
    """
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        raise ArgError(f"run-dir not found or not a directory: {run_dir}")
    try:
        return _recur(run_dir, args)
    except ArgError as exc:
        _write_recur_result(
            run_dir,
            {
                "ok": False,
                "baseline": bool(getattr(args, "baseline", False)),
                "prior_run": None,
                "history_path": None,
                "history_entry": None,
                "backlog_delta": None,
                "errors": [str(exc)],
                "warnings": [],
            },
        )
        raise


def _recur(run_dir: Path, args: Any) -> dict[str, Any]:
    import os

    manifest_path = run_dir / _MANIFEST_NAME
    if not manifest_path.is_file():
        raise ArgError(
            f"{_MANIFEST_NAME} not found in {run_dir} — run `starboard review … --json "
            f"--manifest-out {manifest_path}` first"
        )
    manifest = _load_json(manifest_path, _MANIFEST_NAME)
    if not isinstance(manifest, dict):
        raise ArgError(f"{_MANIFEST_NAME} must be a JSON object")
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    if workspace_root == run_dir:
        raise ArgError(
            "--workspace-root must not be the run dir itself — use the dir that holds the run "
            "dirs (e.g. the run dir's parent), or a dedicated trend root such as <run-dir>/ws-root "
            "for an isolated run"
        )
    force_baseline = bool(getattr(args, "baseline", False))
    if force_baseline and getattr(args, "prior", None):
        raise ArgError("--baseline and --prior are mutually exclusive")

    warnings: list[str] = []
    written: list[str] = []
    run_date = _run_date_of(run_dir, manifest)

    # --- prior run ----------------------------------------------------------
    prior_dir: Path | None
    if force_baseline:
        prior_dir = None
    elif getattr(args, "prior", None):
        prior_dir = Path(args.prior).expanduser().resolve()
        if prior_dir == run_dir:
            raise ArgError("--prior must be a different run dir than <run-dir>")
        if not (prior_dir / _MANIFEST_NAME).is_file():
            raise ArgError(
                f"--prior has no {_MANIFEST_NAME}: {prior_dir} (first run? use --baseline)"
            )
    else:
        prior_dir = _locate_prior(run_dir, workspace_root, (run_date, run_dir.name))
    prior_manifest: dict[str, Any] | None = None
    prior_date: str | None = None
    if prior_dir is not None:
        pm = _load_json(prior_dir / _MANIFEST_NAME, f"prior {_MANIFEST_NAME}")
        prior_manifest = pm if isinstance(pm, dict) else {}
        prior_date = _run_date_of(prior_dir, prior_manifest)
    baseline = prior_dir is None

    # --- trend history (idempotent by run_date) -----------------------------
    history_path = workspace_root / "trend" / "history.json"
    history: list[dict[str, Any]] = []
    if history_path.is_file():
        loaded = _load_json(history_path, "trend/history.json")
        if not isinstance(loaded, list):
            raise ArgError(f"trend/history.json must be a JSON array: {history_path}")
        history = [h for h in loaded if isinstance(h, dict)]
    entry, dbu_source = _history_entry(run_date, manifest, run_dir)
    if dbu_source == "finding_evidence_dbu":
        warnings.append("manifest has no products_dbu; total_dbu_estimate = sum of finding-level DBU")
    elif dbu_source == "none":
        warnings.append("manifest carries no DBU figures; total_dbu_estimate is null")
    if entry["act_now"] is None:
        warnings.append("analysis/backlog.json not found — history act_now/investigate/not_now are null")
    prior_entry: dict[str, Any] = {}
    if prior_dir is not None and prior_manifest is not None and prior_date is not None:
        prior_entry, _ = _history_entry(prior_date, prior_manifest, prior_dir)
        if not any(h.get("run_date") == prior_date for h in history):
            history = _upsert_history(history, prior_entry)  # backfill the prior run once
    history = _upsert_history(history, entry)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2) + "\n")
    written.append(str(history_path))

    # --- chart data + PNGs ----------------------------------------------------
    data_dir = run_dir / "charts" / "data"
    trend_dir = run_dir / "charts" / "trend"
    data_dir.mkdir(parents=True, exist_ok=True)
    spend_rows = [
        {"run_date": h["run_date"], "total_dbu_estimate": h["total_dbu_estimate"]}
        for h in history
        if isinstance(h.get("total_dbu_estimate"), (int, float))
    ]
    # A degraded review's finding counts reflect which evidence queries survived, not the
    # workspace — those points are left out of the finding-count trend (spend comes from billing).
    degraded_dates = [str(h["run_date"]) for h in history if h.get("degraded") is True]
    count_rows = [
        {"run_date": h["run_date"], "severity": s, "count": int(h.get(s) or 0)}
        for h in history
        if h.get("degraded") is not True
        for s in _TREND_SEVERITIES
    ]
    if degraded_dates:
        warnings.append(
            "finding-count trend skips degraded review run(s): " + ", ".join(degraded_dates)
        )
    for name, rows in (("spend-over-time", spend_rows), ("finding-count-over-time", count_rows)):
        p = data_dir / f"{name}.json"
        p.write_text(json.dumps(rows, indent=2) + "\n")
        written.append(str(p))
    rendered, render_note = _render_trend_charts(data_dir, trend_dir)
    written.extend(rendered)
    if render_note:
        warnings.append(render_note)

    # --- backlog delta (by catalog id) ----------------------------------------
    backlog_delta: dict[str, Any] | None = None
    backlog_note: str | None = None
    sizing_rows: list[dict[str, Any]] | None = None
    if prior_dir is not None:
        cur_bl, prior_bl = _read_backlog(run_dir), _read_backlog(prior_dir)
        if cur_bl is None or prior_bl is None:
            missing = [n for n, b in (("current", cur_bl), ("prior", prior_bl)) if b is None]
            backlog_note = f"analysis/backlog.json missing in the {' and '.join(missing)} run — no backlog delta."
            warnings.append(backlog_note)
        else:
            backlog_delta = _backlog_delta(cur_bl, prior_bl)
            sizing_rows = _backlog_sizing_delta(_backlog_items_sizing(cur_bl), _backlog_items_sizing(prior_bl))

    # --- delta skeleton -------------------------------------------------------
    delta_path: Path | None = None
    counts: dict[str, int] | None = None
    if prior_dir is not None and prior_date is not None:
        review_path = run_dir / "analysis" / "review.json"
        cost_delta: dict[str, Any] | None = None
        if review_path.is_file():
            cost_delta = _extract_cost_delta(_load_json(review_path, "analysis/review.json"))
            if cost_delta is None:
                warnings.append(
                    "analysis/review.json has no cost_delta — re-run review with "
                    f"--since {prior_dir / _MANIFEST_NAME}"
                )
        else:
            warnings.append(
                "analysis/review.json not found — save the `starboard review --json --since …` output there"
            )
        counts = _delta_counts(cost_delta) if cost_delta is not None else None
        delta_path = run_dir / "analysis" / f"delta-vs-{prior_date}.md"
        delta_path.parent.mkdir(parents=True, exist_ok=True)
        # Idempotent but never clobbers the analyst's work: regenerate only while the file is
        # absent or still carries the untouched skeleton placeholder.
        if delta_path.is_file() and _DELTA_PLACEHOLDER not in delta_path.read_text(errors="replace"):
            warnings.append(f"kept existing {delta_path.name} (narrative already written)")
        else:
            delta_path.write_text(
                _delta_markdown(
                    run_date, prior_date, prior_dir, cost_delta, prior_entry, entry,
                    backlog_delta, backlog_note, sizing_rows,
                )
            )
            written.append(str(delta_path))

    # --- README ## Recur -------------------------------------------------------
    rel_hist = os.path.relpath(history_path, run_dir)
    links = [
        f"- Trend history: `{rel_hist}` ({len(history)} run(s))",
        "- Trend charts: `charts/trend/spend-over-time.png`, `charts/trend/finding-count-over-time.png`"
        + ("" if rendered else " (data only: `charts/data/`)"),
        f"- Recur result: `{_RECUR_RESULT}`",
    ]
    body: list[str] = []
    if baseline:
        body = [
            f"baseline — no prior run ({run_date}). This run's `{_MANIFEST_NAME}` is the baseline "
            "for the next recurrence.",
            *links,
        ]
    elif prior_dir is not None and prior_date is not None and delta_path is not None:
        # Primary: the backlog sizing per (id, target); the review cost_delta is secondary.
        if sizing_rows is not None:
            by_status: dict[str, int] = {}
            for r in sizing_rows:
                by_status[r["status"]] = by_status.get(r["status"], 0) + 1
            summary = (
                f"delta vs {prior_date} (backlog sizing per id × target): "
                + (", ".join(f"{n} {k}" for k, n in sorted(by_status.items())) or "no items")
                + "."
            )
        else:
            summary = f"delta vs {prior_date}: backlog sizing unavailable — {backlog_note or 'see the delta file'}."
        if counts is not None:
            secondary = (
                f"Review findings (secondary): {counts['improved']} improved, {counts['regressed']} regressed, "
                f"{counts['newly_expensive']} newly expensive, {counts['persisting']} persisting, "
                f"{counts['new_low_cost']} new (low-cost)."
            )
        else:
            secondary = f"Review findings (secondary): cost_delta unavailable — see `analysis/{delta_path.name}`."
        body = [
            summary,
            secondary,
            f"Total DBU estimate (list-price): {_fmt_dbu(prior_entry.get('total_dbu_estimate'))} → "
            f"{_fmt_dbu(entry.get('total_dbu_estimate'))}.",
        ]
        if backlog_delta is not None:
            body.append(
                f"Backlog vs {prior_date}: {len(backlog_delta['new'])} new, "
                f"{len(backlog_delta['resolved'])} resolved, {len(backlog_delta['tier_changed'])} tier changed."
            )
        body += [f"- Delta: `analysis/{delta_path.name}` (prior run: `{prior_dir.name}`)", *links]
    if isinstance(entry.get("coverage_note"), str):
        body.insert(1, f"Review coverage: {entry['coverage_note']}")
    if entry.get("degraded") is True:
        body.insert(
            1,
            "Review degraded (unavailable domains: "
            f"{', '.join(entry['unavailable_domains']) or 'unnamed'}) — finding counts are partial and "
            "those domains are not comparable run-over-run.",
        )
    readme = run_dir / "README.md"
    _upsert_readme_recur(readme, body, run_dir.name)
    written.append(str(readme))

    # --- recur-result.json (read back by run check item 15) -------------------
    result_path = _write_recur_result(
        run_dir,
        {
            "ok": True,
            "baseline": baseline,
            "prior_run": str(prior_dir) if prior_dir else None,
            "history_path": str(history_path),
            "history_entry": entry,
            "backlog_delta": backlog_delta,
            "backlog_sizing": sizing_rows,
            "errors": [],
            "warnings": warnings,
        },
    )
    written.append(str(result_path))

    return {
        "run_dir": str(run_dir),
        "run_date": run_date,
        "baseline": baseline,
        "prior_run_dir": str(prior_dir) if prior_dir else None,
        "prior_run_date": prior_date,
        "history_path": str(history_path),
        "history_entries": len(history),
        "entry": entry,
        "total_dbu_source": dbu_source,
        "delta_counts": counts,
        "delta_path": str(delta_path) if delta_path else None,
        "backlog_delta": backlog_delta,
        "backlog_sizing": sizing_rows,
        "recur_result_path": str(result_path),
        "charts_rendered": rendered,
        "files_written": written,
        "warnings": warnings,
    }
