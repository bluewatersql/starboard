# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``sparklog parse`` never emits an identity (D3-24).

``spark_params`` is cut to the tuning / sizing allowlist (``clusterAllTags``,
``clusterName``, ``clusterOwnerUserId``, credentials dropped) and the whole emitted
payload is identity-scrubbed on both the ``--input`` and ``--source`` paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

EMAIL = "jane@example.com"
_TAGS = "spark.databricks.clusterUsageTags"

_SPARK_PARAMS: dict[str, Any] = {
    "spark.app.id": "app-1",
    "spark.app.name": f"etl for {EMAIL}",
    "spark.executor.memory": "8g",
    "spark.executor.cores": "4",
    "spark.driver.memory": "16g",
    "spark.sql.shuffle.partitions": "200",
    "spark.sql.adaptive.enabled": "true",
    "spark.dynamicAllocation.enabled": "false",
    "spark.databricks.delta.optimizeWrite.enabled": "true",
    f"{_TAGS}.sparkVersion": "15.4.x-scala2.12",
    f"{_TAGS}.clusterId": "0101-abc",
    f"{_TAGS}.clusterNodeType": "i3.xlarge",
    f"{_TAGS}.clusterAllTags": json.dumps([{"key": "Creator", "value": EMAIL}]),
    f"{_TAGS}.clusterName": "Jane Doe's Cluster",
    f"{_TAGS}.clusterOwnerUserId": "1234567890",
    f"{_TAGS}.clusterCreator": "JobLauncher",
    "spark.hadoop.fs.s3a.secret.key": "s3cr3t",
    "spark.sql.warehouse.token": "dapi-not-a-real-token",
    "spark.driver.host": "10.0.0.1",
}
_KEPT = {
    "spark.app.id",
    "spark.executor.memory",
    "spark.executor.cores",
    "spark.driver.memory",
    "spark.sql.shuffle.partitions",
    "spark.sql.adaptive.enabled",
    "spark.dynamicAllocation.enabled",
    "spark.databricks.delta.optimizeWrite.enabled",
    f"{_TAGS}.sparkVersion",
    f"{_TAGS}.clusterId",
    f"{_TAGS}.clusterNodeType",
}

_PARSED_APP = {
    "metadata": {
        "application_info": {
            "id": "app-1",
            "name": f"etl for {EMAIL}",
            "timestamp_start_ms": 1000,
            "timestamp_end_ms": 2000,
            "runtime_sec": 1,
            "spark_version": "3.4.0",
        },
        "spark_params": _SPARK_PARAMS,
        "existsSQL": False,
        "existsExecutors": False,
    },
    "jobData": [],
    "stageData": [],
    "taskData": [],
    "accumData": [],
}


def _main(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    from starboard_x.sparklog.__main__ import main

    with pytest.raises(SystemExit) as info:
        main(argv)
    return int(info.value.code), capsys.readouterr().out


def _assert_scrubbed(out: str) -> dict[str, Any]:
    assert "@" not in out
    assert "Jane Doe" not in out
    assert "s3cr3t" not in out and "dapi-" not in out
    metadata = json.loads(out)["data"]["metadata"]
    assert set(metadata["spark_params"]) == _KEPT
    assert metadata["spark_params"]["spark.executor.memory"] == "8g"
    assert metadata["application_info"]["name"] == "etl for <email>"
    return metadata


@pytest.mark.unit
class TestSparklogIdentityScrub:
    def test_input_path_is_allowlisted_and_scrubbed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from starboard_core.engagement.overlay import OverlaySignal
        from starboard_x import _cli

        monkeypatch.setattr(
            _cli, "detect_overlay", lambda **_k: OverlaySignal(enabled=False)
        )
        log = tmp_path / "eventlog.json"
        log.write_text(json.dumps(_PARSED_APP))

        code, out = _main(["parse", "--input", str(log)], capsys)
        assert code == 0, out
        _assert_scrubbed(out)

    def test_source_path_is_allowlisted_and_scrubbed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from starboard_core import log_parser
        from starboard_x.sparklog import __main__ as sparklog

        log = tmp_path / "eventlog.json"
        log.write_text(json.dumps(_PARSED_APP))
        app = log_parser.create_spark_application(path=str(log))
        monkeypatch.setattr(sparklog, "_check_source_available", lambda _s: None)
        monkeypatch.setattr(log_parser, "create_spark_application", lambda **_k: app)

        code, out = _main(
            ["parse", "--source", "https", "--path", f"https://h/{EMAIL}/log"],
            capsys,
        )
        assert code == 0, out
        _assert_scrubbed(out)
        assert json.loads(out)["data"]["path"] == "https://h/<email>/log"

    def test_allowlist_rejects_identity_and_credential_keys(self) -> None:
        from starboard_x.sparklog.__main__ import _allowed_spark_params

        assert set(_allowed_spark_params(_SPARK_PARAMS)) == _KEPT
        assert _allowed_spark_params(None) == {}
