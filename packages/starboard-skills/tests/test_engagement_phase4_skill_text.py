# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-4 skill text: the health-review and troubleshoot entry skills are reachable from prompts.

Reuses the phase-2 D-28 extractor (``iter_commands`` / ``command_flag_errors``) so every phase-4
command written in a skill is checked against the real parser. It pins the rules the host must
see: the source choice before preflight, the two task flows (no forced plan, targeted evidence
only), the Drive-run delivery qualifiers, the engagement wiring, the auto agent's kernel records
and the public-text hygiene. (The overlay's internal-only leg is pinned in
``starboard-internal/tests/test_overlay_skill.py``; exit tests e11/e12/e14 pin reachability.)
"""

from __future__ import annotations

import importlib.util
import re
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_PKG = Path(__file__).parents[1]
_SKILLS = _PKG / "skills" / "starboard"
_SCAFFOLD = _SKILLS / "starboard-engagement"
_ENGAGEMENT = _SCAFFOLD / "SKILL.md"
_HEALTH = _SKILLS / "starboard-health-review" / "SKILL.md"
_TROUBLE = _SKILLS / "starboard-troubleshoot" / "SKILL.md"
_DELIVER = _SKILLS / "starboard-deliver" / "SKILL.md"
_BIND = _SCAFFOLD / "references" / "capability-bind.md"
_CHECKLIST = _SCAFFOLD / "references" / "run-checklist.md"
_CASE_TEMPLATE = _SCAFFOLD / "templates" / "case-report.md"
_AUTO = _PKG / "agents" / "starboard-workload-review-auto.yaml"
_ROUTED = tuple(
    _SKILLS / f"starboard-{n}" / "SKILL.md"
    for n in ("analyze", "discovery", "workload-review", "diagnostic", "job", "query")
)
_FILES = (_HEALTH, _TROUBLE, _ENGAGEMENT, _DELIVER, _BIND, _CHECKLIST, *_ROUTED)
_NEW_SKILLS = ("starboard-health-review", "starboard-troubleshoot")

_INTERNAL_TOKENS = re.compile(
    r"centralized_system_tables|fin_live_gold|logfood|dbr-doctor|logs-summariser|gtm_|eng_"
    r"|clickhouse|hmr_stack_hash",
    re.IGNORECASE,
)
_FORCED_PLAN = re.compile(r"~\s?8|\beight\b|min\(8|notebook per", re.IGNORECASE)

# (file, cli, sub-command words, a flag or token the command must carry)
_COMMANDS = (
    (_HEALTH, "starboard-helper", "engagement source-options", "--task health_check"),
    (_HEALTH, "starboard-helper", "engagement preflight", "--task health_check"),
    (_HEALTH, "starboard-helper", "engagement preflight", "--internal-workspace-id"),
    (
        _HEALTH,
        "starboard-helper",
        "engagement verify-identity",
        "--expected-workspace-id",
    ),
    (_HEALTH, "starboard-helper", "engagement route", "--run-id"),
    (_HEALTH, "starboard-helper", "engagement analyze", "--workspace-root"),
    (_HEALTH, "starboard-helper", "engagement play rank", "--reason"),
    (_HEALTH, "starboard-helper", "engagement action accept", "--action-id"),
    (_HEALTH, "starboard-helper", "engagement action reject", "--action-id"),
    (_HEALTH, "starboard-helper", "run recur", "--workspace-root"),
    (_HEALTH, "starboard-helper", "engagement report", "--report-id health-read"),
    (_HEALTH, "starboard-helper", "engagement history", "--run-folder"),
    (_HEALTH, "starboard-helper", "run recur", "--prior drive:<run_folder_id>"),
    (_HEALTH, "starboard-helper", "engagement status", "--run-id"),
    (_HEALTH, "starboard-helper", "run check", "--out"),
    (_HEALTH, "starboard-helper", "engagement commit", "--stage check"),
    (
        _TROUBLE,
        "starboard-helper",
        "engagement source-options",
        "--task troubleshooting",
    ),
    (_TROUBLE, "starboard-helper", "engagement preflight", "--task troubleshooting"),
    (_TROUBLE, "starboard-helper", "engagement preflight", "--internal-workspace-id"),
    (_TROUBLE, "starboard-helper", "engagement case open", "--clue"),
    (_TROUBLE, "starboard-helper", "engagement case open", "--clue query:<statement_id>"),
    (_TROUBLE, "starboard-helper", "engagement case open", "--clue pipeline:<pipeline_id>"),
    (_TROUBLE, "starboard-helper", "engagement case open", "--finding-id"),
    (_TROUBLE, "starboard-helper", "engagement case open", "--drive-object"),
    (_TROUBLE, "starboard-helper", "engagement case open", "--workspace-root"),
    (_TROUBLE, "starboard-helper", "engagement case show", "--case-id"),
    (_TROUBLE, "starboard-helper", "engagement case revise", "--cause-confidence"),
    (_TROUBLE, "starboard-helper", "engagement action execute", "--executed-at"),
    (_TROUBLE, "starboard-helper", "job run-output", "--run-id"),
    (_TROUBLE, "starboard-helper", "query fetch", "--query-id"),
    (_TROUBLE, "starboard-helper", "query slow", "--warehouse-id"),
    (_TROUBLE, "starboard-helper", "query history", "--status FAILED"),
    (_TROUBLE, "starboard-helper", "job list", "--limit"),
    (_TROUBLE, "starboard-helper", "pipeline fetch", "--pipeline-id"),
    (_TROUBLE, "starboard-helper", "pipeline updates", "--pipeline-id"),
    (_TROUBLE, "starboard-helper", "pipeline events", "--update-id"),
    (_TROUBLE, "starboard-helper", "diagnostic cluster-log", "--cluster-id"),
    (_TROUBLE, "starboard-helper", "engagement read", "--path raw/<name>.json"),
    (_TROUBLE, "starboard_x.diagnostic", "profile", "--input"),
    (_TROUBLE, "starboard_x.sparklog", "parse", "--input"),
    (_TROUBLE, "starboard_x.diff", "settings", "--a"),
    (_TROUBLE, "starboard_x.diff", "metrics", "--b"),
    (_TROUBLE, "starboard-helper", "run check", "--out"),
    (_ENGAGEMENT, "starboard-helper", "engagement source-options", "--task"),
    (_ENGAGEMENT, "starboard-helper", "engagement analyze", "--workspace-root"),
    (_ENGAGEMENT, "starboard-helper", "engagement case open", "--workspace-root"),
    (_DELIVER, "starboard-helper", "engagement report", "--derived-from"),
)


@cache
def _d28() -> ModuleType:
    path = Path(__file__).with_name("test_engagement_phase2_skill_text.py")
    spec = importlib.util.spec_from_file_location("_phase2_skill_text_for_phase4", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".yaml":
        data = yaml.safe_load(raw)
        return f"{data.get('description', '')}\n{data.get('body', '')}"
    return raw


def _flat(text: str) -> str:
    return " ".join(text.split())


def _segments(path: Path) -> list[tuple[str, str, str]]:
    return [
        (cli, " ".join(words), seg.replace("\\\n", " "))
        for cli, words, seg in _d28().iter_commands(path, _text(path))
    ]


def _label(p: Path) -> str:
    return p.parent.name if p.name == "SKILL.md" else f"{p.parent.name}/{p.name}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "cli", "words", "token"),
    _COMMANDS,
    ids=lambda v: _label(v) if isinstance(v, Path) else str(v).strip(),
)
def test_skill_names_the_phase4_command(
    path: Path, cli: str, words: str, token: str
) -> None:
    found = [seg for c, w, seg in _segments(path) if c == cli and w == words]
    assert any(token in seg for seg in found), (
        f"{_label(path)}: no `{cli} {words} … {token}`"
    )


@pytest.mark.unit
@pytest.mark.parametrize("path", (*_FILES, _AUTO), ids=_label)
def test_every_named_flag_exists(path: Path) -> None:
    errors = _d28().command_flag_errors(path, _text(path))
    assert not errors, "\n".join(errors)


@pytest.mark.unit
@pytest.mark.parametrize("path", (_HEALTH, _TROUBLE), ids=_label)
def test_entry_skill_loads_the_engagement_and_asks_the_source_first(path: Path) -> None:
    body = _flat(_text(path))
    assert "Load [`starboard-engagement`]" in body
    source = body.find("starboard-helper engagement source-options")
    preflight = body.find("starboard-helper engagement preflight")
    assert 0 <= source < preflight, (
        f"{_label(path)}: source-options is not before preflight"
    )
    assert "choice_required" in body
    assert "Never choose silently" in body
    assert "--source-mode" in body


@pytest.mark.unit
@pytest.mark.parametrize("path", (_HEALTH, _TROUBLE), ids=_label)
def test_entry_skill_forces_no_plan(path: Path) -> None:
    hits = _FORCED_PLAN.findall(_text(path))
    assert not hits, f"{_label(path)} forces an action plan: {hits}"


@pytest.mark.unit
def test_health_review_flow() -> None:
    body = _flat(_text(_HEALTH))
    for phrase in (
        "weekly",
        "monthly (the default)",
        "QBR",
        "the previous quarter as the baseline",
        "analysis/health.json",
        "analysis/plays.json",
        "deliverables/health-read.md",
        "Insufficient evidence",
        "## Unknowns",
        "- <family>: unknown",
        "engagement history",
        "engagement status",
        "starboard-troubleshoot",
        "--finding-id <finding_id>",
        "**offer** (never start)",
        "list-price DBU estimates",
    ):
        assert phrase in body, phrase
    report = body.find("--report-id health-read")
    check = body.find("starboard-helper run check --run-folder $RUN_FOLDER")
    assert 0 <= report < check, "the health read is not registered before run check"
    assert "action-plan deliverable set" not in body.replace(
        "no action-plan deliverable set", ""
    )


@pytest.mark.unit
def test_health_review_window_is_the_discovery_lookback() -> None:
    body = _flat(_text(_HEALTH))
    for phrase in (
        "`--lookback-days 7` on a weekly run",
        "`30` on a monthly or proactive run",
        "`90` on a QBR run",
        "every family shares one window",
    ):
        assert phrase in body, phrase
    for cli, words, seg in _segments(_HEALTH):
        if cli == "starboard-helper" and words in ("engagement analyze", "run recur"):
            assert "--interval-" not in seg, f"`{words}` passes its own interval: {seg}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "deliverable"),
    (
        (_HEALTH, "deliverables/health-read.md"),
        (_TROUBLE, "deliverables/case-report.md"),
    ),
    ids=lambda v: _label(v) if isinstance(v, Path) else str(v),
)
def test_readme_delivery_line_is_in_place_before_run_check(
    path: Path, deliverable: str
) -> None:
    text = _text(path)
    block = f"## Delivery\n\n- {deliverable}\n"
    at = text.find(block)
    assert at >= 0, (
        f"{_label(path)}: no README `## Delivery` block naming {deliverable}"
    )
    check = text.find("starboard-helper run check --run-folder $RUN_FOLDER", at)
    assert check > at, f"{_label(path)}: the ## Delivery line is not before run check"
    body = _flat(text)
    assert not re.search(r"\bpending\b|\bTBD\b|\(filled at delivery\)", block)
    assert f"replace the `- {deliverable}` line with the delivery outcomes" in body


@pytest.mark.unit
def test_troubleshoot_evidence_is_saved_into_the_drive_run() -> None:
    body = _flat(_text(_TROUBLE))
    assert "On a Drive run never save helper stdout with Write" in body
    fetches = {
        ("job", "fetch"),
        ("job", "runs"),
        ("job", "run-output"),
        ("job", "code"),
        ("query", "fetch"),
        ("query", "slow"),
        ("query", "history"),
        ("job", "list"),
        ("pipeline", "fetch"),
        ("pipeline", "updates"),
        ("pipeline", "events"),
        ("serving", "fetch"),
        ("diagnostic", "driver-log"),
        ("diagnostic", "cluster-log"),
    }
    seen = set()
    for cli, words, seg in _segments(_TROUBLE):
        key = tuple(words.split())
        if cli == "starboard-helper" and key in fetches:
            seen.add(key)
            assert "--run-folder $RUN_FOLDER" in seg and "--out raw/" in seg, seg
            # Every fetch reads as the run's verified workspace profile.
            assert "--profile <profile>" in seg, seg
    assert seen == fetches, sorted(fetches - seen)


@pytest.mark.unit
def test_troubleshoot_flow_is_targeted() -> None:
    text = _text(_TROUBLE)
    body = _flat(text)
    for phrase in (
        "internal_only",
        "- customer workspace: not acquired (no customer profile)",
        "--drive-object drive:<file_id>",
        "(Drive runs only)",
        "deliverables/case-report.md",
        "templates/case-report.md",
        "not applicable: troubleshooting run",
        "Unknowns",
        "starboard-health-review",
        "list-price DBU estimates",
        "`--clue pipeline:<pipeline_id>`",
        "`vt-pipeline-updates` with `--pipeline-ids <pipeline_id>`",
        "`vt-endpoint-daily` and `vt-endpoint-config-history` with `--endpoint-ids <endpoint_id>`",
        "rather than hand-written SQL",
    ):
        assert phrase in body, phrase
    clis = {(c, w) for c, w, _ in _segments(_TROUBLE)}
    assert not any(c == "starboard" and "--discover" in w for c, w in clis)
    assert "starboard --discover" not in text
    assert "analysis/backlog.json" not in text


_SCOPE_NAMES = (
    "`--task-name queries-<workspace_id>`",
    "`warehouse-<warehouse_id>`",
    "`jobs-<workspace_id>`",
)


@pytest.mark.unit
def test_troubleshoot_without_a_target_names_the_run_after_the_scope() -> None:
    body = _flat(_text(_TROUBLE))
    for phrase in (
        "**No target id yet.**",
        "don't open a case on the scope",
        "find the target inside the run",
        *_SCOPE_NAMES,
    ):
        assert phrase in body, phrase
    # The search lands in the run before the case opens on what it found.
    assert body.index("query slow --warehouse-id") < body.index(
        "case open --run-folder $RUN_FOLDER --clue query:<statement_id>"
    )
    # A run never opens a case on the scope itself.
    assert not re.search(r"--clue (warehouse|queries|jobs):", body)


@pytest.mark.unit
def test_query_skill_troubleshoots_a_scope_by_finding_the_statement() -> None:
    body = _flat(_text(_SKILLS / "starboard-query" / "SKILL.md"))
    for phrase in (*_SCOPE_NAMES[:2], "--clue query:<statement_id>"):
        assert phrase in body, phrase


@pytest.mark.unit
def test_case_report_template_has_the_required_sections() -> None:
    body = _text(_CASE_TEMPLATE)
    for heading in (
        "## Symptom",
        "## Evidence",
        "## Cause",
        "## Next step",
        "## Unknowns",
    ):
        assert heading in body, heading
    assert "cause_confidence" in body
    assert "customer workspace: not acquired (no customer profile)" in body


@pytest.mark.unit
@pytest.mark.parametrize("path", (_DELIVER, _BIND), ids=_label)
def test_drive_runs_get_no_local_fallback(path: Path) -> None:
    body = _flat(_text(path))
    for phrase in (
        "not delivered: <reason>",
        "only when `allowed_audiences` includes `customer`",
    ):
        assert phrase in body, f"{_label(path)}: {phrase}"
    assert "customer_eligible" not in body, (
        f"{_label(path)}: the dropped customer_eligible key"
    )
    # Run 9: the manifest is no run file; the state is `engagement status`'s field.
    assert "data.states.publication" in body, _label(path)


@pytest.mark.unit
def test_engagement_wires_the_two_tasks() -> None:
    body = _flat(_text(_ENGAGEMENT))
    for phrase in (
        "starboard-helper engagement source-options --task <task>",
        "choice_required",
        "- customer workspace: not acquired (no customer profile)",
        "skipped_by_profile",
        "deliverables/health-read.md",
        "deliverables/case-report.md",
        "OUTSIDE_RUN_DIR",
        *_NEW_SKILLS,
    ):
        assert phrase in body, phrase


@pytest.mark.unit
def test_run_checklist_describes_the_profiles() -> None:
    body = _flat(_text(_CHECKLIST))
    for phrase in (
        "action_plan",
        "health_check",
        "troubleshooting",
        "skipped_by_profile",
        "deliverables/health-read.md",
        "deliverables/case-report.md",
    ):
        assert phrase in body, phrase


@pytest.mark.unit
@pytest.mark.parametrize("path", _ROUTED, ids=_label)
def test_focused_skills_route_to_the_two_tasks(path: Path) -> None:
    body = _text(path)
    for skill in _NEW_SKILLS:
        assert f"[`{skill}`](../{skill}/SKILL.md)" in body, f"{_label(path)}: {skill}"


@pytest.mark.unit
def test_auto_agent_names_the_local_kernel_records() -> None:
    body = _flat(_text(_AUTO))
    assert (
        "analysis/{observations,findings,health,plays,changes,cases,actions}.json"
        in body
    )
    assert "no opt-out" in body
    assert "health verdict line" in body
    assert (
        "starboard-helper engagement analyze --run-dir <run-dir> --workspace-root <case-root>"
        in body
    )


@pytest.mark.unit
def test_public_text_is_clean() -> None:
    text = "\n".join(_text(p) for p in (*_FILES, _CASE_TEMPLATE, _AUTO))
    hits = sorted(set(_INTERNAL_TOKENS.findall(text)))
    assert not hits, f"internal tokens in phase-4 public text: {hits}"
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), (
        "an email address in public text"
    )
    ar_keys = set(re.findall(r"\bAR-\d+\b", text))
    assert ar_keys <= {"AR-000000001", "AR-000000002", "AR-000000003"}, ar_keys


# drive_optional (a public install where the operator chose `--storage drive`) is a Drive run:
# route returns a run folder and no local_run_dir. Local is `local` / `internal_only_local` only.
_STORAGE_TEXTS = tuple(
    sorted(
        [
            *_SKILLS.rglob("*.md"),
            *(_PKG / "agents").glob("*.yaml"),
            *(_PKG.parent / "starboard-internal" / "skills").rglob("*.md"),
        ]
    )
)
_PAREN = re.compile(r"\(([^()]*)\)")
_LOCAL_WORD = re.compile(r"(?<![\w-])(?:internal_only_)?local(?![\w-])")
_LOCAL_OR_OPTIONAL = re.compile(
    r"`local`\**\s*(?:or|/|,)\s*\**`drive_optional`"
    r"|`drive_optional`\**\s*(?:or|/|,)\s*\**`(?:internal_only_)?local`"
    r"|(?<![\w`-])local\s*/\s*drive_optional(?![\w`-])"
)


def drive_optional_local_pairings(text: str) -> list[str]:
    """Every place ``text`` files drive_optional under a local run."""
    flat = _flat(text)
    hits = [m.group(0) for m in _LOCAL_OR_OPTIONAL.finditer(flat)]
    hits += [
        f"({inner})"
        for inner in _PAREN.findall(flat)
        if "drive_optional" in inner
        and _LOCAL_WORD.search(inner)
        and "Drive run" not in inner
    ]
    hits += re.findall(r"drive_optional[^.;]{0,60}local_run_dir", flat)
    return hits


@pytest.mark.unit
def test_the_pairing_guard_catches_the_old_wording() -> None:
    for old in (
        "- **`local`** or **`drive_optional`** (a public install): `data.local_run_dir` is",
        "- **Local run** (`local` / `drive_optional`): write `<run-dir>/analysis/uc.md`",
        "# Local run (local / drive_optional)",
    ):
        assert drive_optional_local_pairings(old), old
    ok = "a local run (public install, `local`; never `drive_optional`, which is a Drive run)"
    assert not drive_optional_local_pairings(ok)


@pytest.mark.unit
@pytest.mark.parametrize("path", _STORAGE_TEXTS, ids=_label)
def test_drive_optional_is_never_a_local_run(path: Path) -> None:
    hits = drive_optional_local_pairings(_text(path))
    assert not hits, f"{_label(path)} files drive_optional under a local run: {hits}"
    body = _text(path)
    public = "starboard-internal" not in path.parts  # the overlay is never public
    if (
        public
        and "drive_required" in body
        and "local_run_dir" in body
        and "storage_decision" in body
    ):
        assert "drive_optional" in body, (
            f"{_label(path)} routes Drive and local runs but never names drive_optional"
        )


# preflight emits `storage_decision` as the StoragePolicy value: the lowercase JSON string.
_UPPER_DECISION = re.compile(
    r"(?<![\w-])(?:LOCAL|DRIVE_OPTIONAL|DRIVE_REQUIRED|DRIVE_DEFAULT|INTERNAL_ONLY_LOCAL)(?![\w-])"
)


@pytest.mark.unit
def test_storage_decisions_are_the_emitted_values() -> None:
    from starboard_core.engagement.policy import StoragePolicy

    assert {p.value for p in StoragePolicy} == {
        "local",
        "drive_optional",
        "drive_required",
        "drive_default",
        "internal_only_local",
    }


@pytest.mark.unit
@pytest.mark.parametrize("path", _STORAGE_TEXTS, ids=_label)
def test_storage_decisions_are_quoted_as_emitted(path: Path) -> None:
    hits = sorted(set(_UPPER_DECISION.findall(_text(path))))
    assert not hits, f"{_label(path)} names storage decisions not as emitted: {hits}"


# One account key rule on every surface: every preflight / import-local / rebuild-index line
# names the same placeholders, so no skill can teach a different key for the same account.
_ACCOUNT_TEXTS = tuple(
    sorted(
        [*_SKILLS.glob("starboard-*/SKILL.md"), *(_PKG / "agents").glob("*.yaml")],
        key=lambda p: p.as_posix(),
    )
)
_ACCOUNT_KEY = re.compile(r"--account-key\s+([^\s`;,.)]+)")
_ACCOUNT_NAME = re.compile(r'--account-name\s+("[^"]*"|\S+)')


@pytest.mark.unit
@pytest.mark.parametrize("path", _ACCOUNT_TEXTS, ids=lambda p: p.parent.name + "/" + p.name)
def test_account_placeholders_follow_the_one_rule(path: Path) -> None:
    text = path.read_text()
    keys = set(_ACCOUNT_KEY.findall(text)) - {"<account_key>"}
    names = set(_ACCOUNT_NAME.findall(text)) - {'"<account name>"'}
    assert not keys and not names, f"{path.name}: other account placeholders {keys | names}"


@pytest.mark.unit
def test_engagement_states_the_account_key_rule() -> None:
    text = " ".join(_ENGAGEMENT.read_text().split())
    assert "the account key rule" in text
    assert "At preflight use the key the operator gave; else the WORKSPACE ID" in text
    assert "else the verified account ID" not in text
    assert "account_name_differs" in text


@pytest.mark.unit
@pytest.mark.parametrize("path", (_HEALTH, _TROUBLE, _ENGAGEMENT), ids=_label)
def test_the_source_question_is_the_helpers(path: Path) -> None:
    # Run 7: a host asked its own source question and left out each option's
    # storage. source-options now emits the question; the skills ask it as is.
    body = _flat(_text(path))
    assert "`data.question`" in body, _label(path)
    assert "customer workspace too?" not in body, _label(path)


@pytest.mark.unit
def test_troubleshoot_lookback_follows_the_operator() -> None:
    # Run 7: "pass it, e.g. 7, for 'recent'" fought an operator who said "Defaults".
    body = _flat(_text(_TROUBLE))
    assert "e.g. 7" not in body
    assert "the operator's answer wins" in body


@pytest.mark.unit
def test_a_query_case_without_a_profile_stays_a_hypothesis() -> None:
    # Run 7: metrics alone raised a query case's cause_confidence to supported.
    body = _flat(_text(_TROUBLE))
    assert "no query profile" in body
    assert "keep `--cause-confidence hypothesis`" in body
    assert "any fetch that fails with not found" in body.lower()


@pytest.mark.unit
@pytest.mark.parametrize("path", (_HEALTH, _TROUBLE, _ENGAGEMENT), ids=_label)
def test_a_scripted_non_interactive_prompt_is_attended(path: Path) -> None:
    # Run 7: hosts split on whether "non-interactive" means --unattended.
    body = _flat(_text(path))
    assert '"Non-interactive" or "nobody will answer"' in body, _label(path)


@pytest.mark.unit
@pytest.mark.parametrize("path", (_HEALTH, _TROUBLE), ids=_label)
def test_investigate_names_the_real_play_codes(path: Path) -> None:
    # Run 7: "a play is `investigate`" — no play has that code; it is next_step_kind.
    body = _flat(_text(path))
    for phrase in (
        "`next_step_kind: investigate`",
        "`job_reliability_investigation`",
        "`rule_finding_review`",
    ):
        assert phrase in body, f"{_label(path)}: {phrase}"


@pytest.mark.unit
@pytest.mark.parametrize("path", (_HEALTH, _TROUBLE), ids=_label)
def test_a_delivered_report_writes_about_not_a_tilde(path: Path) -> None:
    # Run 7: the read was written with "~449 DBU" and delivered unchanged, which
    # capability-bind Rule 1 forbids in a Doc.
    body = _flat(_text(path)).lower()
    assert '"about" for an approximate figure, never `~`' in body, _label(path)


@pytest.mark.unit
def test_run7_output_shapes_are_documented() -> None:
    # Run 7: hosts probed for these paths; each is what the helper returns.
    health = _flat(_text(_HEALTH))
    trouble = _flat(_text(_TROUBLE))
    engagement = _flat(_text(_ENGAGEMENT))
    for phrase in (
        "`$.data.warehouses[*].id`",
        "`data.excerpt`",
        "`--jsonpath` is repeatable",
        "`no_observations` or null",
        "`data.warnings`",
        "A host rank belongs to this run only",
    ):
        assert phrase in health, phrase
    for phrase in (
        "`$.data.slow_queries`",
        "`error_trace`, `logs`",
        "there is no `metadata`",
        "`pipeline updates` (the API) can list fewer updates",
        "`data.warnings`",
    ):
        assert phrase in trouble, phrase
    for phrase in (
        "a number, not a list",
        "The printed lists stop at 50 items",
        "`data.warnings`",
        "A host rank belongs to this run only",
    ):
        assert phrase in engagement, phrase


@pytest.mark.unit
def test_a_serving_finding_has_a_template_and_a_config_read() -> None:
    # Run 7: a serving step-change was verified with hand-written SQL and the endpoint's
    # scale-to-zero setting was never read. Step 4 names the templates and the verb.
    body = _flat(_text(_TROUBLE))
    for phrase in (
        "starboard-helper serving fetch --endpoint-id <endpoint_id>",
        "`scale_to_zero_enabled`",
        "`usage_metadata.endpoint_id`",
        "a day with no row had no billed usage",
    ):
        assert phrase in body, phrase
