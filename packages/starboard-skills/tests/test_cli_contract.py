"""Contract tests for the ``starboard-helper`` CLI (Phase-0 A4).

These tests pin the stable JSON envelope, the documented exit codes, and the
1:1 mapping between the 9 canonical skills and CLI verbs. The heavy
``starboard`` package is never imported — helpers use a bare
``databricks.sdk.WorkspaceClient`` which we mock here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starboard_skills.helpers import __main__ as cli
from starboard_skills.helpers import contract

# The 9 canonical verbs (one per skill). D-0.4: no ``genie`` verb.
EXPECTED_VERBS = {
    "job",
    "query",
    "warehouse",
    "uc",
    "cluster",
    "finops",
    "diagnostic",
    "analyze",
    "discovery",
}

ENVELOPE_KEYS = {"ok", "domain", "command", "data", "error", "meta"}


def run_cli(argv, monkeypatch, capsys, *, client=None, account_client=None):
    """Invoke the CLI in-process; return (exit_code, parsed_envelope_or_None)."""
    if client is not None:
        monkeypatch.setattr(
            "databricks.sdk.WorkspaceClient", lambda *a, **k: client
        )
    if account_client is not None:
        monkeypatch.setattr(
            "databricks.sdk.AccountClient", lambda *a, **k: account_client
        )
    code = 0
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    code = exc.value.code if isinstance(exc.value.code, int) else 1
    out = capsys.readouterr().out
    try:
        envelope = json.loads(out)
    except (ValueError, json.JSONDecodeError):
        envelope = None
    return code, envelope


def _ok_client():
    """A MagicMock WorkspaceClient whose list/get calls succeed with empty data."""
    c = MagicMock()
    c.jobs.list.return_value = []
    c.jobs.get.return_value = SimpleNamespace(
        job_id=1, settings=SimpleNamespace(name="j", as_dict=lambda: {"name": "j"})
    )
    c.warehouses.list.return_value = []
    c.clusters.list.return_value = []
    c.catalogs.list.return_value = []
    return c


# --------------------------------------------------------------------------- #
# Verb registry / 1:1 skill mapping
# --------------------------------------------------------------------------- #
def test_all_expected_verbs_registered():
    parser = cli.build_parser()
    # Locate the top-level subparsers action and read its registered choices.
    choices = set()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices and action.dest == "domain":
            choices = set(action.choices)
    assert choices == EXPECTED_VERBS


def test_skill_bodies_map_to_real_verbs():
    """Regression: every ``starboard-helper <domain>`` referenced by a skill
    body resolves to a registered verb. Falls back to the known verb set when
    the skills tree isn't present in this worktree."""
    parser = cli.build_parser()
    registered = set()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices and action.dest == "domain":
            registered = set(action.choices)

    skills_root = (
        Path(__file__).resolve().parents[1] / "skills" / "starboard"
    )
    referenced = set()
    if skills_root.exists():
        pat = re.compile(r"starboard-helper\s+([a-z-]+)\s")
        for md in skills_root.rglob("*.md"):
            referenced.update(pat.findall(md.read_text()))

    if referenced:
        assert referenced <= registered, (
            f"skill bodies reference unregistered verbs: {referenced - registered}"
        )
    else:
        assert registered >= EXPECTED_VERBS


# --------------------------------------------------------------------------- #
# Envelope shape + success path
# --------------------------------------------------------------------------- #
def test_success_envelope_shape(monkeypatch, capsys):
    code, env = run_cli(["job", "list"], monkeypatch, capsys, client=_ok_client())
    assert code == 0
    assert set(env.keys()) == ENVELOPE_KEYS
    assert env["ok"] is True
    assert env["domain"] == "job"
    assert env["command"] == "list"
    assert env["error"] is None
    assert env["data"] is not None
    assert env["data"]["count"] == 0
    assert env["meta"]["format"] == "json"
    assert "contract_version" in env["meta"]


@pytest.mark.parametrize(
    "argv,domain,command",
    [
        (["job", "list"], "job", "list"),
        (["warehouse", "list"], "warehouse", "list"),
        (["cluster", "list"], "cluster", "list"),
        (["uc", "catalogs"], "uc", "catalogs"),
        (["analyze", "snapshot"], "analyze", "snapshot"),
        (["discovery", "list"], "discovery", "list"),
    ],
)
def test_every_verb_emits_envelope(argv, domain, command, monkeypatch, capsys):
    code, env = run_cli(argv, monkeypatch, capsys, client=_ok_client())
    assert code == 0, env
    assert set(env.keys()) == ENVELOPE_KEYS
    assert env["ok"] is True
    assert env["domain"] == domain
    assert env["command"] == command
    assert env["data"] is not None


def test_finops_verb_emits_envelope(monkeypatch, capsys):
    acct = MagicMock()
    acct.budgets.list.return_value = []
    code, env = run_cli(
        ["finops", "budgets"], monkeypatch, capsys, account_client=acct
    )
    assert code == 0
    assert set(env.keys()) == ENVELOPE_KEYS
    assert env["ok"] is True
    assert env["domain"] == "finops"


# --------------------------------------------------------------------------- #
# New verbs
# --------------------------------------------------------------------------- #
def test_discovery_lists_all_domains(monkeypatch, capsys):
    # discovery is data-only and must not touch the SDK.
    code, env = run_cli(["discovery", "list"], monkeypatch, capsys)
    assert code == 0
    assert env["ok"] is True
    domains = env["data"]["domains"]
    listed = {d["name"] for d in domains}
    assert listed >= EXPECTED_VERBS
    # each entry describes its commands
    for d in domains:
        assert "commands" in d and isinstance(d["commands"], list)


def test_analyze_snapshot_is_multidomain(monkeypatch, capsys):
    code, env = run_cli(
        ["analyze", "snapshot"], monkeypatch, capsys, client=_ok_client()
    )
    assert code == 0
    snapshot = env["data"]["snapshot"]
    assert {"jobs", "warehouses", "clusters"} <= set(snapshot.keys())


# --------------------------------------------------------------------------- #
# Exit codes: 0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error
# --------------------------------------------------------------------------- #
def test_exit_code_auth(monkeypatch, capsys):
    def boom(*a, **k):
        raise Exception("default auth credentials not found")

    monkeypatch.setattr("databricks.sdk.WorkspaceClient", boom)
    code, env = run_cli(["job", "list"], monkeypatch, capsys)
    assert code == contract.EXIT_AUTH == 1
    assert env["ok"] is False
    assert env["error"] is not None


def test_exit_code_not_found(monkeypatch, capsys):
    c = MagicMock()
    c.jobs.get.side_effect = Exception("Job 999 not found")
    code, env = run_cli(
        ["job", "fetch", "--job-id", "999"], monkeypatch, capsys, client=c
    )
    assert code == contract.EXIT_NOT_FOUND == 2
    assert env["ok"] is False
    assert env["error"] is not None


def test_exit_code_api_error(monkeypatch, capsys):
    c = MagicMock()
    c.jobs.get.side_effect = Exception("kaboom internal server error")
    code, env = run_cli(
        ["job", "fetch", "--job-id", "1"], monkeypatch, capsys, client=c
    )
    assert code == contract.EXIT_API == 3
    assert env["ok"] is False


def test_exit_code_arg_error_missing_required(monkeypatch, capsys):
    # --job-id is required for `job fetch`
    code, _env = run_cli(["job", "fetch"], monkeypatch, capsys)
    assert code == contract.EXIT_ARG == 4


def test_exit_code_arg_error_bad_choice(monkeypatch, capsys):
    c = MagicMock()
    code, _env = run_cli(
        ["query", "history", "--status", "BOGUS"],
        monkeypatch,
        capsys,
        client=c,
    )
    assert code == contract.EXIT_ARG == 4


# --- regression: --limit must cap results (SDK .list() auto-paginates; limit is
# only the page size, so a bare list() returns ALL rows). ---

def _fake_jobs(n, name=lambda i: f"job{i}"):
    return [
        SimpleNamespace(job_id=i, settings=SimpleNamespace(name=name(i)))
        for i in range(n)
    ]


def test_job_list_honors_limit(monkeypatch, capsys):
    c = MagicMock()
    c.jobs.list.return_value = _fake_jobs(19)  # more than the requested limit
    code, env = run_cli(
        ["job", "list", "--limit", "5"], monkeypatch, capsys, client=c
    )
    assert code == 0 and env["ok"] is True
    assert env["data"]["count"] == 5
    assert len(env["data"]["jobs"]) == 5


def test_job_list_limit_counts_filtered_matches(monkeypatch, capsys):
    c = MagicMock()
    c.jobs.list.return_value = _fake_jobs(
        20, name=lambda i: ("keep" if i % 2 == 0 else "skip") + str(i)
    )
    code, env = run_cli(
        ["job", "list", "--limit", "3", "--name-filter", "keep"],
        monkeypatch,
        capsys,
        client=c,
    )
    assert code == 0
    assert env["data"]["count"] == 3
    assert all("keep" in j["name"] for j in env["data"]["jobs"])
