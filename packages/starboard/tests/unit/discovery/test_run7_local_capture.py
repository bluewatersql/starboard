# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 7: a local run directory keeps a resumable capture too.

An internal-only local discovery ran ~11 minutes, past the host's command limit,
with nothing to resume. ``EngineConfig(capture_sink=...)`` keeps the capture
record in a local run directory while the report stays on ``output_dir``
(``sink`` unset).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starboard.discovery.engine import DiscoveryEngine, EngineConfig
from starboard_core.domain.models.discovery.capture import PROGRESS_PATH
from starboard_core.engagement.policy import StorageDecision, StoragePolicy
from starboard_core.engagement.sink import LocalDirSink

from tests.unit.discovery.test_run6b_capture_resume import _Exec, _Registry

_LOCAL = StorageDecision(StoragePolicy.LOCAL, False, "local run directory")


def _engine(executor: _Exec, run_dir: Path) -> DiscoveryEngine:
    engine = DiscoveryEngine(
        sql_executor=executor,
        llm_client=None,
        config=EngineConfig(
            data_only=True,
            enable_cache=False,
            capture=True,
            capture_sink=LocalDirSink(run_dir, decision=_LOCAL, run_id="run-1"),
        ),
        query_registry=_Registry(),  # type: ignore[arg-type]
    )
    engine._pack_executor._timeout_backoff_s = (0.0,)
    return engine


@pytest.mark.unit
async def test_a_local_run_dir_capture_is_resumed(tmp_path: Path) -> None:
    first = await _engine(_Exec(), tmp_path).run()
    assert first.resumed == {"queries_reused": 0}
    record = json.loads((tmp_path / PROGRESS_PATH).read_text())
    assert record["key"]["run_id"] == "run-1"

    again = _Exec()
    second = await _engine(again, tmp_path).run()
    assert again.calls == []
    assert second.resumed == {"queries_reused": 4}
