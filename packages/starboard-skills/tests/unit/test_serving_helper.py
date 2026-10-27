"""``serving fetch`` against an autospec SDK client.

Run 7: a serving step-change finding had no way to read the endpoint's own config
(scale to zero, workload size, concurrency). System tables carry the served entities
but not scale to zero, so the helper reads it from the serving endpoints API.
"""

from __future__ import annotations

import json
import typing
from unittest.mock import create_autospec

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.serving import (
    EndpointCoreConfigOutput,
    EndpointPendingConfig,
    EndpointState,
    EndpointStateConfigUpdate,
    EndpointStateReady,
    EndpointTag,
    ExternalModel,
    ExternalModelProvider,
    OpenAiConfig,
    Route,
    ServedEntityOutput,
    ServedModelOutput,
    ServingEndpoint,
    ServingEndpointDetailed,
    ServingModelWorkloadType,
    TrafficConfig,
)
from starboard_skills.helpers import discovery

from .conftest import covered_ok, drive_files, run_main

EID = "ac0d807e5b2444098eadd51cd75b1691"
NAME = "churn-model"


def autospec_client(*apis: str):
    w = create_autospec(WorkspaceClient, instance=True)
    for name in apis:
        api_type = typing.get_type_hints(getattr(WorkspaceClient, name).fget)["return"]
        setattr(w, name, create_autospec(api_type, instance=True))
    return w


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch):
    w = autospec_client("serving_endpoints")
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def _data(out: str) -> dict:
    payload = json.loads(out)
    assert payload["ok"], payload
    return payload["data"]


def _endpoint() -> ServingEndpointDetailed:
    return ServingEndpointDetailed(
        id=EID,
        name=NAME,
        creator="alice@corp.com",
        task="llm/v1/chat",
        state=EndpointState(
            ready=EndpointStateReady.READY,
            config_update=EndpointStateConfigUpdate.NOT_UPDATING,
        ),
        creation_timestamp=1_700_000_000_000,
        last_updated_timestamp=1_760_000_000_000,
        route_optimized=False,
        tags=[EndpointTag(key="team", value="ml")],
        config=EndpointCoreConfigOutput(
            config_version=4,
            served_entities=[
                ServedEntityOutput(
                    name="churn-1",
                    entity_name="main.ml.churn",
                    entity_version="3",
                    workload_type=ServingModelWorkloadType.GPU_SMALL,
                    workload_size="Medium",
                    scale_to_zero_enabled=False,
                    min_provisioned_concurrency=4,
                    max_provisioned_concurrency=16,
                    creator="alice@corp.com",
                    environment_vars={
                        "API_TOKEN": "{{secrets/scope/key}}",
                        "RAW": "s3cr3t",
                    },
                    instance_profile_arn="arn:aws:iam::1:instance-profile/x",
                ),
                ServedEntityOutput(
                    name="gpt",
                    external_model=ExternalModel(
                        provider=ExternalModelProvider.OPENAI,
                        name="gpt-4o",
                        task="llm/v1/chat",
                        openai_config=OpenAiConfig(
                            openai_api_key_plaintext="sk-live-secret"
                        ),
                    ),
                ),
            ],
            traffic_config=TrafficConfig(
                routes=[Route(served_entity_name="churn-1", traffic_percentage=100)]
            ),
        ),
        pending_config=EndpointPendingConfig(
            config_version=5,
            start_time=1_760_000_100_000,
            served_models=[
                ServedModelOutput(
                    name="churn-2",
                    model_name="churn",
                    model_version="4",
                    workload_size="Small",
                    scale_to_zero_enabled=True,
                )
            ],
        ),
    )


@pytest.mark.unit
class TestFetch:
    def test_by_name_reads_the_scaling_config(self, sdk, capsys):
        sdk.serving_endpoints.get.return_value = _endpoint()
        code, out = run_main(["serving", "fetch", "--endpoint-name", NAME], capsys)
        assert code == 0, out
        sdk.serving_endpoints.get.assert_called_once_with(NAME)
        data = _data(out)
        assert (data["endpoint_id"], data["name"], data["config_version"]) == (
            EID,
            NAME,
            4,
        )
        assert data["state"] == {"ready": "READY", "config_update": "NOT_UPDATING"}
        first, ext = data["served_entities"]
        assert first["scale_to_zero_enabled"] is False
        assert (first["workload_type"], first["workload_size"]) == (
            "GPU_SMALL",
            "Medium",
        )
        assert (
            first["min_provisioned_concurrency"],
            first["max_provisioned_concurrency"],
        ) == (4, 16)
        assert (first["entity_name"], first["entity_version"]) == ("main.ml.churn", "3")
        assert ext["external_model"] == {
            "provider": "openai",
            "name": "gpt-4o",
            "task": "llm/v1/chat",
        }
        assert data["traffic_routes"] == [
            {"served_entity_name": "churn-1", "traffic_percentage": 100}
        ]
        pending = data["pending_config"]
        assert pending["config_version"] == 5
        assert pending["served_entities"][0]["scale_to_zero_enabled"] is True
        assert pending["served_entities"][0]["entity_name"] == "churn"

    def test_secrets_and_identity_never_leave(self, sdk, capsys):
        sdk.serving_endpoints.get.return_value = _endpoint()
        _, out = run_main(["serving", "fetch", "--endpoint-name", NAME], capsys)
        for secret in (
            "sk-live-secret",
            "s3cr3t",
            "secrets/scope",
            "alice",
            "instance-profile",
        ):
            assert secret not in out, secret
        first = _data(out)["served_entities"][0]
        # The variable names say what the model reads; the values are dropped.
        assert first["environment_var_names"] == ["API_TOKEN", "RAW"]

    def test_by_id_resolves_the_name(self, sdk, capsys):
        sdk.serving_endpoints.list.return_value = iter(
            [
                ServingEndpoint(id="other", name="other"),
                ServingEndpoint(id=EID, name=NAME),
            ]
        )
        sdk.serving_endpoints.get.return_value = _endpoint()
        code, out = run_main(["serving", "fetch", "--endpoint-id", EID], capsys)
        assert code == 0, out
        sdk.serving_endpoints.get.assert_called_once_with(NAME)
        assert _data(out)["endpoint_id"] == EID

    def test_unknown_id_exits_2(self, sdk, capsys):
        sdk.serving_endpoints.list.return_value = iter(
            [ServingEndpoint(id="other", name="other")]
        )
        code, out = run_main(["serving", "fetch", "--endpoint-id", EID], capsys)
        assert code == 2, out
        # Run 10: the list shows only viewable endpoints, so the message says so.
        assert json.loads(out)["error"].startswith(f"Serving endpoint {EID} not found ")
        sdk.serving_endpoints.get.assert_not_called()

    def test_unknown_name_exits_2(self, sdk, capsys):
        sdk.serving_endpoints.get.side_effect = NotFound("Endpoint x does not exist")
        code, out = run_main(["serving", "fetch", "--endpoint-name", "x"], capsys)
        assert code == 2, out
        assert json.loads(out)["error"] == "Serving endpoint x not found"

    def test_list_api_error_exits_3(self, sdk, capsys):
        # A list failure on the --endpoint-id path is an API error, not "not found".
        sdk.serving_endpoints.list.side_effect = PermissionDenied("no access")
        code, out = run_main(["serving", "fetch", "--endpoint-id", EID], capsys)
        assert code == 3, out
        payload = json.loads(out)
        assert payload["ok"] is False and "not found" not in payload["error"]
        sdk.serving_endpoints.get.assert_not_called()

    def test_list_timeout_is_retryable(self, sdk, capsys):
        sdk.serving_endpoints.list.side_effect = TimeoutError("timed out after 300s")
        code, out = run_main(["serving", "fetch", "--endpoint-id", EID], capsys)
        assert code == 3, out
        assert "WORKSPACE_TIMEOUT" in out
        sdk.serving_endpoints.get.assert_not_called()

    @pytest.mark.parametrize(
        "argv",
        [
            ["serving", "fetch"],
            ["serving", "fetch", "--endpoint-name", NAME, "--endpoint-id", EID],
        ],
        ids=["neither", "both"],
    )
    def test_exactly_one_selector(self, sdk, capsys, argv):
        code, _ = run_main(argv, capsys)
        assert code == 4

    def test_run_folder_writes_through_the_sink(
        self, covered_env, drive_run, sdk, capsys
    ):
        sdk.serving_endpoints.get.return_value = _endpoint()
        before = covered_env.snapshot()
        code, out = run_main(
            [
                "serving",
                "fetch",
                "--endpoint-name",
                NAME,
                "--run-folder",
                drive_run.folder_id,
                "--out",
                f"raw/serving-{EID}.json",
            ],
            capsys,
        )
        assert code == 0, out
        covered_ok(covered_env, before, out)
        stored = drive_files(drive_run)[f"raw/serving-{EID}.json"]
        assert b"@" not in stored and b"sk-live" not in stored
        assert json.loads(stored)["data"]["endpoint_id"] == EID


@pytest.mark.unit
def test_the_catalog_lists_the_serving_domain():
    entry = next(d for d in discovery.DOMAIN_CATALOG if d["name"] == "serving")
    assert entry["commands"] == ["fetch"]
