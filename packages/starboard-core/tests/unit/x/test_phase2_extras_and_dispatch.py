# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""D4 extras-taxonomy + dispatcher tests (Phase-2).

Verifies the Phase-1 declared-but-empty extras were filled with their real dep
sets (progressive_helpers/technical.md §4), that the diagnostics-core tier stays
stdlib-only (Phase-1 regression), and that the ``starboard-x`` dispatcher now
routes the four D4 domains.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[3]


def _extras() -> dict:
    with (_CORE_DIR / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["optional-dependencies"]


@pytest.mark.unit
class TestExtrasTaxonomyPhase2:
    def test_diagnostics_core_stays_stdlib_only(self) -> None:
        # Phase-1 regression: the stdlib-only tier must not grow deps.
        assert _extras()["diagnostics-core"] == []

    def test_discovery_pins_polars_connector_sdk(self) -> None:
        joined = " ".join(_extras()["discovery"]).lower()
        assert "polars" in joined
        assert "databricks-sql-connector" in joined
        assert "databricks-sdk" in joined

    def test_sparklog_pins_streaming_deps(self) -> None:
        joined = " ".join(_extras()["sparklog"]).lower()
        for dep in ("polars", "numpy", "stream-unzip", "httpx"):
            assert dep in joined, dep

    def test_sparklog_cloud_extras_layer_on_base(self) -> None:
        extras = _extras()
        assert any("boto3" in d for d in extras["sparklog-aws"])
        assert any("starboard-kernel[sparklog]" in d for d in extras["sparklog-aws"])
        assert any(
            "azure-storage-file-datalake" in d for d in extras["sparklog-azure"]
        )
        assert any("google-cloud-storage" in d for d in extras["sparklog-gcp"])

    def test_warehouse_pins_analyzer_deps(self) -> None:
        joined = " ".join(_extras()["warehouse"]).lower()
        assert "polars" in joined
        assert "sqlglot" in joined
        assert "databricks-sql-connector" in joined

    def test_uc_pins_sdk_and_connector(self) -> None:
        joined = " ".join(_extras()["uc"]).lower()
        assert "databricks-sdk" in joined
        assert "databricks-sql-connector" in joined

    def test_all_extra_aggregates_capabilities(self) -> None:
        joined = " ".join(_extras()["all"])
        for name in ("discovery", "sparklog", "warehouse", "uc"):
            assert name in joined, name


@pytest.mark.unit
class TestDispatcher:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "starboard_x", *args],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )

    @pytest.mark.parametrize("domain", ["discovery", "sparklog", "warehouse", "uc"])
    def test_dispatcher_routes_d4_domains(self, domain: str) -> None:
        # An unknown verb for a routed domain is an arg-error (exit 4) emitted by
        # that domain's own parser — proving the dispatch reached it.
        proc = self._run(domain, "definitely-not-a-verb")
        assert proc.returncode == 4, f"{domain}: {proc.stdout!r} {proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert env["domain"] == domain
        assert env["ok"] is False

    def test_dispatcher_still_lists_declared_stubs(self) -> None:
        # cluster/charts remain declared-but-unimplemented.
        proc = self._run("cluster", "health")
        assert proc.returncode == 4
        assert "not implemented" in proc.stderr.lower()
