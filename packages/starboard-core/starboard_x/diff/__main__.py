# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.diff`` — deterministic JSON diffs (D3-24).

Every invocation emits the stable JSON envelope (:mod:`starboard_x.contract`) and
uses the exit-code contract (``0 ok · 1 auth · 2 refused · 3 api-error ·
4 arg-error · 7 storage``).

Verbs:
    settings --a REF --b REF [--run-folder ID]
    metrics  --a REF --b REF [--run-folder ID]

``settings`` lists the leaf JSON paths added, removed and changed from ``--a`` to
``--b``. ``metrics`` lists every numeric value at an object path (not inside a
list, not a boolean) with ``delta = b - a`` and a ``unit`` inferred from the key
(``pp`` for a percentage; omitted when unknown). A document that is a
``starboard_x`` envelope is diffed by its ``data``. Output is sorted by path.

REF is ``drive:<object id>`` or a local file (refused on an overlay install, exit 2).
With ``--run-folder ID`` a REF is a run-relative path (or ``drive:<object id>``)
read through the run's sink; on a covered run a local path is refused
(``LOCAL_STORAGE_REFUSED``, exit 2). The verbs are read-only: nothing is written.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator
from typing import Any

from starboard_core.engagement.enforce import covered, writer_context
from starboard_core.engagement.overlay import detect_overlay
from starboard_core.engagement.reads import ReadRefusedError, read_verified, run_relpath
from starboard_core.engagement.sink import ArtifactSink, load_engagement_storage
from starboard_core.ports.engagement_storage import (
    EngagementStoragePort,
    StorageNotFoundError,
)

from starboard_x import _cli
from starboard_x.contract import ArgError
from starboard_x.discovery._authorization import bounded_stdout, storage_refusals

_DOMAIN = "diff"
_DRIVE = _cli.DRIVE_REF_PREFIX
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

#: Units ``metrics`` infers from a key's last segment (else the unit is omitted).
UNITS: tuple[str, ...] = ("pp", "ms", "s", "bytes", "count", "DBU")
_CAMEL_MS = re.compile(r"[a-z0-9]Ms\Z")


def _unit(key: str) -> str | None:
    """The unit of a metric whose last path segment is ``key`` (``None``: unknown)."""
    low = key.lower()
    if "pct" in low or "percent" in low:
        return "pp"
    if low == "ms" or low.endswith("_ms") or _CAMEL_MS.search(key):
        return "ms"
    if low.endswith(("_sec", "_secs", "_seconds")):
        return "s"
    if "bytes" in low:
        return "bytes"
    if low.endswith("count") or low.startswith("num_"):
        return "count"
    if "dbu" in low:
        return "DBU"
    return None


def _step(key: str) -> str:
    return f".{key}" if _IDENT.match(key) else f"[{json.dumps(key)}]"


def _leaves(doc: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    """``(json path, value)`` of every leaf; an empty object or list is a leaf."""
    if isinstance(doc, dict) and doc:
        for key in sorted(doc, key=str):
            yield from _leaves(doc[key], path + _step(str(key)))
    elif isinstance(doc, list) and doc:
        for index, item in enumerate(doc):
            yield from _leaves(item, f"{path}[{index}]")
    else:
        yield path, doc


def _numbers(doc: Any, path: str = "$") -> Iterator[tuple[str, str, int | float]]:
    """``(json path, last key, value)`` of every numeric value at an object path."""
    if not isinstance(doc, dict):
        return
    for key in sorted(doc, key=str):
        value, sub = doc[key], path + _step(str(key))
        if isinstance(value, dict):
            yield from _numbers(value, sub)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            yield sub, str(key), value


def _unwrap(doc: Any) -> Any:
    """A ``starboard_x`` envelope is diffed by its ``data``."""
    if isinstance(doc, dict) and {"ok", "domain", "data"} <= set(doc):
        return doc["data"]
    return doc


def _diff_settings(a: Any, b: Any) -> dict[str, Any]:
    left, right = dict(_leaves(a)), dict(_leaves(b))
    added = [{"path": p, "b": right[p]} for p in sorted(right.keys() - left.keys())]
    removed = [{"path": p, "a": left[p]} for p in sorted(left.keys() - right.keys())]
    common = sorted(left.keys() & right.keys())
    changed = [
        {"path": p, "a": left[p], "b": right[p]}
        for p in common
        if _canonical(left[p]) != _canonical(right[p])
    ]
    return {
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "unchanged": len(common) - len(changed),
        },
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _canonical(value: Any) -> str:
    """Type-aware equality: ``1`` and ``1.0`` and ``true`` stay distinct."""
    return json.dumps([type(value).__name__, value], sort_keys=True)


def _delta(a: int | float, b: int | float) -> int | float:
    """``b - a``; a float delta is rounded to 9 places (no binary-float noise)."""
    delta = b - a
    return round(delta, 9) if isinstance(delta, float) else delta


def _diff_metrics(a: Any, b: Any) -> dict[str, Any]:
    left = {p: (k, v) for p, k, v in _numbers(a)}
    right = {p: (k, v) for p, k, v in _numbers(b)}
    rows: list[dict[str, Any]] = []
    for path in sorted(left.keys() | right.keys()):
        key = (left.get(path) or right[path])[0]
        va = left[path][1] if path in left else None
        vb = right[path][1] if path in right else None
        row: dict[str, Any] = {
            "key": path,
            "a": va,
            "b": vb,
            "delta": None if va is None or vb is None else _delta(va, vb),
        }
        unit = _unit(key)
        if unit is not None:
            row["unit"] = unit
        rows.append(row)
    return {
        "counts": {
            "keys": len(rows),
            "changed": sum(
                1 for r in rows if r["delta"] is not None and r["a"] != r["b"]
            ),
            "only_a": len(left.keys() - right.keys()),
            "only_b": len(right.keys() - left.keys()),
        },
        "metrics": rows,
    }


def _parse_json(data: bytes, flag: str, value: str) -> Any:
    try:
        return json.loads(data)
    except ValueError as exc:
        raise ArgError(f"{flag} is not valid JSON ({value}): {exc}") from exc


def _read_from_run(
    sink: ArtifactSink,
    storage: EngagementStoragePort,
    flag: str,
    value: str,
    *,
    covered_run: bool,
) -> Any:
    """A REF with ``--run-folder``: a run-relative path or ``drive:<object id>``."""
    limit = _cli.MAX_INTAKE_BYTES
    if value.startswith(_DRIVE):
        try:
            data = read_verified(storage, value[len(_DRIVE) :], max_bytes=limit)
        except StorageNotFoundError as exc:
            raise ArgError(f"{flag}: {value} not found: {exc}") from exc
        except ReadRefusedError as exc:
            raise ArgError(f"{flag}: {exc}") from exc
    else:
        rel = run_relpath(flag, value, covered_run=covered_run, arg_error=ArgError)
        try:
            data = sink.get_bytes(rel, max_bytes=limit)
        except StorageNotFoundError as exc:
            raise ArgError(f"{flag}: {rel} is not in the run folder") from exc
        except ReadRefusedError as exc:
            raise ArgError(f"{flag}: {exc}") from exc
    return _parse_json(data, flag, value)


def _diff(args: argparse.Namespace, differ: Any) -> dict[str, Any]:
    if not args.run_folder:
        docs = [
            _cli.read_json_file(value, flag=flag)
            for flag, value in (("--a", args.a), ("--b", args.b))
        ]
        data = {"a": args.a, "b": args.b, **differ(*map(_unwrap, docs))}
        return bounded_stdout(data) if detect_overlay().enabled else data

    cache: list[EngagementStoragePort] = []

    def storage_factory() -> EngagementStoragePort:
        if not cache:
            cache.append(load_engagement_storage())
        return cache[0]

    with (
        storage_refusals(),
        writer_context(
            run_folder_id=args.run_folder,
            local_root=None,
            acquires_customer_data=False,
            storage_factory=storage_factory,
            overlay=detect_overlay(),
        ) as ctx,
    ):
        is_covered = covered(ctx.decision)
        docs = [
            _read_from_run(
                ctx.sink, storage_factory(), flag, value, covered_run=is_covered
            )
            for flag, value in (("--a", args.a), ("--b", args.b))
        ]
        data = {
            "a": args.a,
            "b": args.b,
            "run_folder_id": args.run_folder,
            **differ(*map(_unwrap, docs)),
        }
        ctx.raise_if_refused()
    return bounded_stdout(data) if is_covered else data


def _cmd_settings(args: argparse.Namespace) -> dict[str, Any]:
    return _diff(args, _diff_settings)


def _cmd_metrics(args: argparse.Namespace) -> dict[str, Any]:
    return _diff(args, _diff_metrics)


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.diff",
        description="Deterministic diffs of two JSON documents (settings, metrics).",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, func, help_text in (
        ("settings", _cmd_settings, "JSON-path adds, removes and changes."),
        ("metrics", _cmd_metrics, "Per-key numeric delta and unit."),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--a", required=True, help="Baseline: drive:<id> or FILE.")
        sub.add_argument("--b", required=True, help="Compared: drive:<id> or FILE.")
        sub.add_argument(
            "--run-folder",
            default=None,
            help="Drive run folder id: REFs are run-relative paths (or drive:<id>).",
        )
        sub.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
