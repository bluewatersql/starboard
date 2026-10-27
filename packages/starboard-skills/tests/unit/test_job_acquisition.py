"""``job run-output`` and ``job code`` against an autospec SDK client (spec §F, D3-24)."""

from __future__ import annotations

import base64
import json
import typing
from unittest.mock import create_autospec

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import (
    GitSource,
    Job,
    JobSettings,
    NotebookOutput,
    NotebookTask,
    Run,
    RunLifeCycleState,
    RunOutput,
    RunResultState,
    RunState,
    RunTask,
    Source,
    SparkPythonTask,
    SqlTask,
    SqlTaskFile,
    Task,
)
from databricks.sdk.service.workspace import ExportFormat, ExportResponse

from .conftest import covered_ok, drive_files, run_main

RUN_ID = 900
FAILED = RunState(
    life_cycle_state=RunLifeCycleState.TERMINATED,
    result_state=RunResultState.FAILED,
    state_message="boom",
)


def autospec_client(*apis: str):
    """An autospec ``WorkspaceClient`` whose named sub-APIs are autospecced too."""
    w = create_autospec(WorkspaceClient, instance=True)
    for name in apis:
        api_type = typing.get_type_hints(getattr(WorkspaceClient, name).fget)["return"]
        setattr(w, name, create_autospec(api_type, instance=True))
    return w


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch):
    w = autospec_client("jobs", "workspace")
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def _run(*task_keys: str) -> Run:
    return Run(
        run_id=RUN_ID,
        job_id=42,
        state=FAILED,
        creator_user_name="alice@corp.com",
        tasks=[
            RunTask(task_key=k, run_id=1000 + i, state=FAILED)
            for i, k in enumerate(task_keys)
        ],
    )


def _output(**over) -> RunOutput:
    base = {
        "error": "Failed for alice@corp.com",
        "error_trace": "Traceback ...\nValueError: bad row owner=bob@corp.com",
        "logs": "line\n" * 10 + "contact carol@corp.com\n",
        "logs_truncated": True,
        "notebook_output": NotebookOutput(
            result="done by dave@corp.com", truncated=False
        ),
        "metadata": Run(run_id=1000, state=FAILED, creator_user_name="alice@corp.com"),
    }
    base.update(over)
    return RunOutput(**base)


def _identity_keys(obj) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.endswith(("user_name", "user_id")) or "email" in k:
                found.append(k)
            found += _identity_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            found += _identity_keys(v)
    return found


@pytest.mark.unit
class TestRunOutput:
    def test_single_task_run_needs_no_task_key(self, sdk, capsys):
        sdk.jobs.get_run.return_value = _run("ingest")
        sdk.jobs.get_run_output.return_value = _output()
        code, out = run_main(["job", "run-output", "--run-id", str(RUN_ID)], capsys)
        assert code == 0, out
        sdk.jobs.get_run.assert_called_once_with(RUN_ID)
        sdk.jobs.get_run_output.assert_called_once_with(1000)
        data = json.loads(out)["data"]
        assert data["run_id"] == RUN_ID and data["task_run_id"] == 1000
        assert data["task_key"] == "ingest"
        assert data["state"]["result_state"] == "FAILED"
        assert data["logs_truncated"] is True

    def test_scrubbed_and_redacted(self, sdk, capsys):
        sdk.jobs.get_run.return_value = _run("ingest")
        sdk.jobs.get_run_output.return_value = _output()
        code, out = run_main(["job", "run-output", "--run-id", str(RUN_ID)], capsys)
        assert code == 0
        data = json.loads(out)["data"]
        assert data["error"] == "Failed for <email>"
        assert data["error_trace"].endswith("owner=<email>")
        assert data["logs"].endswith("contact <email>\n")
        assert data["notebook_output"] == {
            "result": "done by <email>",
            "truncated": False,
        }
        assert _identity_keys(data) == [] and "@" not in out

    def test_multi_task_run_selects_by_key(self, sdk, capsys):
        sdk.jobs.get_run.return_value = _run("ingest", "transform")
        sdk.jobs.get_run_output.return_value = _output()
        code, out = run_main(
            ["job", "run-output", "--run-id", str(RUN_ID), "--task-key", "transform"],
            capsys,
        )
        assert code == 0, out
        sdk.jobs.get_run_output.assert_called_once_with(1001)
        assert json.loads(out)["data"]["task_key"] == "transform"

    def test_multi_task_run_without_key_lists_keys(self, sdk, capsys):
        sdk.jobs.get_run.return_value = _run("ingest", "transform")
        code, out = run_main(["job", "run-output", "--run-id", str(RUN_ID)], capsys)
        assert code == 4
        err = json.loads(out)["error"]
        assert "--task-key" in err and "ingest" in err and "transform" in err
        sdk.jobs.get_run_output.assert_not_called()

    def test_unknown_task_key_is_not_found(self, sdk, capsys):
        sdk.jobs.get_run.return_value = _run("ingest", "transform")
        code, out = run_main(
            ["job", "run-output", "--run-id", str(RUN_ID), "--task-key", "nope"], capsys
        )
        assert code == 2
        assert "nope" in json.loads(out)["error"]
        sdk.jobs.get_run_output.assert_not_called()

    def test_repaired_task_uses_latest_attempt(self, sdk, capsys):
        run = _run("ingest")
        run.tasks.append(RunTask(task_key="ingest", run_id=2000, attempt_number=1))
        sdk.jobs.get_run.return_value = run
        sdk.jobs.get_run_output.return_value = _output()
        code, _ = run_main(["job", "run-output", "--run-id", str(RUN_ID)], capsys)
        assert code == 0
        sdk.jobs.get_run_output.assert_called_once_with(2000)

    def test_taskless_run_reads_its_own_output(self, sdk, capsys):
        sdk.jobs.get_run.return_value = Run(run_id=RUN_ID, state=FAILED)
        sdk.jobs.get_run_output.return_value = _output()
        code, _ = run_main(["job", "run-output", "--run-id", str(RUN_ID)], capsys)
        assert code == 0
        sdk.jobs.get_run_output.assert_called_once_with(RUN_ID)

    def test_max_bytes_truncates_and_flags(self, sdk, capsys):
        sdk.jobs.get_run.return_value = _run("ingest")
        sdk.jobs.get_run_output.return_value = _output(
            logs="x" * 5000 + "TAIL",
            logs_truncated=False,
            notebook_output=NotebookOutput(result="HEAD" + "y" * 5000),
        )
        code, out = run_main(
            ["job", "run-output", "--run-id", str(RUN_ID), "--max-bytes", "100"], capsys
        )
        assert code == 0
        data = json.loads(out)["data"]
        assert len(data["logs"].encode()) == 100 and data["logs"].endswith("TAIL")
        assert data["logs_truncated"] is False  # the SDK flag is kept as-is
        assert data["notebook_output"]["result"].startswith("HEAD")
        assert len(data["notebook_output"]["result"].encode()) == 100
        assert data["truncated"]["logs"] is True
        assert data["truncated"]["notebook_result"] is True
        assert data["truncated"]["error_trace"] is False

    def test_default_cap_is_64_kib(self, sdk, capsys):
        sdk.jobs.get_run.return_value = _run("ingest")
        sdk.jobs.get_run_output.return_value = _output(logs="z" * 200_000)
        code, out = run_main(["job", "run-output", "--run-id", str(RUN_ID)], capsys)
        assert code == 0
        assert len(json.loads(out)["data"]["logs"]) == 64 * 1024

    @pytest.mark.parametrize("bad", ["0", "-1", str(8 * 2**20)])
    def test_bad_max_bytes_is_arg_error(self, sdk, capsys, bad):
        code, _ = run_main(
            ["job", "run-output", "--run-id", str(RUN_ID), "--max-bytes", bad], capsys
        )
        assert code == 4
        sdk.jobs.get_run.assert_not_called()

    def test_missing_run_is_not_found(self, sdk, capsys):
        sdk.jobs.get_run.side_effect = RuntimeError("Run 900 does not exist: not found")
        code, _ = run_main(["job", "run-output", "--run-id", str(RUN_ID)], capsys)
        assert code == 2

    def test_run_folder_writes_through_the_sink(
        self, covered_env, drive_run, sdk, capsys
    ):
        sdk.jobs.get_run.return_value = _run("ingest")
        sdk.jobs.get_run_output.return_value = _output()
        before = covered_env.snapshot()
        code, out = run_main(
            [
                "job",
                "run-output",
                "--run-id",
                str(RUN_ID),
                "--run-folder",
                drive_run.folder_id,
                "--out",
                "raw/run-output.json",
            ],
            capsys,
        )
        assert code == 0, out
        covered_ok(covered_env, before, out)
        stored = drive_files(drive_run)["raw/run-output.json"]
        assert b"@" not in stored and json.loads(stored)["data"]["task_run_id"] == 1000


def _job(*tasks: Task, git: bool = False) -> Job:
    return Job(
        job_id=42,
        creator_user_name="alice@corp.com",
        settings=JobSettings(
            name="etl",
            tasks=list(tasks),
            git_source=GitSource(
                git_url="https://example.com/r.git", git_provider="gitHub"
            )
            if git
            else None,
        ),
    )


def _export(text: str) -> ExportResponse:
    return ExportResponse(
        content=base64.b64encode(text.encode()).decode(), file_type="py"
    )


NB = Task(
    task_key="nb", notebook_task=NotebookTask(notebook_path="/Users/alice@corp.com/etl")
)
PY = Task(
    task_key="py",
    spark_python_task=SparkPythonTask(python_file="/Workspace/etl/main.py"),
)


@pytest.mark.unit
class TestJobCode:
    def test_notebook_task_exports_source(self, sdk, capsys):
        sdk.jobs.get.return_value = _job(NB)
        sdk.workspace.export.return_value = _export(
            "# owner: alice@corp.com\nprint(1)\n"
        )
        code, out = run_main(["job", "code", "--job-id", "42"], capsys)
        assert code == 0, out
        sdk.jobs.get.assert_called_once_with(42)
        sdk.workspace.export.assert_called_once_with(
            "/Users/alice@corp.com/etl", format=ExportFormat.SOURCE
        )
        data = json.loads(out)["data"]
        assert data["task_key"] == "nb" and data["kind"] == "notebook"
        assert data["path"] == "/Users/<email>/etl"
        assert data["code"] == "# owner: <email>\nprint(1)\n"
        assert data["truncated"] is False
        assert "@" not in out and _identity_keys(data) == []

    def test_python_file_task_exports_source(self, sdk, capsys):
        sdk.jobs.get.return_value = _job(PY)
        sdk.workspace.export.return_value = _export("import sys\n")
        code, out = run_main(["job", "code", "--job-id", "42"], capsys)
        assert code == 0, out
        sdk.workspace.export.assert_called_once_with(
            "/Workspace/etl/main.py", format=ExportFormat.SOURCE
        )
        assert json.loads(out)["data"]["kind"] == "python_file"

    def test_multi_task_job_needs_task_key(self, sdk, capsys):
        sdk.jobs.get.return_value = _job(NB, PY)
        code, out = run_main(["job", "code", "--job-id", "42"], capsys)
        assert code == 4
        err = json.loads(out)["error"]
        assert "--task-key" in err and "nb" in err and "py" in err
        sdk.workspace.export.assert_not_called()

    def test_multi_task_job_with_key(self, sdk, capsys):
        sdk.jobs.get.return_value = _job(NB, PY)
        sdk.workspace.export.return_value = _export("x = 1\n")
        code, out = run_main(
            ["job", "code", "--job-id", "42", "--task-key", "py"], capsys
        )
        assert code == 0, out
        assert json.loads(out)["data"]["task_key"] == "py"

    def test_unknown_task_key_is_not_found(self, sdk, capsys):
        sdk.jobs.get.return_value = _job(NB, PY)
        code, _ = run_main(
            ["job", "code", "--job-id", "42", "--task-key", "zz"], capsys
        )
        assert code == 2

    @pytest.mark.parametrize(
        "job",
        [
            _job(NB, git=True),  # source unset + git_source → GIT
            _job(
                Task(
                    task_key="nb",
                    notebook_task=NotebookTask(
                        notebook_path="etl/nb", source=Source.GIT
                    ),
                )
            ),
            _job(
                Task(
                    task_key="py",
                    spark_python_task=SparkPythonTask(python_file="dbfs:/code/main.py"),
                )
            ),
            _job(
                Task(
                    task_key="sql",
                    sql_task=SqlTask(warehouse_id="w", file=SqlTaskFile(path="q.sql")),
                )
            ),
        ],
        ids=[
            "git_source_default",
            "git_explicit",
            "remote_python_file",
            "unsupported_kind",
        ],
    )
    def test_non_workspace_code_is_a_gap(self, sdk, capsys, job):
        sdk.jobs.get.return_value = job
        code, out = run_main(["job", "code", "--job-id", "42"], capsys)
        assert code == 2
        assert json.loads(out)["error"].startswith("code_not_in_workspace:")
        sdk.workspace.export.assert_not_called()

    def test_max_bytes_honoured(self, sdk, capsys):
        sdk.jobs.get.return_value = _job(PY)
        sdk.workspace.export.return_value = _export("HEAD" + "a" * 10_000)
        code, out = run_main(
            ["job", "code", "--job-id", "42", "--max-bytes", "64"], capsys
        )
        assert code == 0
        data = json.loads(out)["data"]
        assert data["code"].startswith("HEAD") and len(data["code"].encode()) == 64
        assert data["truncated"] is True and data["bytes"] == 10_004
