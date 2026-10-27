"""SparkApplication exporter: bytes variant vs file variant, and the write guard."""

from __future__ import annotations

import gzip

import polars as pl
import pytest
from starboard_core.log_parser.domain.models.application import SparkApplication
from starboard_core.log_parser.domain.models.metadata import (
    SparkApplicationInfo,
    SparkApplicationMetadata,
)

pytestmark = pytest.mark.unit


def _app() -> SparkApplication:
    info = SparkApplicationInfo(
        timestamp_start_ms=1700000000000,
        timestamp_end_ms=1700001000000,
        runtime_sec=1000.0,
        name="MyApp",
        id="app-123",
        spark_version="3.5.0",
        emr_version_tag="",
        cloud_platform="standalone",
        cloud_provider="on-prem",
        cluster_id="",
    )
    metadata = SparkApplicationMetadata(
        application_info=info,
        spark_params={"spark.executor.cores": 2},
        exists_sql=False,
        exists_executors=False,
    )
    return SparkApplication(
        metadata=metadata,
        job_data=pl.DataFrame({"job_id": [0, 1]}),
        stage_data=pl.DataFrame({"stage_id": [0, 1, 2]}),
        task_data=pl.DataFrame({"task_id": [0, 1, 2, 3]}),
        accum_data=pl.DataFrame({"accum_id": [0]}),
        sql_data=None,
        executor_data=None,
    )


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("include_spark_params", [False, True])
def test_to_json_bytes_equals_saved_file(tmp_path, compress, include_spark_params):
    app = _app()
    app.save(
        str(tmp_path / "app"),
        compress=compress,
        include_spark_params=include_spark_params,
    )

    data = app.to_json_bytes(
        compress=compress, include_spark_params=include_spark_params
    )

    suffix = ".json.gz" if compress else ".json"
    assert (tmp_path / f"app{suffix}").read_bytes() == data
    if compress:
        assert gzip.decompress(data) == app.to_json_bytes(
            include_spark_params=include_spark_params
        )


def test_save_refused_under_write_guard_but_bytes_allowed(tmp_path):
    from starboard_core.engagement import write_guard

    app = _app()
    with write_guard.guarded(write_guard.default_policy()):
        assert app.to_json_bytes()
        assert app.to_json_bytes(compress=True)
        for compress in (False, True):
            with pytest.raises(write_guard.LocalWriteRefused):
                app.save(str(tmp_path / "app"), compress=compress)
    assert not write_guard.active()
    assert list(tmp_path.iterdir()) == []
