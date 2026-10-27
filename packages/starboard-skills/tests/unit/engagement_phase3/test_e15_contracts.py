"""E15: record contracts — round-trips, free-text scrub, concern keys, catalog, seed rules."""

from __future__ import annotations

import pytest
from starboard_skills.helpers.engagement.analysis_cmds import PLAY_DIGEST_KEYS

from . import _j42
from ._support import (
    QUESTION,
    Ctx,
    baseline_run,
    commit,
    current_run,
    eng,
    engagement_ok,
    error_code,
    manifest,
    records,
)

MODE = "drive_backed"
RUN_ID = "20261008_12345678-1234-4123-8123-123456789abc"
NEW_REFS = ("health_ref", "plays_ref", "changes_ref", "cases_ref", "actions_ref")


def _classes() -> dict[str, type]:
    from starboard_core.engagement import records as r

    return {
        "observations": r.Observation,
        "findings": r.FindingRecord,
        "health": r.HealthRead,
        "plays": r.Play,
        "changes": r.ChangeInput,
        "cases": r.Case,
        "actions": r.Action,
        "baselines": r.BaselineSelection,
    }


def _items(value) -> list[dict]:
    return value if isinstance(value, list) else [value]


def test_every_new_record_round_trips(capsys, store, sandbox, seams, tmp_path) -> None:
    from starboard_core.engagement.records import RunManifest, StorageRef

    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, MODE)
    baseline_run(ctx)
    run = current_run(ctx, commit_it=False)
    engagement_ok(
        ctx,
        run,
        "case",
        "open",
        *run.flags(),
        "--finding-id",
        _j42.finding_id_j42(),
        "--question",
        QUESTION,
    )
    commit(ctx, run)

    recs = records(ctx, run)
    for name, cls in _classes().items():
        items = _items(getattr(recs, name))
        assert items, name
        for item in items:
            if name == "plays":  # run-5 B4: plays.json also carries derived digest keys
                assert set(PLAY_DIGEST_KEYS) <= set(item), name
                item = {k: v for k, v in item.items() if k not in PLAY_DIGEST_KEYS}
            assert cls.from_dict(item).to_dict() == item, name

    assert run.rf
    m = manifest(store, run.rf)
    for ref_name in NEW_REFS:
        ref = getattr(m, ref_name)
        assert isinstance(ref, StorageRef), ref_name
        assert StorageRef.from_dict(ref.to_dict()) == ref
    assert RunManifest.from_dict(m.to_dict()) == m


@pytest.mark.parametrize(
    "text",
    [
        "Ask jo.analyst@acme.example why job 42 fails",
        "Ask jo.analyst%40acme.example why job 42 fails",
        "Job 42 fails with password=synthetic-not-real",
    ],
    ids=["email", "encoded-email", "credential"],
)
def test_host_free_text_rejects_emails_and_credentials(
    text, capsys, store, sandbox, seams, tmp_path
) -> None:
    from starboard_core.engagement.records import _check_free_text

    with pytest.raises(ValueError):
        _check_free_text(text, "question")

    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, MODE)
    baseline_run(ctx)
    run = current_run(ctx, commit_it=False)
    code, env, raw = eng(
        capsys,
        "case",
        "open",
        *run.flags(),
        "--finding-id",
        _j42.finding_id_j42(),
        "--question",
        text,
    )
    assert code == 2, raw
    assert "@" not in raw and "synthetic-not-real" not in raw
    assert error_code(env)

    action_id = next(a["action_id"] for a in records(ctx, run).actions)
    code, _env, raw = eng(
        capsys,
        "action",
        "accept",
        *run.flags(),
        "--action-id",
        action_id,
        "--note",
        text,
    )
    assert code == 2, raw


def test_concern_key_excludes_run_ticket_and_path() -> None:
    from starboard_core.engagement.records import concern_key

    key = concern_key(_j42.ACCOUNT, _j42.WS, "job", _j42.JOB, "job_failure_rise")
    assert key.split("|") == [
        "ck1",
        _j42.ACCOUNT,
        _j42.WS,
        "job",
        _j42.JOB,
        "job_failure_rise",
        "-",
    ]
    bad = [
        (_j42.ACCOUNT, _j42.WS, "job", "4|2", "job_failure_rise", "-"),
        (_j42.ACCOUNT, _j42.WS, "job", _j42.JOB, "job_failure_rise", f"sig:{RUN_ID}"),
        (_j42.ACCOUNT, _j42.WS, "job", f"{_j42.JOB}-{RUN_ID}", "job_failure_rise", "-"),
        (
            "AR-000000001/troubleshooting",
            _j42.WS,
            "job",
            _j42.JOB,
            "job_failure_rise",
            "-",
        ),
        (_j42.ACCOUNT, _j42.WS, "job", "job 42", "job_failure_rise", "-"),
        (_j42.ACCOUNT, _j42.WS, "job", _j42.JOB, "Why did job 42 fail", "-"),
    ]
    for parts in bad:
        with pytest.raises(ValueError):
            concern_key(*parts)


def test_family_metric_units_are_known() -> None:
    from starboard_core.engagement.catalog import FAMILY_METRICS, SIX_FAMILIES
    from starboard_core.engagement.records import UNITS

    assert set(FAMILY_METRICS) == set(SIX_FAMILIES)
    units = {spec.unit for specs in FAMILY_METRICS.values() for spec in specs}
    assert units <= set(UNITS)
    per_job = {spec.metric: spec for spec in FAMILY_METRICS["reliability"]}
    assert per_job["job_failure_rate_pct"].unit == "pct"


def test_seed_rules_carry_a_family() -> None:
    from starboard_core.domain.rules.registry import RuleRegistry
    from starboard_core.engagement.catalog import SIX_FAMILIES

    rules = RuleRegistry.from_seed().rules
    assert len(rules) == 23
    assert [r.id for r in rules if r.family not in SIX_FAMILIES] == []


def test_user_rule_without_family_is_unclassified() -> None:
    from starboard_core.domain.rules.loader import load_ruleset_from_string
    from starboard_core.domain.rules.registry import RuleRegistry, rule_family

    ruleset = load_ruleset_from_string(
        """
version: "1.0.0"
domain: jobs
rules:
  - id: user_custom_rule
    name: A user rule with no family
    category: jobs
    short_description: Synthetic user rule.
    rationale: Synthetic user rule.
    severity: low
    default_effort: S
    default_impact: 1
    bad: bad
    good: good
    suggested_fix: fix
    detect: detect
    evidence_query: F-06
    source: null
    enabled: true
""",
        source="user.yaml",
    )
    registry = RuleRegistry([ruleset])
    assert ruleset.rules[0].family is None
    assert rule_family("user_custom_rule", registry) == "unclassified"
    assert rule_family("no_such_rule", registry) == "unclassified"
