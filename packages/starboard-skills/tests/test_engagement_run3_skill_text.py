# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live-run-3 skill text: the engagement contract the skills state matches the helpers.

Pins the exit-8 / ``ACCOUNT_NAME_TAKEN`` rows, the one account-key rule (workspace id at
preflight, never the account name), the ``engagement read`` paging/slicing contract, the
troubleshoot items (``ws-<workspace_id>``, ``--evidence`` for non-job verify results,
``effective_rank``) and the verify-sql end-date wording.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starboard_skills.helpers.query import _MAX_ROW_LIMIT
from starboard_skills.helpers.verify import VERIFY_ROW_LIMIT

_PKG = Path(__file__).parents[1]
_SKILLS = _PKG / "skills" / "starboard"
_ENGAGEMENT = _SKILLS / "starboard-engagement" / "SKILL.md"
_TROUBLE = _SKILLS / "starboard-troubleshoot" / "SKILL.md"
_HEALTH = _SKILLS / "starboard-health-review" / "SKILL.md"
_VERIFY_SQL = _SKILLS / "starboard-engagement" / "references" / "verify-sql.md"
_OVERLAY = _PKG.parent / "starboard-internal" / "skills" / "starboard-internal-overlay" / "SKILL.md"


def _text(path: Path) -> str:
    return " ".join(path.read_text().split())


@pytest.mark.unit
def test_engagement_exit_table_has_the_transient_row_and_retry_rule() -> None:
    raw = _ENGAGEMENT.read_text()
    assert re.search(r"^\s*\| 6 \| `WORKSPACE_API_ERROR`", raw, re.MULTILINE)
    assert re.search(r"^\s*\| 8 \| `STORAGE_TRANSIENT`", raw, re.MULTILINE)
    text = _text(_ENGAGEMENT)
    assert "With exit 8, or any `errors[0].retryable: true`, retry the same command once" in text
    assert "if it fails again, stop and record it" in text


@pytest.mark.unit
@pytest.mark.parametrize("path", [_ENGAGEMENT, _TROUBLE, _HEALTH], ids=lambda p: p.parent.name)
def test_skills_state_account_name_taken(path: Path) -> None:
    text = _text(path)
    assert "ACCOUNT_NAME_TAKEN" in text
    assert "engagement preflight` with `--account-key` set to the key the message names" in text
    assert "never merge" in text.lower()


@pytest.mark.unit
@pytest.mark.parametrize("path", [_ENGAGEMENT, _TROUBLE, _HEALTH], ids=lambda p: p.parent.name)
def test_account_key_rule_is_workspace_id_never_the_name(path: Path) -> None:
    text = _text(path)
    assert "use the key the operator gave; else the workspace id" in text.lower()
    assert "never use the account name as the key" in text.lower()
    assert "account_key_looks_like_name:" in text
    assert "verify-identity` runs after preflight" in text
    assert "the key never changes mid-run" in text
    assert "else the verified account ID" not in text


@pytest.mark.unit
def test_overlay_key_rule_uses_the_account_id_it_resolves_before_preflight() -> None:
    """The overlay resolves the account before preflight, so its ID can be the key."""
    if not _OVERLAY.exists():
        pytest.skip("internal overlay not present")
    text = " ".join(_text(_OVERLAY).split())
    assert "At preflight use the key the operator gave; else the " in text
    assert "account ID resolved in this step (it exists before preflight); else ask the operator" in text
    # 2026-10-22: a workspace-id key split a customer's history from its account-key run.
    assert "the Salesforce account ID and name" in text
    assert "else, when they have none, the WORKSPACE ID." in text
    assert "Never use the account name as the key" in text
    assert "account_key_looks_like_name:" in text
    assert "The key never changes mid-run" in text


@pytest.mark.unit
def test_engagement_read_contract() -> None:
    text = _text(_ENGAGEMENT)
    assert "`--jsonpath` is repeatable" in text
    assert "an object keyed by each expression" in text
    assert "prefer ONE read with several `--jsonpath` slices" in text
    assert "`--offset <bytes>`" in text and "`next_offset` (null at end of file)" in text
    assert "default `--max-bytes` is the cap" in text and "a plain read does not warn" in text
    assert "no local `--out`" in text


@pytest.mark.unit
def test_case_show_and_idempotent_actions_are_documented() -> None:
    text = _text(_ENGAGEMENT)
    assert "`evidence_paths`" in text
    assert 'already: "<state>"' in text and "idempotent" in text
    assert 'already: "<state>"' in _text(_TROUBLE)


@pytest.mark.unit
def test_troubleshoot_run3_items() -> None:
    text = _text(_TROUBLE)
    assert "`--task-name ws-<workspace_id>`" in text and "`workspace-<id>` is refused" in text
    # --verify is job run-states only; anything else is cited with --evidence
    assert "`--verify <path>` accepts only a job run-state verify result" in text
    assert "(`vt-job-run-states`)" in text and "with `--evidence <path>`" in text
    assert "verify run vt-warehouse-queue" in text and "--warehouse-ids <target_warehouse_id>" in text
    assert "--hypothesis-id h1 --hypothesis-status refuted" in text and "reuses the stored statement" in text
    assert "lowest `effective_rank`" in text
    assert "ask for a clue instead" in text
    assert "applies only on an `internal_only` or `hybrid` run" in text
    # verify run reads the bundled verify-sql.md by default: no --templates path to resolve
    assert "pass no `--templates` on the public path" in text
    assert "<starboard-engagement-dir>" not in text
    assert "`STORAGE_TRANSIENT`" in text and "retry the same command once" in text


@pytest.mark.unit
def test_verify_sql_end_date_matches_the_cli() -> None:
    text = _text(_VERIFY_SQL)
    assert "with `{end}` before today" not in text
    assert "accepts today as `--end`" in text
    assert "a window ending today includes today's partial data" in text


# ---------------------------------------------------------------------------
# Group C2: health-review flow, digest, exposure, recur, verify cap, discovery summary
# ---------------------------------------------------------------------------

_CHECKLIST = _SKILLS / "starboard-engagement" / "references" / "run-checklist.md"
_DOMAINS = "jobs,sql,warehouse,uc,portfolio-readiness"


def _phase2():
    import importlib.util

    path = Path(__file__).with_name("test_engagement_phase2_skill_text.py")
    spec = importlib.util.spec_from_file_location("_phase2_for_run3", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _commands(path: Path, prefix: str) -> list[str]:
    """Each command in ``path`` that starts with ``prefix``, joined across ``\\`` continuations."""
    out, cur = [], None
    for line in path.read_text().splitlines():
        if cur is None and line.lstrip().startswith(prefix):
            cur = line.strip()
        elif cur is not None:
            cur += " " + line.strip()
        if cur is not None and not cur.endswith("\\"):
            out.append(" ".join(cur.replace("\\", " ").split()))
            cur = None
        elif cur is not None:
            cur = cur[:-1].rstrip()
    return out


@pytest.mark.unit
def test_health_domains_match_the_kernel_constant() -> None:
    from starboard_core.engagement.health import HEALTH_REVIEW_DOMAINS, REVIEW_COMMAND

    assert HEALTH_REVIEW_DOMAINS == _DOMAINS
    assert f"--domains {_DOMAINS}" in REVIEW_COMMAND


@pytest.mark.unit
def test_every_health_review_line_passes_the_governance_domains() -> None:
    reviews = _commands(_HEALTH, "starboard review")
    assert len(reviews) == 3, reviews  # Drive, local, internal_only_local
    for line in reviews:
        assert f"--domains {_DOMAINS}" in line, line
    by_form = {
        "drive": [r for r in reviews if "--run-folder" in r],
        "local": [r for r in reviews if "--run-folder" not in r and "--run-dir" not in r],
        "internal": [r for r in reviews if "--run-dir <run-dir>" in r],
    }
    assert all(len(v) == 1 for v in by_form.values()), by_form
    text = _text(_HEALTH)
    assert "`not_reviewed:<domains>`" in text
    assert "which the default domains (`jobs,sql,warehouse`) do not run" in text
    # the capture is committed once, right after discovery and before the review
    drive = text.find("--stage capture")
    assert text.find("starboard --discover --profile") < drive
    assert drive < text.find("starboard review --from-discovery discovery")


@pytest.mark.unit
def test_health_review_commits_and_checks_are_the_minimum_flow() -> None:
    text = _text(_HEALTH)
    assert "**Commit before every `run check`**" in text
    assert "exactly these commits and checks, no others" in text
    # no analysis commit before Step 6: one capture, one analysis, one check, one check
    raw = _HEALTH.read_text()
    assert _text(_HEALTH).count("--stage capture") >= 2  # the Step 3 line and the flow list
    step4 = raw.split("## Step 4", 1)[1].split("## Step 5", 1)[0]
    assert "engagement commit" not in step4.split("Do not commit here", 1)[0]
    assert "Do not commit here: the one analysis commit is in Step 6" in text
    step6 = raw.split("## Step 6", 1)[1].split("## Step 7", 1)[0]
    assert step6.count("--stage analysis") >= 1
    assert step6.index("--stage analysis") < step6.index("run check --run-folder")
    assert "one more `--stage check` commit after a customer version's put" in text
    assert "a last `--stage check` commit" in text
    assert "This is the last `--stage check` commit" in text


@pytest.mark.unit
def test_health_review_goes_internal_only_directly_without_a_profile() -> None:
    text = _text(_HEALTH)
    assert "Skip the question when the prompt already settles it" in text
    assert "preflight `internal_only` directly" in text
    assert "record the missing customer leg under `## Unknowns`" in text
    assert "If you know that before preflight" in text


@pytest.mark.unit
def test_discovery_status_and_failures_are_in_the_stdout_summary() -> None:
    for path in (_HEALTH, _ENGAGEMENT):
        text = _text(path)
        assert "`data.failed`" in text and "`[{query_id, pack, error}]`" in text
    assert "`summary.failed`" in _text(_ENGAGEMENT)
    assert "`summary.packs_with_gaps`" in _text(_ENGAGEMENT)
    assert "`data.status` in the stdout summary" in _text(_HEALTH)


@pytest.mark.unit
def test_digest_keys_are_the_emitted_keys() -> None:
    from types import SimpleNamespace

    from starboard_skills.helpers.engagement.analysis_cmds import play_digest

    play = SimpleNamespace(
        play_id="p", play_code="c", interaction_type="i", next_step_kind="act",
        target_entity_kind="job", target_entity_id="1", finding_ids=("f",), urgency="high",
        exposure={}, host_rank=None, reason="r", next_commands=[],
    )
    keys = set(play_digest(1, play, "high"))
    for path in (_HEALTH, _ENGAGEMENT):
        text = _text(path)
        for key in keys:
            assert f"`{key}`" in text, (path.parent.name, key)
        assert "`plays_by_code`" in text and "`observations_by_family`" in text
        assert "lowest `effective_rank`" in text or "the lowest `effective_rank`" in text
    assert "up to 10" in _text(_HEALTH) and "Do not re-read" in _text(_HEALTH)


@pytest.mark.unit
def test_exposure_dbus_vs_failed_run_dbus() -> None:
    for path in (_HEALTH, _ENGAGEMENT):
        text = _text(path)
        assert "exposure_dbus" in text
        assert "`failed_run_dbus`" in text
        assert "job-failure rules" in text
    assert "is never an estimate for another kind of rule" in _text(_ENGAGEMENT)
    # the old, wrong wording is gone
    assert "`exposure` (`failed_runs`, `failed_run_dbus` in DBU)" not in _text(_ENGAGEMENT)


@pytest.mark.unit
def test_play_next_commands_are_task_aware() -> None:
    for path in (_HEALTH, _ENGAGEMENT):
        text = _text(path)
        assert "no `job fetch` command" in text
        assert "`, plus `--templates ~/<overlay skill path>/mirror-verify.md`" in text
        assert "<overlay-dir>" not in text


@pytest.mark.unit
def test_recur_comparable_false_interval_overlap_and_delta() -> None:
    for path in (_HEALTH, _ENGAGEMENT):
        text = _text(path)
        assert "interval_overlap" in text
        assert "`comparable: false`" in text
        assert "`outcome_state`" in text
        assert "delta-vs-<prior_date>.md" in text or "delta-vs-<prior-date>.md" in text
    health = _text(_HEALTH)
    assert "A health check has no backlog" in health
    assert "README `- Delta:` line" in health
    assert "keyed on `(run_date, run)`" in health and "keyed on `(run_date, run)`" in _text(_ENGAGEMENT)
    engagement = _text(_ENGAGEMENT)
    for key in ("prior_run_date", "history_entry", "prior_entry", "delta_path", "delta_counts"):
        assert f"`{key}`" in engagement, key
    assert "`window.prior_run_id`" in engagement


@pytest.mark.unit
def test_since_inside_the_case_root_on_internal_only_local() -> None:
    for path in (_HEALTH, _ENGAGEMENT):
        text = _text(path)
        assert "findings-manifest.json" in text and "same case root" in text
    assert "`LOCAL_FILE_INTAKE_REFUSED`" in _text(_ENGAGEMENT)


@pytest.mark.unit
def test_verify_cap_and_limit_flags_are_consistent() -> None:
    text = _text(_ENGAGEMENT)
    assert (f"{VERIFY_ROW_LIMIT} for `verify run` and {_MAX_ROW_LIMIT} for `query sql`") in text
    assert "`requested_limit`" in text and "`limit_capped: true`" in text
    for path in (_ENGAGEMENT, _VERIFY_SQL, _TROUBLE, _OVERLAY):
        if not path.exists():
            continue
        for line in _commands(path, "starboard-helper verify run"):
            for n in re.findall(r"--limit (\d+)", line):
                assert int(n) <= VERIFY_ROW_LIMIT, (path.name, line)
        for line in _commands(path, "starboard-helper query sql"):
            for n in re.findall(r"--limit (\d+)", line):
                assert int(n) <= _MAX_ROW_LIMIT, (path.name, line)


@pytest.mark.unit
def test_item_16_on_drive_is_generic_wording_only() -> None:
    assert "On a Drive run item 16 checks generic wording only" in _text(_CHECKLIST)
    assert "On a Drive run item 16 checks generic wording only" in _text(_HEALTH)


@pytest.mark.unit
@pytest.mark.parametrize("path", [_HEALTH, _ENGAGEMENT, _TROUBLE, _OVERLAY], ids=lambda p: p.parent.name)
def test_new_command_lines_match_the_real_parsers(path: Path) -> None:
    if not path.exists():
        pytest.skip("internal overlay not present")
    assert _phase2().command_flag_errors(path, path.read_text()) == []


@pytest.mark.unit
def test_run5_skill_text_contract() -> None:
    """Run-5 outcomes the skills state: cases, read, status, baseline, suppressed rules."""
    trouble, engagement, health = _text(_TROUBLE), _text(_ENGAGEMENT), _text(_HEALTH)
    for text in (trouble, engagement):
        assert "keeps its position in `hypotheses[]`" in text
        assert "`evidence_from_run`" in text
        assert "`<category>/<exception>[:<code>]`" in text
    assert "always joins the targeted hypothesis" in trouble
    assert "`truncated_paths`" in engagement and "at most 50 `--jsonpath`" in engagement
    assert "`RUN_ID_MISMATCH`" in engagement
    for text in (engagement, health):
        assert '`not_comparable_reason: "baseline"`' in text or '`"baseline"`' in text
        assert "(not compared)" in text
    assert "suppressed:<rule_id>[:missing_column:<col>]" in engagement
    assert "`acquisition_request` is null" in engagement
    assert "`STARBOARD_OVERLAY_DIR`" in engagement and "`STARBOARD_OVERLAY_DIR`" in _text(_OVERLAY)
    assert "suppressed:<rule_id>[:missing_column:<col>]" in _text(_OVERLAY)
