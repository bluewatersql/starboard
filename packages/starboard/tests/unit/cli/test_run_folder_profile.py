# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``--run-folder`` runs read as the run's verified profile (``PROFILE_MISMATCH``).

``engagement verify-identity --profile X`` records the profile on the run descriptor.
``starboard --discover`` / the goal agent / ``starboard review`` with ``--run-folder``
then default ``--profile`` to it, and refuse another profile (or ``--host``) with exit
2 before any config, client or write. Same rule as ``starboard-core``'s
``TestRunFolderProfile``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard.cli.cli import main as cli_main
from starboard.cli.cli import review_command
from starboard.cli.cli._run_io import ProfileMismatchRefused, resolve_run_profile
from starboard.cli.cli.exit_codes import USAGE_ERROR
from starboard.cli.cli.review_command import run_review
from starboard_core.engagement.write_guard import active

from tests.unit.cli._engagement_support import (
    covered_env,
    diff,
    drive_run,
    sink_for,
    snapshot,
    written,
)


class _Stop(Exception):
    """Raised by the fake config merge: the run got past the profile gate."""


@pytest.fixture(autouse=True)
def _restore_logging() -> Any:
    import logging

    import structlog

    saved = structlog.get_config()
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    structlog.configure(**saved)
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def merged(monkeypatch: pytest.MonkeyPatch) -> list[SimpleNamespace]:
    """Fake ``merge_env_config``: record the profile/host it would export, then stop."""
    seen: list[SimpleNamespace] = []

    def merge(_file_config: object, args: Any) -> None:
        seen.append(SimpleNamespace(profile=args.profile, host=args.databricks_host))
        raise _Stop

    monkeypatch.setattr(cli_main, "merge_env_config", merge)
    return seen


async def _run(argv: list[str]) -> int:
    try:
        await cli_main.async_main(cli_main.parse_args(argv))
    except SystemExit as exc:
        return int(exc.code or 0)
    except _Stop:
        return 0
    return 0


@pytest.mark.unit
class TestResolveRunProfile:
    def test_defaults_to_the_verified_profile(self) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        assert resolve_run_profile(store, folder, None) == "acme-ws"
        assert resolve_run_profile(store, folder, "acme-ws") == "acme-ws"

    def test_refuses_another_profile(self) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        with pytest.raises(ProfileMismatchRefused, match=r"^PROFILE_MISMATCH: .*'other'"):
            resolve_run_profile(store, folder, "other")

    def test_refuses_host_on_a_profile_verified_run(self) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        with pytest.raises(ProfileMismatchRefused, match=r"^PROFILE_MISMATCH: .*drop --host"):
            resolve_run_profile(store, folder, None, "https://x.example.com")

    def test_host_verified_run(self) -> None:
        store, folder = drive_run(basis="verified")
        assert resolve_run_profile(store, folder, None, "https://x.example.com") is None
        with pytest.raises(ProfileMismatchRefused, match="PROFILE_MISMATCH"):
            resolve_run_profile(store, folder, "acme-ws")

    def test_unverified_scope_passes_through(self) -> None:
        store, folder = drive_run()
        assert resolve_run_profile(store, folder, "any") == "any"
        assert resolve_run_profile(store, folder, None) is None


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [["--discover", "--data-only"], ["--goal", "Cut spend"]])
class TestStarboardCli:
    async def test_defaults_to_the_verified_profile(
        self,
        mode: list[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        merged: list[SimpleNamespace],
    ) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        covered_env(monkeypatch, tmp_path, store, cli_main)

        await _run([*mode, "--run-folder", folder])

        assert [m.profile for m in merged] == ["acme-ws"]

    async def test_same_profile_is_accepted(
        self,
        mode: list[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        merged: list[SimpleNamespace],
    ) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        covered_env(monkeypatch, tmp_path, store, cli_main)

        await _run([*mode, "--run-folder", folder, "--profile", "acme-ws"])

        assert [m.profile for m in merged] == ["acme-ws"]

    async def test_another_profile_is_refused_before_anything_runs(
        self,
        mode: list[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        merged: list[SimpleNamespace],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
        before = snapshot(sandbox)

        code = await _run([*mode, "--run-folder", folder, "--profile", "other"])

        captured = capsys.readouterr()
        assert code == USAGE_ERROR
        envelope = json.loads(captured.out)
        assert envelope["ok"] is False
        assert envelope["error"].startswith("PROFILE_MISMATCH")
        assert "PROFILE_MISMATCH" in captured.err
        assert merged == []  # no config, no client
        assert written(sink_for(store, folder)) == set()
        assert diff(sandbox, before) == []
        assert not active()

    async def test_host_on_a_profile_verified_run_is_refused(
        self,
        mode: list[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        merged: list[SimpleNamespace],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        covered_env(monkeypatch, tmp_path, store, cli_main)

        code = await _run(
            [*mode, "--run-folder", folder, "--host", "https://x.example.com"]
        )

        assert code == USAGE_ERROR
        assert json.loads(capsys.readouterr().out)["error"].startswith("PROFILE_MISMATCH")
        assert merged == []

    async def test_host_verified_run_refuses_an_explicit_profile(
        self,
        mode: list[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        merged: list[SimpleNamespace],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(basis="verified")
        covered_env(monkeypatch, tmp_path, store, cli_main)

        code = await _run([*mode, "--run-folder", folder, "--profile", "acme-ws"])

        assert code == USAGE_ERROR
        assert json.loads(capsys.readouterr().out)["error"].startswith("PROFILE_MISMATCH")
        assert merged == []

    async def test_declared_scope_passes_the_profile_through(
        self,
        mode: list[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        merged: list[SimpleNamespace],
    ) -> None:
        store, folder = drive_run()
        covered_env(monkeypatch, tmp_path, store, cli_main)

        await _run([*mode, "--run-folder", folder, "--profile", "any"])
        await _run([*mode, "--run-folder", folder])

        assert [m.profile for m in merged] == ["any", None]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_internal_source_discovery_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    merged: list[SimpleNamespace],
) -> None:
    store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
    covered_env(monkeypatch, tmp_path, store, cli_main)

    await _run(
        ["--discover", "--run-folder", folder, "--internal-workspace-id", "123"]
    )

    assert [m.profile for m in merged] == [None]


@pytest.mark.unit
class TestReview:
    def test_another_profile_is_refused(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        sandbox = covered_env(monkeypatch, tmp_path, store, review_command)
        before = snapshot(sandbox)

        code = run_review(["--run-folder", folder, "--profile", "other"])

        captured = capsys.readouterr()
        assert code == USAGE_ERROR
        assert json.loads(captured.out)["error"].startswith("PROFILE_MISMATCH")
        assert captured.err.startswith("PROFILE_MISMATCH")
        assert written(sink_for(store, folder)) == set()
        assert diff(sandbox, before) == []
        assert not active()

    def test_workspace_alias_is_checked_too(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        covered_env(monkeypatch, tmp_path, store, review_command)

        code = run_review(["--run-folder", folder, "--workspace", "other"])

        assert code == USAGE_ERROR
        assert "PROFILE_MISMATCH" in capsys.readouterr().err

    def test_omitted_and_same_profile_pass_the_gate(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        covered_env(monkeypatch, tmp_path, store, review_command)

        for extra in ([], ["--profile", "acme-ws"]):
            code = run_review(["--run-folder", folder, *extra])
            out = capsys.readouterr()
            # No discovery output in the run: past the gate, the review fails on that.
            assert "PROFILE_MISMATCH" not in out.out + out.err, code
