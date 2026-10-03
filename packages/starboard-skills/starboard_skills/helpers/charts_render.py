"""Charts render helper — chart spec + data rows → rendered image (PNG/SVG).

The ``vl-convert-python`` render dep is imported lazily inside ``_vegalite_to_png``
and ``_vegalite_to_svg`` so the base install stays dep-free (import-linter contracts
remain KEPT).  Declare ``starboard-skills[render]`` to pull the heavy dep.

CLI:
    starboard-helper charts render --kind spend-by-product --data rows.json --out chart.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from starboard_skills.helpers.contract import ArgError, HelperError

# pip requirement string for the chart-render extra (vl-convert-python).
# Used by _bootstrap.ensure() for auto-install and surfaced in HelperError messages.
_RENDER_SPEC = (
    "starboard-skills[render]"
    " @ git+https://github.com/bluewatersql/starboard.git"
    "#subdirectory=packages/starboard-skills"
)

# ---------------------------------------------------------------------------
# Low-level render functions (lazy imports; monkeypatch target in tests)
# ---------------------------------------------------------------------------


def _vegalite_to_png(vl_dict: dict[str, Any]) -> bytes:
    """Convert a Vega-Lite spec dict to PNG bytes.

    Raises :class:`HelperError` if ``vl-convert-python`` is not installed and
    auto-install is disabled (``STARBOARD_NO_AUTO_INSTALL=1``).
    """
    from starboard_x._bootstrap import ensure  # lazy — stdlib-only bootstrap

    try:
        vlc = ensure("vl_convert", spec=_RENDER_SPEC, label="chart render")
    except RuntimeError as exc:
        raise HelperError(str(exc)) from exc
    return vlc.vegalite_to_png(json.dumps(vl_dict))  # type: ignore[no-any-return]


def _vegalite_to_svg(vl_dict: dict[str, Any]) -> bytes:
    """Convert a Vega-Lite spec dict to SVG bytes.

    Raises :class:`HelperError` if ``vl-convert-python`` is not installed and
    auto-install is disabled (``STARBOARD_NO_AUTO_INSTALL=1``).
    """
    from starboard_x._bootstrap import ensure  # lazy — stdlib-only bootstrap

    try:
        vlc = ensure("vl_convert", spec=_RENDER_SPEC, label="chart render")
    except RuntimeError as exc:
        raise HelperError(str(exc)) from exc
    result = vlc.vegalite_to_svg(json.dumps(vl_dict))
    return result.encode() if isinstance(result, str) else result  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

# Vega-Lite mark alias for chart_type values that use a string (e.g. "bar").
_MARK_ALIASES: dict[str, str] = {
    "bar": "bar",
    "line": "line",
    "area": "area",
    "scatter": "point",
    "histogram": "bar",
    "table": "bar",
}


def _build_vegalite(spec: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble a minimal Vega-Lite dict from a ``build_chart_spec`` output.

    Maps ``spec["chart_config"]["chart_type"]`` to a Vega-Lite mark and flattens
    the ``encodings`` dict, preserving Vega-Lite props beyond field/type/title
    (sort, axis, scale, stack, aggregate, bin, timeUnit, format).

    Raises :class:`ArgError` when rows is non-empty and any encoding ``field``
    is absent from the row objects — a schema mismatch that would silently
    produce a blank chart.
    """
    chart_config = spec.get("chart_config", {})
    chart_type: str = chart_config.get("chart_type", "bar")
    mark: Any = _MARK_ALIASES.get(chart_type, chart_type)

    raw_encodings: dict[str, Any] = chart_config.get("encodings", {})
    encoding: dict[str, Any] = {}
    required_fields: list[str] = []
    for channel, enc in raw_encodings.items():
        encoding[channel] = {
            "field": enc["field"],
            "type": enc["type"],
            "title": enc.get("title", enc["field"]),
        }
        for k in ("sort", "axis", "scale", "stack", "aggregate", "bin", "timeUnit", "format"):
            if k in enc:
                encoding[channel][k] = enc[k]
        required_fields.append(enc["field"])

    # Schema-mismatch guard: validate only when rows is non-empty so that an
    # empty dataset (rows=[]) still renders (an intentionally-empty chart is
    # valid).  A mismatch would otherwise silently produce a blank PNG.
    if rows and required_fields:
        row_keys = set(rows[0].keys())
        # De-dupe: one field can drive multiple encoding channels (e.g.
        # spend-by-product maps billing_origin_product to both arc and color), so
        # required_fields may repeat it. Report each field once.
        expected = sorted(set(required_fields))
        missing = sorted({f for f in required_fields if f not in row_keys})
        if missing:
            raise ArgError(
                f"chart kind '{chart_type}' is missing required field(s) "
                f"{missing!r}. It needs columns {expected!r}; the data rows have "
                f"{sorted(row_keys)!r}. Fix the --data rows to match the "
                f"'{chart_type}' schema (see `charts render --help` for all kinds)."
            )

    # Apply mark render options: interpolate + point become a mark object.
    options: dict[str, Any] = chart_config.get("options") or {}
    mark_opts = {k: options[k] for k in ("interpolate", "point") if k in options}
    if mark_opts:
        mark = {"type": mark, **mark_opts}

    # Build Vega-Lite top-level title from chart_config.
    title_text: str | None = chart_config.get("title")
    description: str | None = chart_config.get("description")
    vl_title: dict[str, Any] | None = None
    if title_text:
        vl_title = {"text": title_text}
        if description is not None:
            vl_title["subtitle"] = description

    result: dict[str, Any] = {
        "mark": mark,
        "data": {"values": rows},
        "encoding": encoding,
    }
    if vl_title is not None:
        result["title"] = vl_title
    return result


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


def cmd_render(args: Any) -> dict[str, Any]:
    """Render a chart spec + data rows to a PNG or SVG file.

    Args:
        args: Parsed namespace with ``kind``, ``data``, ``out``, and ``format``.

    Returns:
        A dict with ``out_path`` and ``bytes_written`` for the envelope.

    Raises:
        :class:`ArgError`: for bad arguments (unknown kind, missing file).
        :class:`HelperError`: if the render dep is not installed.
    """
    from starboard_x.charts import CHART_KINDS, build_chart_spec  # lazy – kernel dep

    kind: str = args.kind
    data_path: str = args.data
    out_path: str = args.out
    fmt: str = getattr(args, "format", "png")

    # --- Resolve spec --------------------------------------------------------
    try:
        spec = build_chart_spec(kind)
    except ValueError as exc:
        raise ArgError(
            f"unknown chart kind '{kind}'; expected one of: {', '.join(CHART_KINDS)}"
        ) from exc

    # --- Load rows -----------------------------------------------------------
    try:
        text = Path(data_path).read_text()
    except FileNotFoundError as exc:
        raise ArgError(f"data file not found: {data_path}") from exc

    rows: list[dict[str, Any]]
    # Try a JSON array first (standard form: [ {...}, {...} ])
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None  # fall through to NDJSON

    if parsed is not None:
        if not isinstance(parsed, list):
            raise ArgError(
                "data file must be a JSON array [...] or newline-delimited JSON objects "
                f"(NDJSON). Got a {type(parsed).__name__}. Wrap rows in [...] or produce "
                "NDJSON with `jq -c '.[]' rows.json`."
            )
        rows = parsed
    else:
        # Try NDJSON (newline-delimited JSON objects, e.g. jq output without [ ])
        ndjson_lines = [ln for ln in text.splitlines() if ln.strip()]
        if not ndjson_lines:
            raise ArgError(
                "data file is empty or whitespace-only. "
                "Expected a JSON array [{...}, ...] or newline-delimited JSON objects "
                "(NDJSON, one object per line, e.g. `jq -c '.[]' rows.json`)."
            )
        rows = []
        for i, line in enumerate(ndjson_lines, 1):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ArgError(
                    f"data file is not a JSON array or NDJSON: line {i} is not valid "
                    f"JSON ({exc}). Expected a JSON array [{{...}}, ...] or "
                    "newline-delimited JSON objects (one per line, "
                    "e.g. `jq -c '.[]' rows.json`)."
                ) from exc
            if not isinstance(obj, dict):
                raise ArgError(
                    f"data file is not a JSON array or NDJSON: line {i} is a "
                    f"{type(obj).__name__}, not a JSON object. Each NDJSON line must be "
                    'a JSON object {"field": value, ...}.'
                )
            rows.append(obj)

    # --- Build Vega-Lite dict ------------------------------------------------
    vl = _build_vegalite(spec, rows)

    # --- Render --------------------------------------------------------------
    raw = _vegalite_to_svg(vl) if fmt.lower() == "svg" else _vegalite_to_png(vl)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(raw)
    out_abs = str(Path(out_path).resolve())
    return {"out_path": out_abs, "bytes_written": len(raw), "kind": kind, "format": fmt}


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register(subparsers: Any) -> None:  # noqa: ANN401
    """Register the ``charts`` domain parser with its subcommands."""
    p = subparsers.add_parser("charts", help="Chart spec and rendering operations")
    sp = p.add_subparsers(dest="command", required=True)

    from starboard_x.charts import CHART_KINDS, REQUIRED_FIELDS  # lazy – kernel dep

    kind_fields = "Required input columns per chart kind:\n" + "\n".join(
        f"  {kind:<30}  {', '.join(REQUIRED_FIELDS[kind])}" for kind in CHART_KINDS
    )
    render = sp.add_parser(
        "render",
        help="Render a chart spec + data rows to PNG/SVG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=kind_fields,
    )
    render.add_argument(
        "--kind",
        required=True,
        type=str,
        help="Chart kind (e.g. spend-by-product, cost-trend, utilization-bands)",
    )
    render.add_argument(
        "--data",
        required=True,
        type=str,
        metavar="FILE",
        help="Path to a JSON file containing an array of data-row objects",
    )
    render.add_argument(
        "--out",
        required=True,
        type=str,
        metavar="FILE",
        help="Output file path (.png or .svg)",
    )
    render.add_argument(
        "--format",
        choices=["png", "svg"],
        default="png",
        help="Output format (default: png)",
    )
    render.set_defaults(func=cmd_render)
