"""Live run 10: helper error text carries no SDK config, and an unseen endpoint says so.

The Databricks SDK appends ``. Config: host=..., account_id=..., auth_type=... .
Env: DATABRICKS_HOST`` to API error messages; the skills show ``error`` verbatim, so
that context landed in case reports. ``serving fetch --endpoint-id`` said "not found"
for an endpoint that exists but that the identity cannot view.
"""

from __future__ import annotations

import json

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.serving import ServingEndpoint
from starboard_skills.helpers.contract import ApiError, api_error_text, raise_api_error

from .conftest import run_main
from .test_serving_helper import EID, sdk  # noqa: F401  (fixture)

pytestmark = pytest.mark.unit

_SDK_MSG = (
    "User does not have View permission on endpoint x. Config: host=https://dbc-1.cloud."
    "databricks.com, account_id=abc-123, profile=e2, auth_type=databricks-cli. "
    "Env: DATABRICKS_HOST, DATABRICKS_TOKEN"
)


def test_api_error_text_drops_the_sdk_config_tail() -> None:
    text = api_error_text(PermissionDenied(_SDK_MSG))
    assert text == "User does not have View permission on endpoint x"
    assert api_error_text(ValueError("plain failure")) == "plain failure"
    assert api_error_text(ValueError("only env. Env: DATABRICKS_HOST")) == "only env"


def test_raise_api_error_message_has_no_config() -> None:
    with pytest.raises(ApiError) as caught:
        raise_api_error(PermissionDenied(_SDK_MSG))
    msg = caught.value.message
    assert msg == "API error: User does not have View permission on endpoint x"
    for leak in ("Config:", "host=", "account_id", "auth_type", "DATABRICKS_"):
        assert leak not in msg


def test_unseen_endpoint_id_says_it_may_lack_view_permission(sdk, capsys) -> None:  # noqa: F811
    sdk.serving_endpoints.list.return_value = iter(
        [ServingEndpoint(id="other", name="o")]
    )
    code, out = run_main(["serving", "fetch", "--endpoint-id", EID], capsys)
    assert code == 2, out
    error = json.loads(out)["error"]
    assert error.startswith(f"Serving endpoint {EID} not found")
    assert "View permission" in error and "--endpoint-name" in error


def test_identical_staged_records_read_as_one() -> None:
    # Run 11: a retried upload left two identical storage-preflight.json records.
    from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
    from starboard_core.ports.engagement_storage import StorageIntegrityError
    from starboard_skills.helpers.engagement import _runs
    from starboard_skills.helpers.engagement._envelope import ARTIFACT_PROPERTY

    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    tag = {ARTIFACT_PROPERTY: "preflight:r1"}
    for _ in range(2):
        store.put_stream(
            root,
            "storage-preflight.json",
            "application/json",
            [b'{"run_id": "r1"}'],
            properties=tag,
        )
    assert _runs._read_staged(
        store, root, "storage-preflight.json", "preflight:r1"
    ) == {"run_id": "r1"}
    store.put_stream(
        root,
        "storage-preflight.json",
        "application/json",
        [b'{"run_id": "other"}'],
        properties=tag,
    )
    with pytest.raises(StorageIntegrityError, match="3 staged"):
        _runs._read_staged(store, root, "storage-preflight.json", "preflight:r1")
