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


def _run_cli(
    *args: str, input_files: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m starboard_x.diagnostic <args>`` from the core dir."""
    return subprocess.run(
        [sys.executable, "-m", "starboard_x.diagnostic", *args],
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
