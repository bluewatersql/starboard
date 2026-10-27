"""E13: ``job run-output`` / ``job code`` / ``diagnostic driver-log`` over autospec SDK fakes."""

from __future__ import annotations

import base64
import io

import pytest

from . import _j42
from ._support import (
    Ctx,
    autospec_client,
    clean,
    error_code,
    fake_run_output,
    helper,
    identity_keys,
    new_run,
    read_json,
)

EMAIL = "jo.analyst@acme.example"


def _sdk(monkeypatch: pytest.MonkeyPatch, *apis: str):
    w = autospec_client(*apis)
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def _failed():
    from databricks.sdk.service.jobs import RunLifeCycleState, RunResultState, RunState

    return RunState(
        life_cycle_state=RunLifeCycleState.TERMINATED,
        result_state=RunResultState.FAILED,
        state_message="failed",
    )


def _multi_task_run(w) -> None:
    from databricks.sdk.service.jobs import Run, RunOutput, RunTask

    w.jobs.get_run.return_value = Run(
        run_id=9001,
        job_id=42,
        state=_failed(),
        creator_user_name=EMAIL,
        tasks=[
            RunTask(task_key="ingest", run_id=9002, state=_failed()),
            RunTask(task_key="publish", run_id=9003, state=_failed()),
        ],
    )
    w.jobs.get_run_output.return_value = RunOutput(
        error=f"failed for {EMAIL}",
        error_trace=_j42.TRACE_OOM,
        logs="x" * 200 + f"\nlast line for {EMAIL}\n",
        logs_truncated=True,
        metadata=Run(run_id=9003, state=_failed(), creator_user_name=EMAIL),
    )


@pytest.mark.usefixtures("public")
def test_run_output_requires_task_key_on_multi_task_run(monkeypatch, capsys) -> None:
    w = _sdk(monkeypatch, "jobs")
    _multi_task_run(w)
    code, env, raw = helper(capsys, "job", "run-output", "--run-id", "9001")
    assert code == 4, raw
    assert "ingest" in raw and "publish" in raw
    w.jobs.get_run_output.assert_not_called()

    code, env, raw = helper(
        capsys,
        "job",
        "run-output",
        "--run-id",
        "9001",
        "--task-key",
        "publish",
        "--max-bytes",
        "64",
    )
    assert code == 0, raw
    w.jobs.get_run_output.assert_called_once_with(9003)
    data = env["data"]
    assert data["task_run_id"] == 9003 and data["task_key"] == "publish"
    assert data["logs_truncated"] is True
    assert data["truncated"]["logs"] is True
    assert len(data["logs"].encode()) <= 64
    assert "<email>" in data["logs"]
    assert identity_keys(data) == []
    assert "@" not in raw


@pytest.mark.usefixtures("public")
def test_job_code_exports_the_task_notebook(monkeypatch, capsys) -> None:
    from databricks.sdk.service.jobs import Job, JobSettings, NotebookTask, Task
    from databricks.sdk.service.workspace import ExportFormat, ExportResponse

    w = _sdk(monkeypatch, "jobs", "workspace")
    w.jobs.get.return_value = Job(
        job_id=42,
        creator_user_name=EMAIL,
        settings=JobSettings(
            name="j42",
            tasks=[
                Task(
                    task_key="ingest",
                    notebook_task=NotebookTask(notebook_path="/Shared/j42/ingest"),
                ),
            ],
        ),
    )
    source = f"# owner: {EMAIL}\n" + "print(1)\n" * 50
    w.workspace.export.return_value = ExportResponse(
        content=base64.b64encode(source.encode()).decode(), file_type="py"
    )
    code, env, raw = helper(
        capsys, "job", "code", "--job-id", "42", "--max-bytes", "128"
    )
    assert code == 0, raw
    w.workspace.export.assert_called_once_with(
        "/Shared/j42/ingest", format=ExportFormat.SOURCE
    )
    data = env["data"]
    assert (data["kind"], data["path"], data["task_key"]) == (
        "notebook",
        "/Shared/j42/ingest",
        "ingest",
    )
    assert data["truncated"] is True and len(data["code"].encode()) <= 128
    assert data["code"].startswith("# owner: <email>")
    assert identity_keys(data) == [] and "@" not in raw


@pytest.mark.usefixtures("public")
@pytest.mark.parametrize("kind", ["dbfs", "volumes"])
def test_driver_log_tails_the_delivery_destination(kind, monkeypatch, capsys) -> None:
    from databricks.sdk.service.compute import (
        ClusterDetails,
        ClusterLogConf,
        DbfsStorageInfo,
        VolumesStorageInfo,
    )
    from databricks.sdk.service.files import DownloadResponse, FileInfo, ReadResponse

    w = _sdk(monkeypatch, "clusters", "dbfs", "files")
    body = ("noise\n" * 100 + f"ERROR for {EMAIL}\n").encode()
    conf = (
        ClusterLogConf(dbfs=DbfsStorageInfo(destination="dbfs:/cluster-logs"))
        if kind == "dbfs"
        else ClusterLogConf(volumes=VolumesStorageInfo(destination="/Volumes/c/s/logs"))
    )
    w.clusters.get.return_value = ClusterDetails(
        cluster_id="c-1", cluster_log_conf=conf, creator_user_name=EMAIL
    )
    w.dbfs.get_status.return_value = FileInfo(file_size=len(body))
    w.dbfs.read.side_effect = lambda path, offset, length: ReadResponse(
        bytes_read=length,
        data=base64.b64encode(body[offset : offset + length]).decode(),
    )
    w.files.download.return_value = DownloadResponse(contents=io.BytesIO(body))

    code, env, raw = helper(
        capsys,
        "diagnostic",
        "driver-log",
        "--cluster-id",
        "c-1",
        "--stream",
        "stderr",
        "--tail-bytes",
        "64",
    )
    assert code == 0, raw
    data = env["data"]
    assert data["destination_kind"] == kind
    assert data["path"].endswith("/c-1/driver/stderr")
    assert data["bytes"] == len(body) and data["truncated"] is True
    assert data["content"].endswith("ERROR for <email>\n")
    assert identity_keys(data) == [] and "@" not in raw
    (w.dbfs.read if kind == "dbfs" else w.files.download).assert_called()


@pytest.mark.usefixtures("public")
def test_driver_log_without_delivery_is_a_gap(monkeypatch, capsys) -> None:
    from databricks.sdk.service.compute import ClusterDetails

    w = _sdk(monkeypatch, "clusters")
    w.clusters.get.return_value = ClusterDetails(cluster_id="c-1")
    code, env, raw = helper(capsys, "diagnostic", "driver-log", "--cluster-id", "c-1")
    assert code == 2, raw
    assert error_code(env).lower() == "cluster_log_delivery_off"


def test_run_output_on_covered_run_goes_only_to_the_sink(
    monkeypatch, capsys, store, sandbox, seams, tmp_path
) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, "drive_backed")
    run = new_run(ctx)
    assert run.rf
    fake_run_output(monkeypatch, run_id=9001, trace=f"{_j42.TRACE_OOM}\nby {EMAIL}")
    rel = "raw/job-run-output-9001.json"
    before = sandbox.snapshot()
    code, _env, raw = helper(
        capsys,
        "job",
        "run-output",
        "--run-id",
        "9001",
        "--run-folder",
        run.rf,
        "--out",
        rel,
    )
    assert code == 0, raw
    clean(sandbox, before, raw)
    assert "error_trace" not in raw and "@" not in raw
    stored = read_json(ctx, run, rel)
    data = stored.get("data", stored)
    assert data["task_run_id"] == 9002
    assert "<email>" in data["error_trace"]
    assert identity_keys(data) == []
