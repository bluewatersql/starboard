"""The ``_fetch`` identity scrub on the older acquiring verbs (D3-24).

``job fetch`` / ``cluster fetch`` / ``uc table`` / ``--out`` must never emit an email:
user-name / email keys are dropped, and an ``owner`` that is a user reads as
``<email>`` (still set) while a group owner is kept verbatim.
"""

from __future__ import annotations

import json
import typing
from unittest.mock import create_autospec

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import TableInfo
from databricks.sdk.service.compute import ClusterDetails
from databricks.sdk.service.jobs import (
    Job,
    JobEmailNotifications,
    JobRunAs,
    JobSettings,
    NotebookTask,
    Task,
)

from .conftest import run_main

EMAIL = "jane@example.com"


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch):
    w = create_autospec(WorkspaceClient, instance=True)
    for name in ("jobs", "clusters", "tables"):
        api_type = typing.get_type_hints(getattr(WorkspaceClient, name).fget)["return"]
        setattr(w, name, create_autospec(api_type, instance=True))
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


@pytest.mark.unit
class TestFetchIdentityScrub:
    def test_job_fetch_settings_are_scrubbed(self, sdk, capsys):
        sdk.jobs.get.return_value = Job(
            job_id=7,
            creator_user_name=EMAIL,
            settings=JobSettings(
                name="nightly",
                email_notifications=JobEmailNotifications(on_failure=[EMAIL]),
                run_as=JobRunAs(user_name=EMAIL),
                tasks=[
                    Task(
                        task_key="t",
                        notebook_task=NotebookTask(notebook_path=f"/Users/{EMAIL}/etl"),
                    )
                ],
            ),
        )
        code, out = run_main(["job", "fetch", "--job-id", "7"], capsys)
        assert code == 0, out
        assert "@" not in out
        settings = json.loads(out)["data"]["settings"]
        assert "email_notifications" not in settings
        assert settings["run_as"] == {}
        task = settings["tasks"][0]
        assert task["notebook_task"]["notebook_path"] == "/Users/<email>/etl"
        assert settings["name"] == "nightly"

    def test_job_fetch_service_principal_run_as_kept(self, sdk, capsys):
        sp = "6f1e1c3a-0000-4000-8000-000000000001"
        sdk.jobs.get.return_value = Job(
            job_id=8,
            settings=JobSettings(name="j", run_as=JobRunAs(service_principal_name=sp)),
        )
        code, out = run_main(["job", "fetch", "--job-id", "8"], capsys)
        assert code == 0, out
        assert json.loads(out)["data"]["settings"]["run_as"] == {
            "service_principal_name": sp
        }

    def test_cluster_fetch_drops_creator(self, sdk, capsys):
        sdk.clusters.get.return_value = ClusterDetails(
            cluster_id="0101-abc",
            cluster_name=f"{EMAIL}'s cluster",
            creator_user_name=EMAIL,
            num_workers=2,
        )
        code, out = run_main(["cluster", "fetch", "--cluster-id", "0101-abc"], capsys)
        assert code == 0, out
        assert "@" not in out
        data = json.loads(out)["data"]
        assert "creator_user_name" not in data
        assert data["cluster_name"] == "<email>'s cluster"
        assert data["num_workers"] == 2

    @pytest.mark.parametrize(
        ("owner", "expected"),
        [(EMAIL, "<email>"), ("data-eng", "data-eng"), (None, None)],
    )
    def test_uc_owner_is_redacted_not_dropped(self, sdk, capsys, owner, expected):
        sdk.tables.get.return_value = TableInfo(
            name="t", catalog_name="c", schema_name="s", owner=owner
        )
        code, out = run_main(["uc", "table", "--full-name", "c.s.t"], capsys)
        assert code == 0, out
        data = json.loads(out)["data"]
        assert data.get("owner") == expected  # as_dict() omits a None owner
        assert "@" not in out

    def test_out_file_is_scrubbed(self, sdk, capsys, tmp_path):
        sdk.tables.get.return_value = TableInfo(
            name="t", catalog_name="c", schema_name="s", owner=EMAIL
        )
        target = tmp_path / "table.json"
        code, out = run_main(
            ["uc", "table", "--full-name", "c.s.t", "--out", str(target)], capsys
        )
        assert code == 0, out
        written = target.read_text()
        assert "@" not in written and "<email>" in written
