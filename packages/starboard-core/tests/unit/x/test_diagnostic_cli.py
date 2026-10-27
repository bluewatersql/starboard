# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``python -m starboard_x.diagnostic`` CLI (Phase-1 B2).

Covers the stable JSON envelope, the Phase-0 exit-code contract
(``0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error``), and the
stdlib-only guarantee for the ``diagnostics-core`` trio (no pyyaml / pydantic /
databricks-sdk imported when running the trio verbs).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[3]
_REPO_ROOT = Path(__file__).parents[5]


# Pins the W30 intake overlay seam (``starboard_x._cli.detect_overlay``) OFF in the
# subprocess: the dev venv has the internal package installed, so the real detector
# reports "enabled" and a local input file would be refused. The gate itself is
# covered in tests/unit/x/test_cli_intake.py.
_PIN_PUBLIC = (
    "import runpy, starboard_x._cli as c;"
    "from starboard_core.engagement.overlay import OverlaySignal;"
    "c.detect_overlay = lambda **_k: OverlaySignal(enabled=False);"
)


def _run_cli(
    *args: str, input_files: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m starboard_x.diagnostic <args>`` from the core dir."""
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _PIN_PUBLIC
            + "runpy.run_module('starboard_x.diagnostic', run_name='__main__')",
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


def _parse_envelope(proc: subprocess.CompletedProcess[str]) -> dict:
    payload = json.loads(proc.stdout)
    # Every emission is the stable envelope.
    assert set(payload) >= {"ok", "domain", "command", "data", "error", "meta"}
    assert payload["meta"]["format"] == "json"
    assert "contract_version" in payload["meta"]
    return payload


@pytest.mark.unit
class TestTriageExitVerb:
    def test_triage_exit_137_ranked_hypotheses_exit_0(self) -> None:
        proc = _run_cli("triage-exit", "--exit-code", "137")
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["ok"] is True
        assert env["domain"] == "diagnostic"
        assert env["command"] == "triage-exit"
        data = env["data"]
        # Ranked hypotheses present, primary is OOM-family for 137 (SIGKILL).
        assert data["exit_code"] == 137
        assert data["primary_hypothesis"]["hypothesis_type"] == "oom"
        # Alternatives are ranked (list, possibly empty but present).
        assert isinstance(data["alternative_hypotheses"], list)
        assert data["primary_hypothesis"]["confidence"] >= 0.0

    def test_triage_exit_with_context_boosts_oom(self) -> None:
        proc = _run_cli(
            "triage-exit", "--exit-code", "137", "--context", "Container was OOMKilled"
        )
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["data"]["primary_hypothesis"]["hypothesis_type"] == "oom"

    def test_triage_exit_143_is_cancellation(self) -> None:
        proc = _run_cli("triage-exit", "--exit-code", "143")
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["data"]["primary_hypothesis"]["hypothesis_type"] == "cancellation"


@pytest.mark.unit
class TestExtractEvidenceVerb:
    def test_extract_evidence_from_file(self, tmp_path: Path) -> None:
        log = tmp_path / "err.log"
        log.write_text(
            "some noise\n"
            "java.lang.OutOfMemoryError: Java heap space\n"
            "\tat org.apache.spark.Foo(Foo.scala:1)\n"
        )
        proc = _run_cli("extract-evidence", "--text", str(log))
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["ok"] is True
        assert env["command"] == "extract-evidence"
        data = env["data"]
        assert data["window_count"] >= 1
        types = {w["evidence_type"] for w in data["windows"]}
        assert "oom" in types

    def test_extract_evidence_missing_file_is_arg_error(self) -> None:
        proc = _run_cli("extract-evidence", "--text", "/no/such/file.log")
        assert proc.returncode == 4, proc.stdout
        env = _parse_envelope(proc)
        assert env["ok"] is False
        assert env["error"]


@pytest.mark.unit
class TestRcaVerb:
    def test_rca_combines_triage_and_evidence(self, tmp_path: Path) -> None:
        log = tmp_path / "err.log"
        log.write_text(
            "Executor lost\n"
            "java.lang.OutOfMemoryError: Java heap space\n"
            "Container killed by YARN for exceeding memory limits\n"
        )
        proc = _run_cli("rca", "--text", str(log), "--exit-code", "137")
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["ok"] is True
        assert env["command"] == "rca"
        data = env["data"]
        # RCA merges exit-code triage + evidence extraction + synthesis.
        assert data["triage"]["primary_hypothesis"]["hypothesis_type"] == "oom"
        assert data["evidence"]["window_count"] >= 1
        assert "synthesis" in data
        assert "root_causes" in data["synthesis"]

    def test_rca_text_only_no_exit_code(self, tmp_path: Path) -> None:
        log = tmp_path / "err.log"
        log.write_text("[ERROR] something bad happened\n")
        proc = _run_cli("rca", "--text", str(log))
        assert proc.returncode == 0, proc.stderr
        env = _parse_envelope(proc)
        assert env["ok"] is True
        assert env["data"]["triage"] is None


@pytest.mark.unit
class TestArgErrors:
    def test_no_subcommand_is_arg_error(self) -> None:
        proc = _run_cli()
        assert proc.returncode == 4, proc.stdout
        env = _parse_envelope(proc)
        assert env["ok"] is False

    def test_bad_exit_code_value_is_arg_error(self) -> None:
        proc = _run_cli("triage-exit", "--exit-code", "not-a-number")
        assert proc.returncode == 4, proc.stdout
        env = _parse_envelope(proc)
        assert env["ok"] is False

    def test_unknown_subcommand_is_arg_error(self) -> None:
        proc = _run_cli("bogus-verb")
        assert proc.returncode == 4, proc.stdout


@pytest.mark.unit
class TestLazyPackageInit:
    """Review fix #5: importing the package must not eagerly pull the whole trio.

    ``starboard_x.diagnostic.__init__`` re-exports the trio for convenience but
    must do so lazily (module-level ``__getattr__``), so ``import
    starboard_x.diagnostic`` does not drag in evidence_extractor /
    exit_code_triager / models / root_cause_synthesizer unless an attribute is
    actually accessed. The public re-exports must still resolve.
    """

    def test_bare_package_import_does_not_load_submodules(self) -> None:
        body = """
import importlib
import sys

importlib.import_module("starboard_x.diagnostic")

eager = sorted(
    m for m in (
        "starboard_x.diagnostic.evidence_extractor",
        "starboard_x.diagnostic.exit_code_triager",
        "starboard_x.diagnostic.models",
        "starboard_x.diagnostic.query_profile",
        "starboard_x.diagnostic.root_cause_synthesizer",
    )
    if m in sys.modules
)
assert not eager, f"package __init__ eagerly imported submodules: {eager}"
print("OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", body],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout

    def test_public_reexports_resolve_lazily(self) -> None:
        import starboard_x.diagnostic as diag
        from starboard_x.diagnostic.evidence_extractor import EvidenceWindowExtractor
        from starboard_x.diagnostic.exit_code_triager import ExitCodeTriager
        from starboard_x.diagnostic.models import PrimarySymptom
        from starboard_x.diagnostic.root_cause_synthesizer import RootCauseSynthesizer

        # Lazy attribute access resolves to the exact same objects.
        assert diag.ExitCodeTriager is ExitCodeTriager
        assert diag.EvidenceWindowExtractor is EvidenceWindowExtractor
        assert diag.RootCauseSynthesizer is RootCauseSynthesizer
        assert diag.PrimarySymptom is PrimarySymptom
        # The Phase-1 spec alias must still be exposed.
        assert diag.EvidenceExtractor is EvidenceWindowExtractor

    def test_dir_and_all_advertise_public_names(self) -> None:
        import starboard_x.diagnostic as diag

        for name in ("ExitCodeTriager", "EvidenceExtractor", "RootCauseSynthesizer"):
            assert name in diag.__all__, f"{name} missing from __all__"
            assert name in dir(diag), f"{name} missing from dir()"

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        import starboard_x.diagnostic as diag

        with pytest.raises(AttributeError):
            _ = diag.NoSuchThing


@pytest.mark.unit
class TestStdlibOnlyGuarantee:
    """The ``diagnostics-core`` trio must import with no pyyaml/pydantic/SDK."""

    def test_trio_import_is_stdlib_only(self) -> None:
        body = """
import importlib
import sys

for mod in (
    "starboard_x.diagnostic",
    "starboard_x.diagnostic.exit_code_triager",
    "starboard_x.diagnostic.evidence_extractor",
    "starboard_x.diagnostic.root_cause_synthesizer",
    "starboard_x.diagnostic.models",
):
    importlib.import_module(mod)

heavy = sorted(
    m for m in sys.modules
    if m == "yaml"
    or m == "pydantic"
    or m == "databricks"
    or m.startswith("databricks.")
    or m.startswith("pydantic.")
)
assert not heavy, f"heavy deps imported by the core trio: {heavy}"
print("OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", body],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout


@pytest.mark.unit
class TestBackCompatShims:
    """Old import paths still resolve to the re-homed classes."""

    def test_starboard_diagnostic_reexports_trio(self) -> None:
        from starboard.tools.domain.diagnostic import (
            EvidenceWindowExtractor,
            ExitCodeTriager,
            RootCauseSynthesizer,
        )
        from starboard_x.diagnostic.evidence_extractor import (
            EvidenceWindowExtractor as XEvidence,
        )
        from starboard_x.diagnostic.exit_code_triager import (
            ExitCodeTriager as XTriager,
        )
        from starboard_x.diagnostic.root_cause_synthesizer import (
            RootCauseSynthesizer as XSynth,
        )

        # Shims must resolve to the exact same classes (single source of truth).
        assert ExitCodeTriager is XTriager
        assert EvidenceWindowExtractor is XEvidence
        assert RootCauseSynthesizer is XSynth

    def test_primary_symptom_single_source_of_truth(self) -> None:
        from starboard.tools.domain.diagnostic.models import PrimarySymptom as SbSymptom
        from starboard_x.diagnostic.models import PrimarySymptom as XSymptom

        assert SbSymptom is XSymptom


@pytest.mark.unit
class TestExtrasTaxonomy:
    """D-1.3 per-capability extras must be declared with the right shapes."""

    def _extras(self) -> dict:
        with (_CORE_DIR / "pyproject.toml").open("rb") as fh:
            return tomllib.load(fh)["project"]["optional-dependencies"]

    def test_diagnostics_core_is_empty(self) -> None:
        extras = self._extras()
        assert "diagnostics-core" in extras, list(extras)
        assert extras["diagnostics-core"] == [], extras["diagnostics-core"]

    def test_diagnostics_adds_pyyaml(self) -> None:
        extras = self._extras()
        assert "diagnostics" in extras, list(extras)
        joined = " ".join(extras["diagnostics"])
        assert "pyyaml" in joined.lower(), extras["diagnostics"]

    def test_stub_extras_declared(self) -> None:
        extras = self._extras()
        for name in (
            "discovery",
            "sparklog",
            "warehouse",
            "uc",
            "cluster",
            "charts",
            "all",
        ):
            assert name in extras, f"missing declared extra: {name}"

    def test_starboard_x_console_script_declared(self) -> None:
        with (_CORE_DIR / "pyproject.toml").open("rb") as fh:
            pyproject = tomllib.load(fh)
        scripts = pyproject["project"].get("scripts", {})
        assert scripts.get("starboard-x") == "starboard_x.__main__:main", scripts


# --------------------------------------------------------------------------- #
# ``profile --input REF`` (D3-22): the stdlib query-profile parser.
# --------------------------------------------------------------------------- #
_PROFILE = {
    "query": {
        "id": "q-9",
        "status": "FINISHED",
        "queryText": "SELECT 1 -- carol@example.com",
        "metrics": {"totalTimeMs": 100, "spillToDiskBytes": 0, "readBytes": 10},
    },
    "graphs": [
        {
            "nodes": [
                {
                    "id": "1",
                    "name": "Scan main.s.t",
                    "tag": "UNKNOWN_DATA_SOURCE_SCAN_EXEC",
                    "metrics": [{"key": "NUMBER_OUTPUT_ROWS", "value": 5}],
                }
            ]
        }
    ],
}


def _pin_overlay(monkeypatch: pytest.MonkeyPatch, *, overlay: bool) -> None:
    from starboard_core.engagement.overlay import OverlaySignal
    from starboard_x import _cli

    monkeypatch.setattr(
        _cli, "detect_overlay", lambda **_k: OverlaySignal(enabled=overlay)
    )


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch):
    """An in-memory Drive resolved through the engagement-storage entry point."""
    from types import SimpleNamespace

    from starboard_core.engagement import sink
    from starboard_core.engagement.memory_storage import InMemoryEngagementStorage

    s = InMemoryEngagementStorage(owner_domain="databricks.com")
    entry = SimpleNamespace(value="tests:InMemory", load=lambda: lambda: s)
    monkeypatch.setattr(
        sink, "metadata", SimpleNamespace(entry_points=lambda **_kw: [entry])
    )
    return s


def _share(store, data: bytes) -> str:
    obj = store.put_stream(
        store.root_folder_id(),
        "profile.json",
        "application/json",
        [data],
        properties={},
    )
    return f"drive:{obj.id}"


def _main(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    from starboard_x.diagnostic.__main__ import main

    with pytest.raises(SystemExit) as info:
        main(argv)
    return int(info.value.code), json.loads(capsys.readouterr().out)


@pytest.mark.unit
class TestProfileVerb:
    def test_public_local_file(self, tmp_path: Path) -> None:
        path = tmp_path / "profile.json"
        path.write_text(json.dumps(_PROFILE))
        proc = _run_cli("profile", "--input", str(path))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        env = _parse_envelope(proc)
        assert env["command"] == "profile"
        data = env["data"]
        assert data["format"] == "liquid"
        assert data["operator_count"] == 1
        assert data["scans"]["tables"] == [{"table": "main.s.t", "scans": 1}]
        assert "carol@example.com" not in proc.stdout

    def test_drive_object_from_the_memory_store(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        store,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin_overlay(monkeypatch, overlay=True)
        monkeypatch.chdir(tmp_path)
        ref = _share(store, json.dumps(_PROFILE).encode())
        code, env = _main(["profile", "--input", ref], capsys)
        assert code == 0, env
        assert env["data"]["query"]["id"] == "q-9"
        assert env["data"]["operator_count"] == 1
        # Nothing is written locally.
        assert [p for p in tmp_path.rglob("*") if p.is_file()] == []

    def test_overlay_local_file_is_refused_exit_2(self, tmp_path: Path) -> None:
        import os

        path = tmp_path / "profile.json"
        path.write_text(json.dumps(_PROFILE))
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "starboard_x.diagnostic",
                "profile",
                "--input",
                str(path),
            ],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
            env={**os.environ, "STARBOARD_OVERLAY": "1"},
        )
        assert proc.returncode == 2, proc.stdout + proc.stderr
        env = _parse_envelope(proc)
        assert env["error"].startswith("LOCAL_FILE_INTAKE_REFUSED: --input ")

    def test_oversize_drive_object_is_refused_before_read(
        self,
        monkeypatch: pytest.MonkeyPatch,
        store,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from starboard_x import _cli

        _pin_overlay(monkeypatch, overlay=True)
        monkeypatch.setattr(_cli, "MAX_INTAKE_BYTES", 4)
        ref = _share(store, json.dumps(_PROFILE).encode())
        code, env = _main(["profile", "--input", ref], capsys)
        assert code == 4
        assert "larger than 4 bytes" in env["error"]

    def test_oversize_local_file_is_refused_before_read(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from starboard_x import _cli

        _pin_overlay(monkeypatch, overlay=False)
        monkeypatch.setattr(_cli, "MAX_INTAKE_BYTES", 4)
        path = tmp_path / "profile.json"
        path.write_text(json.dumps(_PROFILE))

        def no_read(*_a: object, **_k: object) -> bytes:
            raise AssertionError("read before the size check")

        monkeypatch.setattr(Path, "read_bytes", no_read)
        code, env = _main(["profile", "--input", str(path)], capsys)
        assert code == 4
        assert "larger than 4 bytes" in env["error"]

    def test_invalid_json_is_arg_error(self, tmp_path: Path) -> None:
        path = tmp_path / "profile.json"
        path.write_text("{not json")
        proc = _run_cli("profile", "--input", str(path))
        assert proc.returncode == 4, proc.stdout
        assert "not valid JSON" in _parse_envelope(proc)["error"]

    def test_missing_file_is_arg_error(self, tmp_path: Path) -> None:
        proc = _run_cli("profile", "--input", str(tmp_path / "nope.json"))
        assert proc.returncode == 4, proc.stdout
        assert "file not found" in _parse_envelope(proc)["error"]

    def test_input_is_required(self) -> None:
        proc = _run_cli("profile")
        assert proc.returncode == 4, proc.stdout
