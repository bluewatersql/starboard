# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Contract: the engagement layer is a composable, host-led scaffold — not a monolith.

The engagement capability is deliberately structured as a shared scaffold skill
(`starboard-engagement`) that carries the phase beats, the modular primitives, and the
doc/slide templates, plus **thin vertical** skills (`starboard-action-plan`,
`starboard-deliver`) that *compose* the scaffold rather than duplicating it. There is no
deterministic ranking kernel (`starboard_x.plan_portable` was removed) and no compute
script — the host reasons, prioritizes, validates, and writes.

This test guards that structure: the scaffold exists with its primitives + templates, the
verticals stay thin and reference the scaffold, and nothing re-acquires a compute script or
the removed kernel.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SKILLS = Path(__file__).parents[1] / "skills" / "starboard"
_SCAFFOLD = _SKILLS / "starboard-engagement"
_ACTION_PLAN = _SKILLS / "starboard-action-plan"
_DELIVER = _SKILLS / "starboard-deliver"
_VERTICALS = (_ACTION_PLAN, _DELIVER)
_ALL = (_SCAFFOLD, *_VERTICALS)


@pytest.mark.unit
class TestEngagementIsGuidanceOnly:
    @pytest.mark.parametrize("skill_dir", _ALL)
    def test_no_compute_script(self, skill_dir: Path) -> None:
        assert skill_dir.is_dir(), f"missing skill {skill_dir}"
        assert not (skill_dir / "scripts").exists(), (
            f"{skill_dir.name} must be guidance-only — no scripts/ dir"
        )

    @pytest.mark.parametrize("skill_dir", _ALL)
    def test_no_removed_kernel_reference(self, skill_dir: Path) -> None:
        for md in skill_dir.rglob("*.md"):
            assert "plan_portable" not in md.read_text(encoding="utf-8"), (
                f"{md.relative_to(_SKILLS)} references the removed plan_portable kernel"
            )


@pytest.mark.unit
class TestScaffoldCarriesTheReusableAssets:
    def test_primitives_present(self) -> None:
        refs = _SCAFFOLD / "references"
        assert refs.is_dir(), "scaffold must carry references/ primitives"
        for prim in (
            "technical-review",
            "humanize",
            "scope-sanitize",
            "evidence-cite",
            "native-remediation",
            "capability-bind",
        ):
            assert (refs / f"{prim}.md").is_file(), f"missing primitive {prim}.md"

    def test_templates_present(self) -> None:
        tpl = _SCAFFOLD / "templates"
        assert tpl.is_dir(), "scaffold must carry templates/"
        assert (tpl / "cost-review-doc.md").is_file()
        assert (tpl / "deck.md").is_file()

    def test_scaffold_declares_the_beats(self) -> None:
        body = (_SCAFFOLD / "SKILL.md").read_text(encoding="utf-8")
        for beat in ("CONFIRM", "validate", "technical-review", "humanize"):
            assert beat in body, f"scaffold SKILL.md dropped the '{beat}' beat"


@pytest.mark.unit
class TestDriveStorageIsReachableFromPrompts:
    """The engagement-drive helper must be wired into the skill text, not only shipped."""

    def test_scaffold_runs_preflight_and_route_before_gather(self) -> None:
        body = (_SCAFFOLD / "SKILL.md").read_text(encoding="utf-8")
        preflight = body.index("starboard-helper engagement preflight")
        route = body.index("starboard-helper engagement route")
        gather = body.index("1. **gather**")
        assert preflight < gather and route < gather
        assert "storage_decision" in body
        assert "starboard-helper engagement commit" in body
        assert "engagement upload" not in body and "advisory_warning" not in body

    def test_deliver_publishes_through_the_helper(self) -> None:
        for md in (
            _DELIVER / "SKILL.md",
            _SCAFFOLD / "references" / "capability-bind.md",
        ):
            body = md.read_text(encoding="utf-8")
            assert "engagement upload" not in body, md.name
            assert "starboard-helper engagement report" in body, md.name
            assert "run_folder_id" in body or "$RUN_FOLDER" in body, md.name
            assert "fallback_warning" in body, md.name
            assert "<Workspace Name>/<YYYY_MM_DD>" not in body, (
                f"{md.name} still names the pre-route Drive path"
            )


@pytest.mark.unit
class TestVerticalsAreThinAndCompose:
    @pytest.mark.parametrize("skill_dir", _VERTICALS)
    def test_vertical_composes_the_scaffold(self, skill_dir: Path) -> None:
        body = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "starboard-engagement" in body, (
            f"{skill_dir.name} must compose the shared scaffold (reference starboard-engagement), "
            "not re-implement the beats"
        )


# A run-dir template that ends in a date (`ws-<id>-<YYYY-MM-DD>/`, `<workspace>-<date>/`). The
# engagement run dir is preflight's `data.run_dir` (`<account>/<task>/<task-name>/<run_id>/`).
_OLD_RUN_DIR = re.compile(r"(?:ws|<[a-z_]+>)(?:-<[a-z_]+>)?-<(?:YYYY-MM-DD|date)>")
_FOCUSED = tuple(
    _SKILLS / f"starboard-{name}"
    for name in (
        "analyze",
        "cluster",
        "diagnostic",
        "finops",
        "job",
        "query",
        "uc",
        "warehouse",
        "workload-review",
    )
)
#: The phase-4 task entry skills (not focused skills: they run a whole task).
_TASK_ENTRY = (_SKILLS / "starboard-health-review", _SKILLS / "starboard-troubleshoot")
_RUN_DIR_SKILLS = (
    _SCAFFOLD,
    _SKILLS / "starboard-discovery",
    _ACTION_PLAN,
    _DELIVER,
    *_FOCUSED,
    *_TASK_ENTRY,
)
_AGENT = Path(__file__).parents[1] / "agents" / "starboard-workload-review-auto.yaml"
# Skills and the scheduled agent that create their own run dir when run standalone.
_STANDALONE = (
    *(d / "SKILL.md" for d in (_SKILLS / "starboard-discovery", *_FOCUSED, *_TASK_ENTRY)),
    _AGENT,
)


def _label(p: Path) -> str:
    return p.parent.name if p.name == "SKILL.md" else p.stem


@pytest.mark.unit
class TestRunDirsFollowTheEngagementLayout:
    @pytest.mark.parametrize("skill_dir", _RUN_DIR_SKILLS, ids=lambda p: p.name)
    def test_no_dated_run_dir_template(self, skill_dir: Path) -> None:
        assert skill_dir.is_dir(), f"missing skill {skill_dir}"
        for md in skill_dir.rglob("*.md"):
            hits = _OLD_RUN_DIR.findall(md.read_text(encoding="utf-8"))
            assert not hits, f"{md.relative_to(_SKILLS)} names a dated run dir: {hits}"

    def test_scheduled_agent_has_no_dated_run_dir_template(self) -> None:
        body = _AGENT.read_text(encoding="utf-8")
        assert not _OLD_RUN_DIR.findall(body)
        assert "--workspace-root starboard-reports/ws-" not in body

    @pytest.mark.parametrize("path", [_SCAFFOLD / "SKILL.md", *_STANDALONE], ids=_label)
    def test_preflight_names_the_task_and_case(self, path: Path) -> None:
        body = path.read_text(encoding="utf-8")
        assert "starboard-helper engagement preflight" in body
        assert "--task " in body and "--task-name " in body and "--account-name " in body

    @pytest.mark.parametrize("path", [_SCAFFOLD / "SKILL.md", _AGENT], ids=_label)
    def test_recur_trend_root_is_the_case_root(self, path: Path) -> None:
        body = path.read_text(encoding="utf-8")
        assert "--workspace-root <case-root>" in body
        assert "--workspace-root starboard-reports/" not in body


@pytest.mark.unit
class TestStandaloneRunsReachDrive:
    """A standalone covered run routes to its run folder and commits there; nothing is uploaded."""

    @pytest.mark.parametrize("path", _STANDALONE, ids=_label)
    def test_routes_then_commits_on_a_drive_run(self, path: Path) -> None:
        body = path.read_text(encoding="utf-8")
        assert "drive_required" in body and "storage_decision" in body
        route = body.index("starboard-helper engagement route --run-id")
        commit = body.index("starboard-helper engagement commit --run-folder $RUN_FOLDER")
        assert route < commit
        assert "engagement upload" not in body
        assert "fallback_warning" in body


@pytest.mark.unit
class TestOneTaskPerRun:
    """A workspace task (discovery / action plan / review) never does or mentions run diagnosis."""

    def test_scaffold_declares_one_task_per_run(self) -> None:
        body = (_SCAFFOLD / "SKILL.md").read_text(encoding="utf-8")
        assert "One task per run" in body
        assert "troubleshooting" in body

    @pytest.mark.parametrize(
        "path", [_SKILLS / "starboard-discovery" / "SKILL.md", _AGENT], ids=_label
    )
    def test_workspace_runs_never_fetch_run_logs(self, path: Path) -> None:
        assert "never fetches a single job's logs" in path.read_text(encoding="utf-8")

    @pytest.mark.parametrize("skill_dir", _RUN_DIR_SKILLS, ids=lambda p: p.name)
    def test_public_skills_name_no_internal_diagnosis_tool(self, skill_dir: Path) -> None:
        for md in skill_dir.rglob("*.md"):
            body = md.read_text(encoding="utf-8").lower()
            for tok in ("dbr-doctor", "logs-summariser"):
                assert tok not in body, f"{md.relative_to(_SKILLS)} names {tok}"


_MONITOR = Path(__file__).parents[1] / "agents" / "starboard-cluster-monitor.yaml"
_SCHEDULED = (_AGENT, _MONITOR)
# A discovery invocation in prompt text, through to the end of its (possibly
# backslash-continued) command line or inline code span.
_DISCOVER_CALL = re.compile(
    r"(?:starboard --discover|python -m starboard_x\.discovery (?:run|plan))(?:\\\n|[^\n`])*"
)


def _discovery_texts() -> list[Path]:
    mds = [md for d in _RUN_DIR_SKILLS for md in sorted(d.rglob("*.md"))]
    return [*mds, *_SCHEDULED]


@pytest.mark.unit
class TestRunsAreAuthorizedBeforeAcquisition:
    """preflight → verify-identity --run-id → route --run-id → acquire into the run → commit."""

    @pytest.mark.parametrize("path", [_SCAFFOLD / "SKILL.md", *_STANDALONE, _MONITOR], ids=_label)
    def test_identity_is_verified_between_preflight_and_route(self, path: Path) -> None:
        body = path.read_text(encoding="utf-8")
        preflight = body.index("starboard-helper engagement preflight")
        verify = body.index("starboard-helper engagement verify-identity --run-id")
        route = body.index("starboard-helper engagement route --run-id")
        assert preflight < verify < route
        assert "--account-key " in body[preflight:verify]
        assert "--expected-workspace-id" in body[verify:route]

    @pytest.mark.parametrize("path", [*_STANDALONE, _MONITOR], ids=_label)
    def test_route_runs_before_the_commit_on_every_storage_decision(self, path: Path) -> None:
        body = path.read_text(encoding="utf-8")
        route = body.index("starboard-helper engagement route --run-id")
        commit = body.index("starboard-helper engagement commit --run-folder $RUN_FOLDER")
        assert route < commit
        assert "run-authorization.json" in body  # the local (public) form keeps its record

    @pytest.mark.parametrize("path", _discovery_texts(), ids=lambda p: f"{p.parent.name}/{p.name}")
    def test_customer_discovery_passes_the_run(self, path: Path) -> None:
        for call in _DISCOVER_CALL.findall(path.read_text(encoding="utf-8")):
            assert "--authorization" in call or "--run-folder" in call, f"{path.name}: {call!r}"
            assert not ("--authorization" in call and "--run-folder" in call), call
            if "--internal-" in call and "--run-folder" not in call:
                # an internal_only_local capture writes only inside its run dir
                assert "--authorization <run-dir>" in call, f"{path.name}: {call!r}"
                assert "--out-dir <run-dir>/discovery" in call, f"{path.name}: {call!r}"

    @pytest.mark.parametrize("path", _SCHEDULED, ids=_label)
    def test_scheduled_runs_are_unattended(self, path: Path) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        for cmd in ("starboard-helper engagement preflight", "starboard-helper engagement route"):
            hits = [ln for ln in lines if cmd in ln]
            assert hits, f"{path.name} never runs {cmd}"
            assert all("--unattended" in ln for ln in hits), f"{path.name}: {cmd} w/o --unattended"

    @pytest.mark.parametrize("path", _SCHEDULED, ids=_label)
    def test_scheduled_runs_never_approve(self, path: Path) -> None:
        body = path.read_text(encoding="utf-8")
        assert "starboard-helper engagement approve" not in body
        assert "can_approve" in body

    def test_monitor_keeps_its_workspace_id(self) -> None:
        body = _MONITOR.read_text(encoding="utf-8")
        assert "--workspace-id" in body
        assert "--task-name ws-<workspace_id>" in body

    def test_scaffold_resumes_an_interrupted_run(self) -> None:
        body = (_SCAFFOLD / "SKILL.md").read_text(encoding="utf-8")
        assert "starboard-helper engagement preflight --resume-run-id" in body
        assert "--resume <" not in body
        assert "quarantined" in body

    @pytest.mark.parametrize(
        "path",
        [
            _SCAFFOLD / "SKILL.md",
            _SCAFFOLD / "references" / "capability-bind.md",
            _DELIVER / "SKILL.md",
        ],
        ids=lambda p: f"{p.parent.name}-{p.name}",
    )
    def test_a_sharing_change_blocks_the_run(self, path: Path) -> None:
        body = " ".join(path.read_text(encoding="utf-8").split())
        assert "`replaces`" not in body and "earlier cop" not in body
        assert "re-run route to reauthorize" not in body
        assert "blocked_access" in body
        assert "restore the folder's previous sharing" in body
        assert "re-run upload" not in body
        assert "restore the folder sharing" not in body


# --- Run setup comes before the first workspace read ----------------------------------------
_AGENTS = Path(__file__).parents[1] / "agents"
_DOMAIN_AGENTS = tuple(
    _AGENTS / f"starboard-{name}.yaml"
    for name in (
        "analyze",
        "cluster",
        "diagnostic",
        "discovery",
        "finops",
        "job",
        "query",
        "uc",
        "warehouse",
        "workload-review",
    )
)
# A command that reads workspace data: a `starboard-helper <domain> <verb>` fetch (not the
# engagement / run / auth helpers), a live discovery or review, or the bundled `run.sh run|plan`.
_WORKSPACE_READ = re.compile(
    r"starboard-helper (?!engagement\b|run\b|auth\b)[a-z-]+ [a-z-]+"
    r"|starboard --discover|starboard review\b"
    r"|python -m starboard_x\.discovery (?:run|plan)"
    r"|run\.sh (?:run|plan)\b"
)
_RUN_SH_DISCOVERY = re.compile(r"scripts/run\.sh (?:run|plan)\b(?:\\\n|[^\n`])*")
# A specific exit number claimed for a discovery / engagement step ("exits 3/2", "exit 2/3").
_EXIT_PAIR = re.compile(r"\bexits?\s+(?:code\s+)?\d\s*/\s*\d\b", re.IGNORECASE)


@pytest.mark.unit
class TestRunSetupPrecedesTheFirstRead:
    """The spec rule: identity is verified before ANY row, log or code is acquired."""

    @pytest.mark.parametrize("skill_dir", _FOCUSED, ids=lambda p: p.name)
    def test_focused_skill_sets_the_run_up_before_its_first_read(self, skill_dir: Path) -> None:
        body = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        read = _WORKSPACE_READ.search(body)
        assert read, f"{skill_dir.name} has no workspace read command"
        for cmd in (
            "starboard-helper engagement preflight",
            "starboard-helper engagement verify-identity --run-id",
            "starboard-helper engagement route --run-id",
        ):
            assert cmd in body, f"{skill_dir.name} never runs {cmd}"
            assert body.index(cmd) < read.start(), (
                f"{skill_dir.name}: {cmd} comes after the first read {read.group(0)!r}"
            )
        # the save step only commits; it no longer sets the run up or uploads
        save = body.index("### Offer to save the report")
        assert "starboard-helper engagement preflight" not in body[save:]
        assert "starboard-helper engagement commit --run-folder $RUN_FOLDER" in body[save:]
        assert "engagement upload" not in body

    @pytest.mark.parametrize("path", _DOMAIN_AGENTS, ids=lambda p: p.stem)
    def test_domain_agent_sets_the_run_up_before_any_read(self, path: Path) -> None:
        body = path.read_text(encoding="utf-8")
        setup = body.index("Run setup (before any read)")
        read = _WORKSPACE_READ.search(body)
        assert read is None or setup < read.start(), f"{path.stem}: setup after {read.group(0)!r}"
        tail = body[setup:]
        for token in (
            "preflight",
            "verify-identity --run-id",
            "route --run-id",
            "--run-folder $RUN_FOLDER",
            "--authorization <run-dir>",
        ):
            assert token in tail, f"{path.stem} run setup never mentions {token}"
        skill_ref = re.search(r"^skill_ref: (\S+)", body, re.MULTILINE)
        assert skill_ref and skill_ref.group(1) in tail

    @pytest.mark.parametrize("path", _DOMAIN_AGENTS, ids=lambda p: p.stem)
    def test_domain_agent_discovery_calls_pass_the_authorization(self, path: Path) -> None:
        body = path.read_text(encoding="utf-8")
        calls = [*_DISCOVER_CALL.findall(body), *_RUN_SH_DISCOVERY.findall(body)]
        for call in calls:
            if "--internal-" not in call:
                assert "--authorization" in call or "--run-folder" in call, f"{path.stem}: {call!r}"

    @pytest.mark.parametrize(
        "name", ["starboard-cluster-monitor", "starboard-workload-review-auto"]
    )
    def test_scheduled_agent_sets_the_run_up_before_its_first_read(self, name: str) -> None:
        body = (_AGENTS / f"{name}.yaml").read_text(encoding="utf-8")
        read = _WORKSPACE_READ.search(body)
        assert read, f"{name} has no workspace read command"
        for cmd in (
            "starboard-helper engagement preflight",
            "starboard-helper engagement verify-identity --run-id",
            "starboard-helper engagement route --run-id",
        ):
            assert cmd in body, f"{name} never runs {cmd}"
            assert body.index(cmd) < read.start(), (
                f"{name}: {cmd} comes after the first read {read.group(0)!r}"
            )

    def test_discovery_agent_runs_discovery(self) -> None:
        body = (_AGENTS / "starboard-discovery.yaml").read_text(encoding="utf-8")
        assert _RUN_SH_DISCOVERY.search(body), "expected a run.sh run call in the discovery agent"


@pytest.mark.unit
class TestNoSpecificExitNumbersForPacks:
    @pytest.mark.parametrize(
        "path",
        [
            *(md for d in _RUN_DIR_SKILLS for md in sorted(d.rglob("*.md"))),
            *sorted(_AGENTS.glob("*.yaml")),
        ],
        ids=lambda p: f"{p.parent.name}/{p.name}",
    )
    def test_no_exit_pair_claim(self, path: Path) -> None:
        body = path.read_text(encoding="utf-8")
        assert not _EXIT_PAIR.findall(body), f"{path.name} claims specific exit numbers"
        assert "cannot run exits" not in " ".join(body.split())
