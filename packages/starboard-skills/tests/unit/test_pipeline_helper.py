"""``pipeline fetch`` / ``updates`` / ``events`` against an autospec SDK client."""

from __future__ import annotations

import json
import typing
from unittest.mock import create_autospec

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.pipelines import (
    ErrorDetail,
    EventLevel,
    GetPipelineResponse,
    GetPipelineResponseHealth,
    ListUpdatesResponse,
    Notifications,
    Origin,
    PipelineEvent,
    PipelineSpec,
    PipelineState,
    RunAs,
    SerializedException,
    StackFrame,
    UpdateInfo,
    UpdateInfoState,
    UpdateStateInfo,
    UpdateStateInfoState,
)
from starboard_skills.helpers import pipeline

from .conftest import covered_ok, drive_files, run_main

PID = "p-1234"


def autospec_client(*apis: str):
    """An autospec ``WorkspaceClient`` whose named sub-APIs are autospecced too."""
    w = create_autospec(WorkspaceClient, instance=True)
    for name in apis:
        api_type = typing.get_type_hints(getattr(WorkspaceClient, name).fget)["return"]
        setattr(w, name, create_autospec(api_type, instance=True))
    return w


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch):
    w = autospec_client("pipelines")
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def _data(out: str) -> dict:
    payload = json.loads(out)
    assert payload["ok"], payload
    return payload["data"]


def _pipeline() -> GetPipelineResponse:
    return GetPipelineResponse(
        pipeline_id=PID,
        name="orders",
        state=PipelineState.FAILED,
        health=GetPipelineResponseHealth.UNHEALTHY,
        cause="update failed",
        cluster_id="0612-abc",
        creator_user_name="alice@corp.com",
        run_as_user_name="alice@corp.com",
        run_as=RunAs(user_name="alice@corp.com"),
        last_modified=1_700_000_000_000,
        latest_updates=[
            UpdateStateInfo(
                update_id="u-2", state=UpdateStateInfoState.FAILED, creation_time="t2"
            )
        ],
        spec=PipelineSpec(
            id=PID,
            name="orders",
            serverless=True,
            channel="CURRENT",
            edition="ADVANCED",
            continuous=False,
            development=False,
            photon=True,
            catalog="main",
            schema="sales",
            notifications=[Notifications(email_recipients=["bob@corp.com"])],
        ),
    )


def _event(i: int, update_id: str = "u-2", **over) -> PipelineEvent:
    base = {
        "id": f"e-{i}",
        "timestamp": f"2026-10-01T00:00:{i:02d}Z",
        "level": EventLevel.INFO,
        "event_type": "flow_progress",
        "message": f"flow step {i}",
        "origin": Origin(
            update_id=update_id,
            flow_name="orders_silver",
            pipeline_id=PID,
            org_id=123,
            host="https://example.cloud.databricks.com",
        ),
    }
    base.update(over)
    return PipelineEvent(**base)


@pytest.mark.unit
class TestFetch:
    def test_spec_state_and_identity_scrubbed(self, sdk, capsys):
        sdk.pipelines.get.return_value = _pipeline()
        code, out = run_main(["pipeline", "fetch", "--pipeline-id", PID], capsys)
        assert code == 0, out
        data = _data(out)
        assert (data["pipeline_id"], data["state"], data["health"]) == (
            PID, "FAILED", "UNHEALTHY"
        )
        assert data["serverless"] is True and data["catalog"] == "main"
        assert data["target_schema"] == "sales"
        assert data["latest_updates"][0]["update_id"] == "u-2"
        assert "@" not in out
        assert "run_as" not in out and "creator_user_name" not in out
        sdk.pipelines.get.assert_called_once_with(PID)

    def test_not_found_exits_2(self, sdk, capsys):
        sdk.pipelines.get.side_effect = NotFound("Pipeline p-x not found")
        code, out = run_main(["pipeline", "fetch", "--pipeline-id", "p-x"], capsys)
        assert code == 2, out
        assert json.loads(out)["error"] == "Pipeline p-x not found"

    def test_run_folder_writes_through_the_sink(self, covered_env, drive_run, sdk, capsys):
        sdk.pipelines.get.return_value = _pipeline()
        before = covered_env.snapshot()
        code, out = run_main(
            [
                "pipeline", "fetch", "--pipeline-id", PID,
                "--run-folder", drive_run.folder_id, "--out", "raw/pipeline.json",
            ],
            capsys,
        )
        assert code == 0, out
        covered_ok(covered_env, before, out)
        stored = drive_files(drive_run)["raw/pipeline.json"]
        assert b"@" not in stored
        assert json.loads(stored)["data"]["pipeline_id"] == PID


@pytest.mark.unit
class TestUpdates:
    def _update(self, n: int) -> UpdateInfo:
        return UpdateInfo(
            update_id=f"u-{n}",
            pipeline_id=PID,
            state=UpdateInfoState.FAILED,
            creation_time=n,
            config=PipelineSpec(id=PID, name="orders"),
        )

    def test_pages_to_the_limit_and_drops_the_spec_snapshot(self, sdk, capsys):
        sdk.pipelines.list_updates.side_effect = [
            ListUpdatesResponse(updates=[self._update(1), self._update(2)], next_page_token="t"),
            ListUpdatesResponse(updates=[self._update(3), self._update(4)], next_page_token="t2"),
        ]
        code, out = run_main(
            ["pipeline", "updates", "--pipeline-id", PID, "--limit", "3"], capsys
        )
        assert code == 0, out
        data = _data(out)
        assert [u["update_id"] for u in data["updates"]] == ["u-1", "u-2", "u-3"]
        assert data["count"] == 3 and data["has_more"] is True
        assert all("config" not in u for u in data["updates"])
        second = sdk.pipelines.list_updates.call_args_list[1]
        assert second.kwargs == {"max_results": 1, "page_token": "t"}

    def test_last_page_is_not_more(self, sdk, capsys):
        sdk.pipelines.list_updates.return_value = ListUpdatesResponse(
            updates=[self._update(1)]
        )
        code, out = run_main(["pipeline", "updates", "--pipeline-id", PID], capsys)
        assert code == 0, out
        assert _data(out)["has_more"] is False

    @pytest.mark.parametrize("limit", ["0", "101", "x"])
    def test_limit_outside_the_cap_exits_4(self, sdk, capsys, limit):
        code, out = run_main(
            ["pipeline", "updates", "--pipeline-id", PID, "--limit", limit], capsys
        )
        assert code == 4, out
        sdk.pipelines.list_updates.assert_not_called()


@pytest.mark.unit
class TestEvents:
    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            ("ERROR", "level='ERROR'"),
            ("WARN", "level in ('ERROR', 'WARN')"),
            ("INFO", "level in ('ERROR', 'WARN', 'INFO')"),
        ],
    )
    def test_level_is_a_minimum_severity_filter(self, level, expected):
        assert pipeline._level_filter(level) == expected

    def test_error_events_keep_exceptions_and_stack_heads(self, sdk, capsys):
        stack = [
            StackFrame(declaring_class="Foo", method_name=f"m{i}", file_name="F.scala",
                       line_number=i)
            for i in range(pipeline.STACK_FRAMES_MAX + 5)
        ]
        sdk.pipelines.list_pipeline_events.return_value = iter(
            [
                _event(
                    1,
                    level=EventLevel.ERROR,
                    message="update failed for alice@corp.com",
                    error=ErrorDetail(
                        fatal=True,
                        exceptions=[
                            SerializedException(
                                class_name="AnalysisException",
                                message="Table not found; owner bob@corp.com",
                                stack=stack,
                            )
                        ],
                    ),
                )
            ]
        )
        code, out = run_main(
            ["pipeline", "events", "--pipeline-id", PID, "--level", "ERROR"], capsys
        )
        assert code == 0, out
        (event,) = _data(out)["events"]
        assert event["level"] == "ERROR" and event["error"]["fatal"] is True
        (exc,) = event["error"]["exceptions"]
        assert exc["class_name"] == "AnalysisException"
        assert exc["stack_frames"] == pipeline.STACK_FRAMES_MAX + 5
        assert len(exc["stack"]) == pipeline.STACK_FRAMES_MAX
        assert exc["stack"][0] == "Foo.m0(F.scala:0)"
        assert "@" not in out
        # Origin keeps the flow, not workspace plumbing (host / org).
        assert event["origin"] == {"update_id": "u-2", "flow_name": "orders_silver"}
        kwargs = sdk.pipelines.list_pipeline_events.call_args.kwargs
        assert kwargs["filter"] == "level='ERROR'"

    def test_limit_bounds_the_events_read(self, sdk, capsys):
        sdk.pipelines.list_pipeline_events.return_value = iter(
            [_event(i) for i in range(30)]
        )
        code, out = run_main(
            ["pipeline", "events", "--pipeline-id", PID, "--limit", "5"], capsys
        )
        assert code == 0, out
        data = _data(out)
        assert data["count"] == 5 and data["scanned"] == 5
        assert data["scan_capped"] is False

    def test_update_id_is_matched_on_the_event_origin(self, sdk, capsys):
        sdk.pipelines.list_pipeline_events.return_value = iter(
            [_event(1, "u-1"), _event(2, "u-2"), _event(3, "u-1"), _event(4, "u-2")]
        )
        code, out = run_main(
            ["pipeline", "events", "--pipeline-id", PID, "--update-id", "u-2"], capsys
        )
        assert code == 0, out
        data = _data(out)
        assert [e["id"] for e in data["events"]] == ["e-2", "e-4"]
        assert data["scanned"] == 4 and data["update_id"] == "u-2"

    def test_update_scan_is_capped(self, sdk, capsys, monkeypatch):
        monkeypatch.setattr(pipeline, "EVENTS_SCAN_MAX", 10)
        sdk.pipelines.list_pipeline_events.return_value = iter(
            [_event(i, "u-other") for i in range(50)]
        )
        code, out = run_main(
            ["pipeline", "events", "--pipeline-id", PID, "--update-id", "u-2"], capsys
        )
        assert code == 0, out
        data = _data(out)
        assert data["count"] == 0 and data["scanned"] == 10
        assert data["scan_capped"] is True

    def test_text_fields_are_clipped(self, sdk, capsys):
        sdk.pipelines.list_pipeline_events.return_value = iter(
            [_event(1, message="x" * 5000)]
        )
        code, out = run_main(
            ["pipeline", "events", "--pipeline-id", PID, "--max-bytes", "1024"], capsys
        )
        assert code == 0, out
        data = _data(out)
        assert len(data["events"][0]["message"].encode()) <= 1024 + 64
        assert data["truncated_fields"] == 1

    @pytest.mark.parametrize(
        "argv",
        [
            ["--limit", "501"],
            ["--level", "DEBUG"],
            ["--update-id", "bad id'"],
        ],
    )
    def test_bad_arguments_exit_4(self, sdk, capsys, argv):
        code, out = run_main(["pipeline", "events", "--pipeline-id", PID, *argv], capsys)
        assert code == 4, out
        sdk.pipelines.list_pipeline_events.assert_not_called()

    def test_not_found_exits_2(self, sdk, capsys):
        sdk.pipelines.list_pipeline_events.side_effect = NotFound("Pipeline p-x not found")
        code, out = run_main(["pipeline", "events", "--pipeline-id", "p-x"], capsys)
        assert code == 2, out
