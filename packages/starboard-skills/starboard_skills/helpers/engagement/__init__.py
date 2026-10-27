"""Engagement run lifecycle for ``starboard-engagement``: Drive-only on covered runs.

Run setup:

* ``source-options`` (read-only, run first) lists the source modes and stores the
  install offers.
* ``preflight`` classifies the run's storage policy from the source mode and the
  internal-overlay signal, then mints the run ID.
  * A Drive run stages ``storage-preflight.json`` in the restricted folder
    ``My Drive/starboard/_preflight/<RUN ID>`` and writes nothing locally.
  * Only the ``local`` and ``internal_only_local`` policies create the local run
    directory ``starboard-reports/<account>/<task>/<task-name>/<run-id>/``.
  * On a covered run (overlay on, customer leg), ``--storage local`` is refused
    with ``LOCAL_STORAGE_REFUSED``.
  * ``--resume-run-id`` re-reads the staging folder from Drive. An unknown ID is
    an error and creates nothing.
  * Only a Drive run loads the storage adapter. When it is missing, preflight
    exits 2 with ``STORAGE_UNAVAILABLE`` before minting a resumable run.
* ``verify-identity``, ``route`` and ``status`` take ``--run-id``. A run ID with
  a local run dir under ``starboard-reports/`` is a local run and never loads the
  storage adapter; ``--run-dir`` names a local run dir kept elsewhere.
* ``verify-identity`` proves that the workspace behind ``--profile``/``--host`` is
  the expected one, using one read-only SCIM ``Me`` call. It stages
  ``identity-check.json``. A mismatch quarantines the staging folder and exits 5.
* ``route`` resolves the account, ticket or override route.
  * It writes the immutable run descriptor and manifest revision 1.
  * It writes ``analysis/identity-check.json`` through the run sink.
  * It registers the run in the operator ``_registry``, plus the shared registry
    when configured.

Run lifecycle (``--run-folder``; ``status`` also takes ``--run-id``/``--run-dir``):
``status``, ``commit`` (never touches
``publication``), ``put`` (one host-authored artifact from stdin, through the run
sink; control records are refused), ``read``, ``history``, then publication with ``report``,
``approve``, ``deliver`` and ``receipt``.

Registry: ``import-local`` (the internal-only bridge) and ``rebuild-index``.

Every subcommand prints one compact envelope
``{"ok","domain","command","data","warnings","errors"}``, bounded by
:func:`starboard_core.engagement.stdout_budget.bound`.

Exit codes:

* 0: ok
* 1: internal error (an unexpected exception; its traceback goes to stderr)
* 2: usage error or refusal
* 3: auth needed
* 4: storage, integrity or access problem
* 5: identity mismatch or quarantined run
* 6: Databricks workspace API failure (``WORKSPACE_API_ERROR``; retryable)
* 8: transient Drive failure (``STORAGE_TRANSIENT``; retryable, nothing refused)

A failure's ``errors[0]`` carries ``code``, ``message`` and ``retryable`` (true
only for ``STORAGE_TRANSIENT`` and ``WORKSPACE_API_ERROR``).

A covered run arms the local write guard for its Drive phase. No ticket lookup
happens here: the internal overlay validates the ticket and passes its
``TicketRef`` JSON in.

Package layout: :mod:`._envelope` (constants, errors, envelope and the test
seams), :mod:`._runs` (shared run plumbing), :mod:`.setup`, :mod:`.lifecycle`,
:mod:`.publication` and :mod:`.registry_cmds` (the subcommands). This module
holds the argument parser.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any, NoReturn

from starboard_skills.helpers.contract import redact_emails
from starboard_skills.helpers.engagement._envelope import (
    ARTIFACT_PROPERTY,
    AUDIENCES,
    AUTHORIZATION_RECORD,
    BASELINE_PATH,
    DEFAULT_PUT_BYTES,
    DEFAULT_READ_BYTES,
    DEFAULT_REPORTS_ROOT,
    DELIVERY_PROPERTY,
    DOMAIN,
    EVIDENCE_PATH,
    EXIT_AUTH_PROMPT,
    EXIT_IDENTITY,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_STORAGE,
    EXIT_STORAGE_TRANSIENT,
    EXIT_USAGE,
    EXIT_WORKSPACE,
    FINDINGS_MANIFEST_PATH,
    FINDINGS_PATH,
    IDENTITY_RECORD,
    IMPORT_SUMMARY,
    METHODOLOGY_VERSION,
    OBSERVATIONS_PATH,
    PREFLIGHT_RECORD,
    PROVISIONAL_SOURCES,
    RECEIPT_CHANNELS,
    RUN_FOLDER_PROPERTY,
    SHARED_REGISTRY_ENV,
    SOURCE_MODES,
    STAGE_STATES,
    STAGED_IDENTITY,
    STAGED_PREFLIGHT,
    STAGES,
    TASKS,
    IdentityMismatch,
    PrincipalKind,
    Refusal,
    RunQuarantined,
    WorkspaceApiError,
    WorkspaceAuthError,
    _emit,
    _entry,
)
from starboard_skills.helpers.engagement.analysis_cmds import add_run_args, cmd_analyze
from starboard_skills.helpers.engagement.case_cmds import (
    ACTION_EVENTS,
    CAUSE_CONFIDENCE,
    HYPOTHESIS_STATES,
    OWNER_ROLES,
    cmd_action_accept,
    cmd_action_execute,
    cmd_action_propose,
    cmd_action_reject,
    cmd_action_withdraw,
    cmd_case_open,
    cmd_case_revise,
    cmd_case_show,
    cmd_play_rank,
)
from starboard_skills.helpers.engagement.lifecycle import (
    cmd_commit,
    cmd_history,
    cmd_put,
    cmd_read,
    cmd_status,
)
from starboard_skills.helpers.engagement.publication import (
    cmd_approve,
    cmd_deliver,
    cmd_receipt,
    cmd_report,
)
from starboard_skills.helpers.engagement.registry_cmds import (
    cmd_import_local,
    cmd_rebuild_index,
)
from starboard_skills.helpers.engagement.setup import (
    cmd_preflight,
    cmd_route,
    cmd_verify_identity,
)
from starboard_skills.helpers.engagement.source_options import cmd_source_options

__all__ = [
    "ARTIFACT_PROPERTY",
    "AUDIENCES",
    "AUTHORIZATION_RECORD",
    "BASELINE_PATH",
    "DEFAULT_PUT_BYTES",
    "DEFAULT_READ_BYTES",
    "DEFAULT_REPORTS_ROOT",
    "DELIVERY_PROPERTY",
    "DOMAIN",
    "EVIDENCE_PATH",
    "EXIT_AUTH_PROMPT",
    "EXIT_IDENTITY",
    "EXIT_INTERNAL",
    "EXIT_OK",
    "EXIT_STORAGE",
    "EXIT_STORAGE_TRANSIENT",
    "EXIT_USAGE",
    "EXIT_WORKSPACE",
    "FINDINGS_MANIFEST_PATH",
    "FINDINGS_PATH",
    "IDENTITY_RECORD",
    "IMPORT_SUMMARY",
    "IdentityMismatch",
    "METHODOLOGY_VERSION",
    "OBSERVATIONS_PATH",
    "PREFLIGHT_RECORD",
    "PROVISIONAL_SOURCES",
    "PrincipalKind",
    "RECEIPT_CHANNELS",
    "RUN_FOLDER_PROPERTY",
    "Refusal",
    "RunQuarantined",
    "SHARED_REGISTRY_ENV",
    "SOURCE_MODES",
    "STAGED_IDENTITY",
    "STAGED_PREFLIGHT",
    "STAGES",
    "STAGE_STATES",
    "TASKS",
    "WorkspaceApiError",
    "WorkspaceAuthError",
    "cmd_action_accept",
    "cmd_action_execute",
    "cmd_action_propose",
    "cmd_action_reject",
    "cmd_action_withdraw",
    "cmd_analyze",
    "cmd_approve",
    "cmd_case_open",
    "cmd_case_revise",
    "cmd_case_show",
    "cmd_commit",
    "cmd_deliver",
    "cmd_history",
    "cmd_import_local",
    "cmd_play_rank",
    "cmd_preflight",
    "cmd_put",
    "cmd_read",
    "cmd_rebuild_index",
    "cmd_receipt",
    "cmd_report",
    "cmd_route",
    "cmd_source_options",
    "cmd_status",
    "cmd_verify_identity",
    "register",
]


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
class _EngagementParser(argparse.ArgumentParser):
    """An engagement verb's parser: a bad argument is a USAGE envelope (exit 2).

    The top-level helper maps argparse errors to its generic exit-4 envelope,
    which under the engagement exit table reads as a storage failure. Leftover
    arguments are refused here too (argparse would otherwise hand them to the
    top-level parser), naming the shell-quoting slip that usually causes them.
    """

    def parse_known_args(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> tuple[argparse.Namespace, list[str]]:
        parsed, extras = super().parse_known_args(args, namespace)
        if extras:
            message = "unrecognized arguments: " + " ".join(extras)
            if any(any(c.isspace() for c in e) for e in extras):
                message += (
                    " (an argument holding spaces arrived as one shell word: pass "
                    "each flag and value as its own word, e.g. a quoted shell array)"
                )
            self.error(message)
        return parsed, extras

    def error(self, message: str) -> NoReturn:
        _, _, command = self.prog.partition(f" {DOMAIN} ")
        envelope: dict[str, Any] = {
            "ok": False,
            "domain": DOMAIN,
            "command": command or None,
            "data": {"run_id": None, "run_folder_id": None},
            "warnings": [],
            "errors": [
                {
                    "code": "USAGE",
                    "message": redact_emails(f"{self.prog}: {message}") or message,
                    "retryable": False,
                }
            ],
        }
        _emit(envelope)
        sys.exit(EXIT_USAGE)


def _run_folder_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--run-folder", required=True, help="run_folder_id from `engagement route`"
    )


def _revision_args(p: argparse.ArgumentParser) -> None:
    _run_folder_arg(p)
    p.add_argument(
        "--report-id", required=True, help="Report ID (a Drive path segment)"
    )
    p.add_argument("--revision", required=True, type=int, help="Report revision number")


def _domain_arg(p: argparse.ArgumentParser, help_text: str) -> None:
    p.add_argument("--internal-domain", action="append", default=None, help=help_text)


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "engagement",
        help="Engagement run lifecycle: preflight, identity gate, Drive route, commit and publication",
    )
    # An unknown or missing verb is a USAGE envelope too (``p`` is the top-level
    # helper's parser class, whose error is the generic exit 4).
    setattr(p, "error", _EngagementParser.error.__get__(p))  # noqa: B010
    sp = p.add_subparsers(dest="command", required=True, parser_class=_EngagementParser)

    pre = sp.add_parser(
        "preflight",
        help="Classify storage (overlay-aware), mint the run ID and stage it in Drive",
    )
    pre.add_argument(
        "--source-mode",
        default=None,
        choices=SOURCE_MODES,
        help="Required for a new run",
    )
    pre.add_argument(
        "--task", default=None, choices=TASKS, help="The engagement task (new run)"
    )
    pre.add_argument(
        "--task-name",
        default=None,
        help="Stable case name, e.g. ws-<workspace_id> or job-<job_id> (new run)",
    )
    pre.add_argument(
        "--account-key",
        default=None,
        help="Stable account identity (CRM account ID, or workspace ID on public installs)",
    )
    pre.add_argument(
        "--account-name",
        default=None,
        help="Account display name; a public install uses the workspace name (new run)",
    )
    pre.add_argument(
        "--internal-workspace-id",
        default=None,
        metavar="ID",
        help="internal_only runs only: the one workspace the run is scoped to",
    )
    pre.add_argument(
        "--storage",
        choices=("drive", "local"),
        default=None,
        help="Operator's explicit store choice; local is refused on a covered run",
    )
    pre.add_argument(
        "--reports-root",
        default=None,
        help="Local runs only: the reports root (default: starboard-reports)",
    )
    pre.add_argument(
        "--run-dir", default=None, help="Local runs only: use this run dir as given"
    )
    pre.add_argument(
        "--resume-run-id",
        default=None,
        metavar="RUN_ID",
        help="Retry the preflight of this Drive run (read from My Drive/starboard/_preflight)",
    )
    pre.add_argument(
        "--unattended",
        action="store_true",
        help="Scheduled run: any fallback, override or missing auth is an error",
    )
    pre.set_defaults(func=_entry(cmd_preflight, "preflight"))

    so = sp.add_parser(
        "source-options",
        help=(
            "Read-only: list the source modes and stores this install offers "
            "(no run, no storage call, no Databricks profile)"
        ),
    )
    so.add_argument(
        "--task",
        default=None,
        help=(
            f"The engagement task about to be preflighted, one of {', '.join(TASKS)} "
            "(validated; the options do not vary by task)"
        ),
    )
    so.set_defaults(func=_entry(cmd_source_options, "source-options"))

    vid = sp.add_parser(
        "verify-identity",
        help="Prove the workspace behind --profile/--host is the expected one (read-only)",
    )
    vid.add_argument(
        "--run-id",
        default=None,
        help="run_id from preflight (a local run is found under starboard-reports/)",
    )
    vid.add_argument(
        "--run-dir", default=None, help="Local run dir kept outside starboard-reports/"
    )
    target = vid.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--profile", default=None, help="Databricks config profile to verify"
    )
    target.add_argument(
        "--host", default=None, help="Databricks workspace URL to verify"
    )
    vid.add_argument(
        "--account-key",
        default=None,
        help="Provisional account key (default: from preflight; must agree)",
    )
    vid.add_argument(
        "--account-name",
        default=None,
        help="Must match the preflight account name, if given",
    )
    vid.add_argument(
        "--account-source",
        default="operator",
        choices=PROVISIONAL_SOURCES,
        help="Where the provisional account came from (default: operator)",
    )
    vid.add_argument(
        "--expected-workspace-id",
        "--workspace-id",
        dest="workspace_id",
        default=None,
        help="Expected workspace ID (default: from a ws-<id> task name)",
    )
    vid.add_argument(
        "--expected-host",
        default=None,
        help="Expected workspace URL, also compared if given",
    )
    vid.set_defaults(func=_entry(cmd_verify_identity, "verify-identity"))

    route = sp.add_parser(
        "route",
        help="Authorize the run, create its Drive run folder and register it",
    )
    route.add_argument(
        "--run-id",
        default=None,
        help="run_id from preflight (a local run is found under starboard-reports/)",
    )
    route.add_argument(
        "--run-dir", default=None, help="Local run dir kept outside starboard-reports/"
    )
    route.add_argument(
        "--account-key", default=None, help="Default: from preflight; must agree"
    )
    route.add_argument(
        "--account-name", default=None, help="Default: from preflight; must agree"
    )
    route.add_argument(
        "--ticket-ref",
        default=None,
        help="TicketRef JSON file (or '-') from the internal overlay's ticket validate",
    )
    route.add_argument(
        "--shared-root-id", default=None, help="Shared ticket root folder ID"
    )
    route.add_argument(
        "--override-folder-id",
        default=None,
        help="Internal-restricted folder to hold the run instead of My Drive",
    )
    _domain_arg(
        route,
        "Internal email domain for the ticket/override/shared-registry ACL check (repeatable)",
    )
    route.add_argument(
        "--unattended",
        action="store_true",
        help="Scheduled run: a fallback destination or unused ticket is an error",
    )
    route.set_defaults(func=_entry(cmd_route, "route"))

    st = sp.add_parser(
        "status",
        help="Read-only run status (Drive: descriptor + latest manifest; local: run dir)",
    )
    st.add_argument(
        "--run-id",
        default=None,
        help="run_id from preflight (a local run is found under starboard-reports/)",
    )
    st.add_argument(
        "--run-dir", default=None, help="Local run dir kept outside starboard-reports/"
    )
    st.add_argument("--run-folder", default=None, help="run_folder_id from route")
    st.set_defaults(func=_entry(cmd_status, "status"))

    cm = sp.add_parser(
        "commit",
        help="Verify the run folder's artifacts and commit a stage state (never publication)",
    )
    _run_folder_arg(cm)
    cm.add_argument("--stage", required=True, choices=STAGES)
    cm.add_argument("--state", default="complete", choices=STAGE_STATES)
    cm.set_defaults(func=_entry(cmd_commit, "commit"))

    pt = sp.add_parser(
        "put",
        help="Write one host-authored artifact from stdin into the run folder "
        "(e.g. analysis/backlog.json); no local files",
    )
    _run_folder_arg(pt)
    pt.add_argument("--path", required=True, help="Run-relative artifact path")
    pt.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_PUT_BYTES,
        help=f"Refuse stdin larger than this (default {DEFAULT_PUT_BYTES})",
    )
    pt.set_defaults(func=_entry(cmd_put, "put"))

    rd = sp.add_parser("read", help="Bounded, verified read of one run artifact")
    _run_folder_arg(rd)
    rd.add_argument("--path", required=True, help="Run-relative artifact path")
    rd.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        help=(
            f"Excerpt size, at least 8 (default and cap {DEFAULT_READ_BYTES}, the "
            "stdout budget); a larger value is capped with a warning"
        ),
    )
    rd.add_argument(
        "--jsonpath",
        action="append",
        default=None,
        help=(
            "Path into a JSON artifact: a.b.0.c, a.b[0].c, a[*].c (every item) or "
            "a[50:100].c (a slice). Repeatable: one download, every slice in one "
            "excerpt - always a JSON object keyed by expression, even for one path. "
            "A path the document lacks is null and listed in missing_paths (not an "
            "error). A list returns at most 50 items: next_paths names the slice "
            "that reads the next ones (item k of [a:b] is position a+k). No filters "
            "[?(...)]: page '$[*].finding_id' to find the position, then read "
            "'[<n>].<field>'"
        ),
    )
    rd.add_argument(
        "--offset",
        type=int,
        default=0,
        help=(
            "Text paging: start the excerpt at this byte offset (pass the previous "
            "read's next_offset); not with --jsonpath"
        ),
    )
    rd.set_defaults(func=_entry(cmd_read, "read"))

    hi = sp.add_parser(
        "history",
        help="Select baselines from the account registry; writes analysis/baseline-selection.json",
    )
    _run_folder_arg(hi)
    hi.add_argument(
        "--families", nargs="*", default=None, help="Observation families to compare"
    )
    hi.add_argument(
        "--interval-start", default=None, help="Default: earliest current observation"
    )
    hi.add_argument(
        "--interval-end", default=None, help="Default: latest current observation"
    )
    hi.add_argument("--overlap-adjusted", action="store_true")
    _domain_arg(
        hi, "Internal email domain for the shared-registry ACL check (repeatable)"
    )
    hi.set_defaults(func=_entry(cmd_history, "history"))

    rp = sp.add_parser("report", help="Register a report revision (audience-gated)")
    _run_folder_arg(rp)
    rp.add_argument("--report-id", required=True)
    rp.add_argument("--audience", required=True, choices=AUDIENCES)
    rp.add_argument(
        "--path", required=True, help="Run-relative path of the report object"
    )
    rp.add_argument("--derived-from", default=None, help="<report_id>@<revision>")
    rp.add_argument(
        "--cite-evidence",
        action="append",
        default=None,
        help="Cited evidence ID (repeatable)",
    )
    rp.add_argument(
        "--cite-observation",
        action="append",
        default=None,
        help="Cited observation ID (repeatable)",
    )
    rp.set_defaults(func=_entry(cmd_report, "report"))

    ap = sp.add_parser(
        "approve", help="Approve one exact report revision (attended runs only)"
    )
    _revision_args(ap)
    ap.set_defaults(func=_entry(cmd_approve, "approve"))

    dv = sp.add_parser(
        "deliver", help="Copy a report revision to a Drive folder and record a receipt"
    )
    _revision_args(dv)
    dv.add_argument("--destination-folder-id", required=True)
    dv.set_defaults(func=_entry(cmd_deliver, "deliver"))

    rc = sp.add_parser(
        "receipt", help="Record a host-performed delivery (Slack is never verified)"
    )
    _revision_args(rc)
    rc.add_argument(
        "--external-object-id",
        required=True,
        help="Delivered Drive object ID or Slack message link",
    )
    rc.add_argument("--channel", required=True, choices=RECEIPT_CHANNELS)
    rc.add_argument(
        "--destination-id", default=None, help="Destination folder or Slack channel ID"
    )
    rc.set_defaults(func=_entry(cmd_receipt, "receipt"))

    il = sp.add_parser(
        "import-local",
        help="Register a summary of an internal-only local run in the account registry",
    )
    il.add_argument("--run-dir", required=True)
    il.add_argument("--account-key", required=True)
    il.add_argument(
        "--confirm", action="store_true", help="Records the operator's permission"
    )
    il.add_argument(
        "--unattended", action="store_true", help="Refused: import needs an operator"
    )
    _domain_arg(
        il, "Internal email domain for the shared-registry ACL check (repeatable)"
    )
    il.set_defaults(func=_entry(cmd_import_local, "import-local"))

    ri = sp.add_parser(
        "rebuild-index",
        help="Rebuild the account registry index from its registrations",
    )
    ri.add_argument("--account-key", required=True)
    ri.add_argument(
        "--account-name", default=None, help="Creates the account folder if missing"
    )
    _domain_arg(
        ri, "Internal email domain for the shared-registry ACL check (repeatable)"
    )
    ri.set_defaults(func=_entry(cmd_rebuild_index, "rebuild-index"))

    _register_analysis(sp)


def _register_analysis(sp) -> None:
    """``analyze``, ``case``, ``action`` and ``play``: the run's assessment records."""
    an = sp.add_parser(
        "analyze",
        help=(
            "Assess the run against the account's prior runs: writes analysis/"
            "{observations,findings,health,plays,changes,cases,actions}.json"
        ),
    )
    add_run_args(an)
    an.add_argument(
        "--manifest",
        default=None,
        help=f"Findings manifest (default: {FINDINGS_MANIFEST_PATH} when present)",
    )
    an.add_argument(
        "--facts",
        default=None,
        help="Discovery facts (default: discovery/facts.json when present)",
    )
    an.add_argument(
        "--verify",
        action="append",
        default=None,
        help=(
            "vt-job-run-states verify result (repeatable; default: every "
            "analysis/verify/vt-job-run-states*.json)"
        ),
    )
    an.add_argument(
        "--interval-start", default=None, help="Interval start (YYYY-MM-DD)"
    )
    an.add_argument("--interval-end", default=None, help="Interval end (YYYY-MM-DD)")
    prior = an.add_mutually_exclusive_group()
    prior.add_argument(
        "--prior",
        default=None,
        help=(
            "drive:<run_folder_id> (--run-folder only): compare with that prior run "
            "only, as `run recur --prior` does (pass both the same flag)"
        ),
    )
    prior.add_argument(
        "--baseline",
        action="store_true",
        help="Assess against no prior run, as `run recur --baseline` does",
    )
    an.add_argument(
        "--warehouse-id",
        dest="warehouse_id",
        default=None,
        help=(
            "SQL warehouse the printed verify / discovery commands use (default: the "
            "commands print <warehouse_id> and list it under placeholders)"
        ),
    )
    an.set_defaults(func=_entry(cmd_analyze, "analyze"))

    cp = sp.add_parser("case", help="Open, revise or show an investigation case")
    csp = cp.add_subparsers(dest="case_command", required=True)
    co = csp.add_parser(
        "open",
        help="Open a case on a finding, or a standalone case on a clue / Drive object",
        description=(
            "Open a case on a finding, or a standalone case on a clue / Drive "
            "object. The result's cause_confidence starts unassessed (Starboard's "
            "value); only the host raises it, in order unassessed -> hypothesis -> "
            "supported, with `case revise --cause-confidence`. finding_revision is "
            "the finding's latest revision across the account's runs "
            "(finding_revision_run_id wrote it); open and show never change it."
        ),
    )
    add_run_args(co)
    origin = co.add_mutually_exclusive_group(required=True)
    origin.add_argument(
        "--finding-id", default=None, help="Finding of this run or a prior run"
    )
    origin.add_argument(
        "--clue", default=None,
        help="job:<id>, query:<id>, pipeline:<id> or run:<id> (a job run)",
    )
    origin.add_argument("--drive-object", default=None, help="drive:<file id>")
    co.add_argument(
        "--question",
        required=True,
        help="The question the case answers (at most 500 characters; no emails or "
        "credentials)",
    )
    co.set_defaults(func=_entry(cmd_case_open, "case open"))

    cr = csp.add_parser(
        "revise",
        help="Record one investigation step on a case and its finding",
        description=(
            "Record one investigation step on a case and its finding. The case's "
            "finding_id never changes. A job run-output cited with --evidence "
            "reports its error_signature. cause_confidence moves unassessed -> "
            "hypothesis -> supported (see --cause-confidence)."
        ),
    )
    add_run_args(cr)
    cr.add_argument("--case-id", required=True)
    cr.add_argument(
        "--verify",
        action="append",
        default=None,
        help=(
            "vt-job-run-states verify result of this step (repeatable); only job "
            "run states (cite any other verify result with --evidence)"
        ),
    )
    cr.add_argument(
        "--evidence",
        action="append",
        default=None,
        help="Run artifact cited by this step, e.g. raw/job-run-output-<id>.json (repeatable)",
    )
    cr.add_argument(
        "--hypothesis",
        default=None,
        help="Hypothesis statement (at most 500 characters; no emails or credentials)",
    )
    cr.add_argument(
        "--hypothesis-id",
        default=None,
        help=(
            "Hypothesis to revise in place, e.g. h1 (default: a new one); without "
            "--hypothesis its stored statement is kept"
        ),
    )
    cr.add_argument(
        "--hypothesis-status",
        default=None,
        choices=HYPOTHESIS_STATES,
        help="New status (with --hypothesis-id alone: the stored hypothesis's)",
    )
    cr.add_argument(
        "--hypothesis-evidence",
        action="append",
        default=None,
        help="Evidence ID the hypothesis cites (repeatable). REPLACES the "
        "hypothesis's stored evidence with exactly these IDs; evidence this step "
        "registers (--evidence/--verify) is always added. Default: the stored list "
        "plus the evidence this step registers. Each ID must already be evidence "
        "of this run",
    )
    cr.add_argument(
        "--cause-confidence",
        default=None,
        choices=CAUSE_CONFIDENCE,
        help="Raise the finding's cause_confidence. Order: unassessed (the start, "
        "never passed) -> hypothesis -> supported; 'supported' needs a hypothesis "
        "with status supported that cites evidence. Omit to keep the current value",
    )
    cr.set_defaults(func=_entry(cmd_case_revise, "case revise"))

    cs = csp.add_parser("show", help="Print one case and its finding (read-only)")
    add_run_args(cs)
    cs.add_argument("--case-id", required=True)
    cs.set_defaults(func=_entry(cmd_case_show, "case show"))

    acp = sp.add_parser(
        "action", help="Propose a case action, or record a host event on an action"
    )
    asp = acp.add_subparsers(dest="action_command", required=True)
    ap = asp.add_parser(
        "propose",
        help="Propose the next step on a case's finding (after the cause; pending)",
    )
    add_run_args(ap)
    ap.add_argument("--case-id", required=True)
    ap.add_argument(
        "--next-step",
        required=True,
        help="The change to make (no emails or credentials)",
    )
    ap.add_argument("--owner-role", required=True, choices=OWNER_ROLES)
    ap.add_argument(
        "--owner-label", default=None, help="Who owns it (no emails or credentials)"
    )
    ap.add_argument(
        "--verify-method",
        default=None,
        help="How the outcome will be checked (no emails or credentials)",
    )
    ap.add_argument("--note", default=None, help="Free text (no emails or credentials)")
    ap.set_defaults(func=_entry(cmd_action_propose, "action propose"))
    commands = {
        "accept": cmd_action_accept,
        "reject": cmd_action_reject,
        "execute": cmd_action_execute,
        "withdraw": cmd_action_withdraw,
    }
    for verb, cmd in commands.items():
        av = asp.add_parser(verb, help=f"Mark an action {ACTION_EVENTS[verb]}")
        add_run_args(av)
        av.add_argument("--action-id", required=True)
        av.add_argument(
            "--note", default=None, help="Free text (no emails or credentials)"
        )
        if verb == "execute":
            av.add_argument(
                "--executed-at",
                default=None,
                help="When it was executed (ISO date/time)",
            )
        else:
            av.set_defaults(executed_at=None)
        av.set_defaults(func=_entry(cmd, f"action {verb}"))

    pp = sp.add_parser("play", help="Host ordering of the run's plays")
    psp = pp.add_subparsers(dest="play_command", required=True)
    pr = psp.add_parser(
        "rank", help="Record the host's rank of one play, with its reason"
    )
    add_run_args(pr)
    pr.add_argument("--play-id", required=True)
    pr.add_argument("--rank", required=True, type=int, help="1 = first")
    pr.add_argument("--reason", required=True, help="Why (no emails or credentials)")
    pr.set_defaults(func=_entry(cmd_play_rank, "play rank"))
