# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.sparklog`` — Spark event-log parsing CLI (Phase-2 D4).

Thin ``argparse`` wrapper over ``create_spark_application``. Every invocation
emits the stable JSON envelope (:mod:`starboard_x.contract`) and uses the Phase-0
exit-code contract (``0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error``).

Verbs:
    parse --source {dbfs|s3|https|local} --path <path> [--full]

``local`` and ``https`` parsing run on the base install (``httpx`` is a
``starboard-core`` dependency). ``s3`` requires ``boto3`` (``[sparklog-aws]``)
and ``dbfs`` requires ``databricks-sdk`` (``[databricks]``); when the extra is
absent the verb exits ``1`` (auth) with an actionable ``pip install`` hint rather
than a stray import error.
"""

from __future__ import annotations

import argparse
import importlib.util
from typing import Any

from starboard_x import _cli
from starboard_x.contract import ArgError, AuthError, NotFoundError, to_jsonable

_DOMAIN = "sparklog"

# source -> (required module, install hint). None = no extra needed.
_SOURCE_REQUIREMENTS: dict[str, tuple[str, str] | None] = {
    "local": None,
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
    if source == "local" and scheme not in ("", "file"):
        raise ArgError(f"--source local expects a filesystem path (got '{scheme}://')")


def _metadata_summary(app: Any) -> Any:
    """Serialize application metadata defensively (dict / dataclass / pydantic)."""
    md = getattr(app, "metadata", None)
    if md is None:
        return {}
    if hasattr(md, "model_dump"):
        return md.model_dump()
    return to_jsonable(md)


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


def _cmd_parse(args: argparse.Namespace) -> dict[str, Any]:
    _check_source_available(args.source)
    _validate_path_scheme(args.source, args.path)

    # Lazy import: keeps the arg-error / gating paths free of polars/orjson and
    # makes the "cloud SDK only on demand" seam explicit.
    from starboard_core.log_parser import create_spark_application

    app = create_spark_application(path=args.path)
    if app is None:
        raise NotFoundError(f"no Spark event logs found at path: {args.path}")

    if args.full:
        return {"source": args.source, "path": args.path, "application": app.to_dict()}

    return {
        "source": args.source,
        "path": args.path,
        "metadata": _metadata_summary(app),
        "counts": {
            "jobs": _frame_height(app, "jobData"),
            "stages": _frame_height(app, "stageData"),
            "tasks": _frame_height(app, "taskData"),
            "sql": _frame_height(app, "sqlData"),
            "executors": _frame_height(app, "executorData"),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.sparklog",
        description="Parse Spark event logs from local/HTTP/S3/DBFS sources.",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_parse = subparsers.add_parser("parse", help="Parse a Spark event log.")
    p_parse.add_argument(
        "--source", required=True, choices=["dbfs", "s3", "https", "local"]
    )
    p_parse.add_argument("--path", required=True, help="Path/URI to the event log.")
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
