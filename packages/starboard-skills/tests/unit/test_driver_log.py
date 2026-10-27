"""``diagnostic driver-log`` against an autospec SDK client (spec §F, D3-24)."""

from __future__ import annotations

import base64
import io
import json
import typing
from unittest.mock import create_autospec

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import ApiClient
from databricks.sdk.service.compute import (
    ClusterDetails,
    ClusterLogConf,
    DbfsStorageInfo,
    S3StorageInfo,
    VolumesStorageInfo,
)
from databricks.sdk.service.files import (
    DownloadResponse,
    FileInfo,
    GetMetadataResponse,
    ReadResponse,
)

from .conftest import covered_ok, drive_files, run_main

CID = "0101-abc"


def autospec_client(*apis: str):
    """An autospec ``WorkspaceClient`` whose named sub-APIs are autospecced too."""
    w = create_autospec(WorkspaceClient, instance=True)
    for name in apis:
        api_type = typing.get_type_hints(getattr(WorkspaceClient, name).fget)["return"]
        setattr(w, name, create_autospec(api_type, instance=True))
    return w


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch):
    w = autospec_client("clusters", "files", "dbfs")
    w.api_client = create_autospec(ApiClient, instance=True)
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def _cluster(conf: ClusterLogConf | None) -> ClusterDetails:
    return ClusterDetails(
        cluster_id=CID, cluster_log_conf=conf, creator_user_name="alice@corp.com"
    )


VOL = ClusterLogConf(volumes=VolumesStorageInfo(destination="/Volumes/main/ops/logs/"))
DBFS = ClusterLogConf(dbfs=DbfsStorageInfo(destination="dbfs:/cluster-logs"))
LOG = b"INFO start\n" * 50 + b"ERROR user=erin@corp.com OOM\n"


def _volumes_file(sdk, blob: bytes, *, size: int | None = -1) -> None:
    """Serve ``blob`` from Volumes: metadata, a plain download and a Range GET."""
    sdk.files.get_metadata.return_value = GetMetadataResponse(
        content_length=len(blob) if size == -1 else size
    )
    sdk.files.download.side_effect = lambda _p: DownloadResponse(
        contents=io.BytesIO(blob)
    )

    def ranged(method, path, *, headers, response_headers, raw):
        start = int(headers["Range"].removeprefix("bytes=").removesuffix("-"))
        return {
            "content-range": f"bytes {start}-{len(blob) - 1}/{len(blob)}",
            "contents": io.BytesIO(blob[start:]),
        }

    sdk.api_client.do.side_effect = ranged


def _dbfs_read(blob: bytes):
    def read(path, *, length=None, offset=None):
        chunk = blob[offset : offset + length]
        return ReadResponse(
            bytes_read=len(chunk), data=base64.b64encode(chunk).decode()
        )

    return read


@pytest.mark.unit
class TestDriverLog:
    def test_volumes_destination_uses_files_download(self, sdk, capsys):
        sdk.clusters.get.return_value = _cluster(VOL)
        _volumes_file(sdk, LOG)
        code, out = run_main(["diagnostic", "driver-log", "--cluster-id", CID], capsys)
        assert code == 0, out
        sdk.clusters.get.assert_called_once_with(CID)
        sdk.api_client.do.assert_not_called()  # the whole file fits the tail
        sdk.files.download.assert_called_once_with(
            f"/Volumes/main/ops/logs/{CID}/driver/stdout"
        )
        sdk.dbfs.read.assert_not_called()
        data = json.loads(out)["data"]
        assert data["destination_kind"] == "volumes" and data["stream"] == "stdout"
        assert data["path"] == f"/Volumes/main/ops/logs/{CID}/driver/stdout"
        assert data["content"].endswith("ERROR user=<email> OOM\n")
        assert data["truncated"] is False and data["bytes"] == len(LOG)
        assert "@" not in out and "creator_user_name" not in out

    def test_dbfs_destination_uses_dbfs_read(self, sdk, capsys):
        sdk.clusters.get.return_value = _cluster(DBFS)
        path = f"dbfs:/cluster-logs/{CID}/driver/log4j-active.log"
        sdk.dbfs.get_status.return_value = FileInfo(path=path, file_size=len(LOG))
        sdk.dbfs.read.side_effect = _dbfs_read(LOG)
        code, out = run_main(
            ["diagnostic", "driver-log", "--cluster-id", CID, "--stream", "log4j"],
            capsys,
        )
        assert code == 0, out
        sdk.dbfs.get_status.assert_called_once_with(path)
        assert sdk.dbfs.read.call_args.args == (path,)
        sdk.files.download.assert_not_called()
        data = json.loads(out)["data"]
        assert data["destination_kind"] == "dbfs" and data["stream"] == "log4j"
        assert data["content"].endswith("ERROR user=<email> OOM\n")

    def test_dbfs_tail_is_bounded_and_read_from_the_end(self, sdk, capsys):
        sdk.clusters.get.return_value = _cluster(DBFS)
        blob = b"a" * 3_000_000 + b"THE END"
        sdk.dbfs.get_status.return_value = FileInfo(file_size=len(blob))
        sdk.dbfs.read.side_effect = _dbfs_read(blob)
        code, out = run_main(
            [
                "diagnostic",
                "driver-log",
                "--cluster-id",
                CID,
                "--stream",
                "stderr",
                "--tail-bytes",
                "1000",
            ],
            capsys,
        )
        assert code == 0, out
        offsets = [c.kwargs["offset"] for c in sdk.dbfs.read.call_args_list]
        assert offsets[0] == len(blob) - 1000
        data = json.loads(out)["data"]
        assert len(data["content"]) == 1000 and data["content"].endswith("THE END")
        assert data["truncated"] is True and data["bytes"] == len(blob)

    def test_volumes_tail_is_range_read(self, sdk, capsys):
        sdk.clusters.get.return_value = _cluster(VOL)
        blob = b"b" * 2_500_000 + b"LAST LINE\n"
        _volumes_file(sdk, blob)
        code, out = run_main(
            ["diagnostic", "driver-log", "--cluster-id", CID, "--tail-bytes", "500"],
            capsys,
        )
        assert code == 0
        sdk.files.download.assert_not_called()
        call = sdk.api_client.do.call_args
        assert call.args == (
            "GET",
            f"/api/2.0/fs/files/Volumes/main/ops/logs/{CID}/driver/stdout",
        )
        assert call.kwargs["headers"]["Range"] == f"bytes={len(blob) - 500}-"
        data = json.loads(out)["data"]
        assert len(data["content"]) == 500 and data["content"].endswith("LAST LINE\n")
        assert data["truncated"] is True and data["bytes"] == len(blob)

    def test_volumes_range_not_honoured_reads_at_most_the_cap(
        self, sdk, capsys, monkeypatch
    ):
        from starboard_skills.helpers import diagnostic

        monkeypatch.setattr(diagnostic, "_VOLUMES_SCAN_CAP", 10_000)
        sdk.clusters.get.return_value = _cluster(VOL)
        blob = io.BytesIO(b"x" * 9_000 + b"END" + b"y" * 50_000)
        sdk.files.get_metadata.return_value = GetMetadataResponse(content_length=59_003)
        sdk.api_client.do.return_value = {"content-range": None, "contents": blob}
        code, out = run_main(
            ["diagnostic", "driver-log", "--cluster-id", CID, "--tail-bytes", "1000"],
            capsys,
        )
        assert code == 0, out
        assert blob.closed
        data = json.loads(out)["data"]
        # Stopped at the 10 000-byte cap: the kept tail is bytes 9 000..10 000.
        assert data["content"] == "END" + "y" * 997 and data["truncated"] is True
        assert data["bytes"] == 59_003

    def test_volumes_without_length_streams_at_most_the_cap(
        self, sdk, capsys, monkeypatch
    ):
        from starboard_skills.helpers import diagnostic

        monkeypatch.setattr(diagnostic, "_VOLUMES_SCAN_CAP", 4_000)
        sdk.clusters.get.return_value = _cluster(VOL)
        stream = io.BytesIO(b"z" * 20_000)
        sdk.files.get_metadata.return_value = GetMetadataResponse(content_length=None)
        sdk.files.download.return_value = DownloadResponse(contents=stream)
        code, out = run_main(
            ["diagnostic", "driver-log", "--cluster-id", CID, "--tail-bytes", "500"],
            capsys,
        )
        assert code == 0, out
        sdk.api_client.do.assert_not_called()
        assert stream.closed
        data = json.loads(out)["data"]
        assert len(data["content"]) == 500 and data["bytes"] == 4_000

    def test_log_path_uses_the_api_cluster_id(self, sdk, capsys):
        """The path segment is the ID ``clusters.get`` returned, not the argument."""
        sdk.clusters.get.return_value = _cluster(VOL)  # cluster_id == CID
        _volumes_file(sdk, LOG)
        code, out = run_main(
            ["diagnostic", "driver-log", "--cluster-id", "../../other"], capsys
        )
        assert code == 0, out
        sdk.clusters.get.assert_called_once_with("../../other")
        path = f"/Volumes/main/ops/logs/{CID}/driver/stdout"
        sdk.files.get_metadata.assert_called_once_with(path)
        data = json.loads(out)["data"]
        assert data["path"] == path and data["cluster_id"] == CID

    def test_cluster_without_id_is_an_api_error(self, sdk, capsys):
        sdk.clusters.get.return_value = ClusterDetails(cluster_log_conf=VOL)
        code, _ = run_main(["diagnostic", "driver-log", "--cluster-id", CID], capsys)
        assert code == 3
        sdk.files.get_metadata.assert_not_called()

    def test_default_tail_is_64_kib(self, sdk, capsys):
        sdk.clusters.get.return_value = _cluster(VOL)
        _volumes_file(sdk, b"c" * 100_000)
        code, out = run_main(["diagnostic", "driver-log", "--cluster-id", CID], capsys)
        assert code == 0
        assert len(json.loads(out)["data"]["content"]) == 64 * 1024

    def test_no_log_conf_is_a_gap(self, sdk, capsys):
        sdk.clusters.get.return_value = _cluster(None)
        code, out = run_main(["diagnostic", "driver-log", "--cluster-id", CID], capsys)
        assert code == 2
        assert json.loads(out)["error"].startswith("cluster_log_delivery_off:")
        sdk.files.download.assert_not_called()
        sdk.dbfs.read.assert_not_called()

    def test_s3_destination_is_a_gap(self, sdk, capsys):
        sdk.clusters.get.return_value = _cluster(
            ClusterLogConf(s3=S3StorageInfo(destination="s3://bucket/logs"))
        )
        code, out = run_main(["diagnostic", "driver-log", "--cluster-id", CID], capsys)
        assert code == 2
        assert json.loads(out)["error"].startswith(
            "cluster_log_destination_unsupported:"
        )

    def test_missing_log_file_is_not_found(self, sdk, capsys):
        sdk.clusters.get.return_value = _cluster(VOL)
        sdk.files.get_metadata.side_effect = RuntimeError("File not found")
        code, _ = run_main(["diagnostic", "driver-log", "--cluster-id", CID], capsys)
        assert code == 2

    def test_bad_stream_and_tail_are_arg_errors(self, sdk, capsys):
        code, _ = run_main(
            ["diagnostic", "driver-log", "--cluster-id", CID, "--stream", "gc"], capsys
        )
        assert code == 4
        code, _ = run_main(
            ["diagnostic", "driver-log", "--cluster-id", CID, "--tail-bytes", "0"],
            capsys,
        )
        assert code == 4
        sdk.clusters.get.assert_not_called()

    def test_run_folder_writes_through_the_sink(
        self, covered_env, drive_run, sdk, capsys
    ):
        sdk.clusters.get.return_value = _cluster(VOL)
        _volumes_file(sdk, LOG)
        before = covered_env.snapshot()
        code, out = run_main(
            [
                "diagnostic",
                "driver-log",
                "--cluster-id",
                CID,
                "--run-folder",
                drive_run.folder_id,
                "--out",
                "raw/driver-stdout.json",
            ],
            capsys,
        )
        assert code == 0, out
        covered_ok(covered_env, before, out)
        assert b"@" not in drive_files(drive_run)["raw/driver-stdout.json"]
