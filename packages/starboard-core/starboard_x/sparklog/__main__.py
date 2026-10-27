# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.sparklog`` — Spark event-log parsing CLI.

Thin ``argparse`` wrapper over the kernel's log-parser factories. Every invocation
emits the stable JSON envelope (:mod:`starboard_x.contract`) and uses the exit-code
contract (``0 ok · 1 auth · 2 not-found/refused · 3 api-error · 4 arg-error ·
7 storage``).

Verbs:
    parse --input drive:<id>|FILE [--full]
    parse --source {dbfs|s3|https} --path <path> [--full]

``--input`` is the customer-file intake (W30): ``drive:<object id>`` is read from
the engagement storage in memory; a local FILE is read on a public install and
refused on an overlay install (exit 2). A gzip-compressed input is decompressed.
``--input`` and ``https`` parsing run on the base install (``httpx`` is a
``starboard-core`` dependency). ``s3`` requires ``boto3`` (``[sparklog-aws]``)
and ``dbfs`` requires ``databricks-sdk`` (``[databricks]``); when the extra is
absent the verb exits ``1`` (auth) with an actionable ``pip install`` hint rather
than a stray import error.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import zlib
from pathlib import Path
from typing import Any

from starboard_x import _cli
from starboard_x.contract import (
    ArgError,
    AuthError,
    NotFoundError,
    scrub_identity,
    to_jsonable,
)

_DOMAIN = "sparklog"

# source -> (required module, install hint). None = no extra needed.
_SOURCE_REQUIREMENTS: dict[str, tuple[str, str] | None] = {
    "https": None,
    "s3": ("boto3", 'pip install "starboard-x[sparklog-aws]"'),
    "dbfs": ("databricks.sdk", 'pip install "starboard-core[databricks]"'),
}

# source -> expected URL scheme(s) for a light path/source consistency check.
_SOURCE_SCHEMES: dict[str, tuple[str, ...]] = {
    "s3": ("s3",),
    "https": ("http", "https"),
    "dbfs": ("dbfs",),
}


def _check_source_available(source: str) -> None:
    """Raise :class:`AuthError` (exit 1) when the source's extra is missing."""
    requirement = _SOURCE_REQUIREMENTS.get(source)
    if requirement is None:
        return
    module_name, hint = requirement
    if importlib.util.find_spec(module_name) is None:
        raise AuthError(
            f"the '{source}' source requires the '{module_name}' dependency "
            f"which is not installed. Install the extra: {hint}"
        )


def _validate_path_scheme(source: str, path: str) -> None:
    """Reject an obvious source/path mismatch (e.g. --source s3 with a local path)."""
    from urllib.parse import urlparse

    expected = _SOURCE_SCHEMES.get(source)
    scheme = urlparse(path).scheme
    if source == "dbfs":
        # DBFS accepts both dbfs: URIs and bare /Volumes/... paths.
        if scheme == "dbfs" or path.startswith("/Volumes/"):
            return
        raise ArgError("--source dbfs expects a 'dbfs:' URI or a '/Volumes/...' path")
    if expected is not None and scheme not in expected:
        raise ArgError(
            f"--source {source} expects a {expected[0]}:// path (got scheme "
            f"'{scheme or 'none'}')"
        )


# Emitted Spark properties (D3-24 allowlist): tuning and sizing configuration only.
# Dropped: identity-bearing Databricks usage tags (``clusterAllTags`` carries the
# Creator email, ``clusterName`` is often "<user>'s Cluster", ``clusterOwnerUserId``
# / ``clusterCreator``), ``spark.app.name``, host / address keys and the
# credential-bearing ``spark.hadoop.*`` / ``fs.*`` space. The parser's own checks
# (dynamic allocation, heterogeneous executors) read the full map before emission.
_SPARK_PARAM_PREFIXES = (
    "spark.sql.",
    "spark.dynamicAllocation.",
    "spark.memory.",
    "spark.shuffle.",
    "spark.speculation",
    "spark.databricks.delta.",
    "spark.databricks.io.cache.",
    "spark.databricks.photon.",
    "spark.databricks.adaptive.",
)
_SPARK_PARAM_KEYS = frozenset(
    {
        "spark.app.id",
        "spark.default.parallelism",
        "spark.serializer",
        "spark.task.cpus",
        "spark.executor.cores",
        "spark.executor.instances",
        "spark.executor.memory",
        "spark.executor.memoryOverhead",
        "spark.executor.memoryOverheadFactor",
        "spark.executor.pyspark.memory",
        "spark.driver.cores",
        "spark.driver.maxResultSize",
        "spark.driver.memory",
        "spark.driver.memoryOverhead",
    }
    | {
        f"spark.databricks.clusterUsageTags.{tag}"
        for tag in (
            "sparkVersion",
            "clusterId",
            "cloudProvider",
            "clusterNodeType",
            "driverNodeType",
            "clusterWorkers",
            "clusterMinWorkers",
            "clusterMaxWorkers",
            "clusterTargetWorkers",
            "clusterScalingType",
            "clusterSku",
            "runtimeEngine",
            "autoTerminationMinutes",
            "enableElasticDisk",
            "clusterAvailability",
            "clusterFirstOnDemand",
            "clusterSpotBidPricePercent",
        )
    }
)
#: Never emitted even under an allowed prefix (credentials, identities).
_SPARK_PARAM_DENY = re.compile(
    r"secret|password|passwd|token|credential|access[._-]?key|private[._-]?key"
    r"|owner|creator|email|(^|[._])user(name|_?id)?$",
    re.IGNORECASE,
)


def _allowed_spark_params(params: Any) -> dict[str, Any]:
    """``params`` restricted to the emitted allowlist."""
    if not isinstance(params, dict):
        return {}
    return {
        key: value
        for key, value in params.items()
        if isinstance(key, str)
        and (key in _SPARK_PARAM_KEYS or key.startswith(_SPARK_PARAM_PREFIXES))
        and not _SPARK_PARAM_DENY.search(key)
    }


def _metadata_summary(app: Any) -> Any:
    """Serialize application metadata defensively (dict / dataclass / pydantic).

    ``spark_params`` is cut to the emitted allowlist.
    """
    md = getattr(app, "metadata", None)
    if md is None:
        return {}
    out = md.model_dump() if hasattr(md, "model_dump") else to_jsonable(md)
    if isinstance(out, dict) and "spark_params" in out:
        out["spark_params"] = _allowed_spark_params(out["spark_params"])
    return out


def _frame_height(app: Any, attr: str) -> int:
    frame = getattr(app, attr, None)
    if frame is None:
        return 0
    height = getattr(frame, "height", None)
    if height is not None:
        return int(height)
    try:
        return len(frame)
    except TypeError:
        return 0


_GZIP_MAGIC = b"\x1f\x8b"


def _read_input_bytes(value: str) -> bytes:
    """Read ``--input`` (``drive:<id>`` or a local file) bounded by the intake cap.

    A local file larger than :data:`starboard_x._cli.MAX_INTAKE_BYTES` is refused
    (exit 4) before it is read; a local file on an overlay install is refused (exit 2).
    A gzip-compressed input is decompressed, bounded by the same cap.
    """
    data = _cli.read_intake_bytes(value, flag="--input")
    if data is None:
        path = Path(value)
        if not path.is_file():
            raise ArgError(f"--input file not found: {value}")
        try:
            if path.stat().st_size > _cli.MAX_INTAKE_BYTES:
                raise ArgError(
                    f"--input {value} is larger than {_cli.MAX_INTAKE_BYTES} bytes"
                )
            data = path.read_bytes()
        except OSError as exc:
            raise ArgError(f"could not read --input file {value}: {exc}") from exc
    if not data.startswith(_GZIP_MAGIC):
        return data
    inflater = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
    try:
        out = inflater.decompress(data, _cli.MAX_INTAKE_BYTES + 1)
    except zlib.error as exc:
        raise ArgError(f"--input {value} is not a valid gzip file: {exc}") from exc
    if len(out) > _cli.MAX_INTAKE_BYTES or inflater.unconsumed_tail:
        raise ArgError(
            f"--input {value} decompresses to more than {_cli.MAX_INTAKE_BYTES} bytes"
        )
    return out


def _summary(app: Any, full: bool) -> dict[str, Any]:
    if full:
        return {"application": app.to_dict()}
    return {
        "metadata": _metadata_summary(app),
        "counts": {
            "jobs": _frame_height(app, "jobData"),
            "stages": _frame_height(app, "stageData"),
            "tasks": _frame_height(app, "taskData"),
            "sql": _frame_height(app, "sqlData"),
            "executors": _frame_height(app, "executorData"),
        },
    }


def _cmd_parse_input(args: argparse.Namespace) -> dict[str, Any]:
    """``parse --input``: the in-memory content factory (read-only, writes nothing)."""
    content = _read_input_bytes(args.input)
    from starboard_core import log_parser

    try:
        app = log_parser.create_spark_application_from_content(content)
    except (ValueError, KeyError) as exc:
        raise ArgError(
            f"could not parse --input {args.input} as a Spark event log: {exc!r}"
        ) from exc
    data = scrub_identity({"input": args.input, **_summary(app, args.full)})
    if _cli.detect_overlay().enabled:
        from starboard_x.discovery._authorization import bounded_stdout

        return bounded_stdout(data)
    return data


def _cmd_parse(args: argparse.Namespace) -> dict[str, Any]:
    if args.input is not None:
        if args.path is not None:
            raise ArgError("--path is used with --source, not with --input")
        return _cmd_parse_input(args)
    if args.path is None:
        raise ArgError(f"--source {args.source} requires --path")
    _check_source_available(args.source)
    _validate_path_scheme(args.source, args.path)

    # Lazy import: keeps the arg-error / gating paths free of polars/orjson and
    # makes the "cloud SDK only on demand" seam explicit.
    from starboard_core.log_parser import create_spark_application

    app = create_spark_application(path=args.path)
    if app is None:
        raise NotFoundError(f"no Spark event logs found at path: {args.path}")

    return scrub_identity(
        {"source": args.source, "path": args.path, **_summary(app, args.full)}
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.sparklog",
        description="Parse Spark event logs from Drive, a file, HTTP, S3 or DBFS.",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_parse = subparsers.add_parser("parse", help="Parse a Spark event log.")
    where = p_parse.add_mutually_exclusive_group(required=True)
    where.add_argument(
        "--input",
        default=None,
        help="Event log: drive:<object id> or a local file (public install).",
    )
    where.add_argument("--source", choices=["dbfs", "s3", "https"], default=None)
    p_parse.add_argument(
        "--path", default=None, help="Path/URI to the event log (with --source)."
    )
    p_parse.add_argument(
        "--full",
        action="store_true",
        help="Emit the full parsed application instead of a summary.",
    )
    p_parse.set_defaults(func=_cmd_parse)

    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
