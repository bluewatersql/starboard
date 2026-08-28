# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.charts`` — pure chart-spec CLI (Phase-2 X2).

Thin ``argparse`` wrapper over the SDK-free chart-spec builder in
:mod:`starboard_x.charts`. Every invocation emits the stable JSON envelope
(:mod:`starboard_x.contract`) and uses the Phase-0 exit-code contract
(``0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error``).

Emits Vega-Lite-style chart *specs* (no render deps). With no ``--kind`` it
returns every chart kind keyed by name; with ``--kind`` it returns just that
spec::

    python -m starboard_x.charts                       # all specs
    python -m starboard_x.charts --kind cost-trend     # one spec
"""

from __future__ import annotations

import argparse
from typing import Any

from starboard_x import _cli
from starboard_x.charts import CHART_KINDS, build_chart_spec

_DOMAIN = "charts"


def _cmd_build(args: argparse.Namespace) -> dict[str, Any]:
    if args.kind:
        return {args.kind: build_chart_spec(args.kind)}
    return {kind: build_chart_spec(kind) for kind in CHART_KINDS}


def build_parser() -> argparse.ArgumentParser:
    """Construct the fully-wired CLI parser (importable for tests)."""
    parser = _cli.ArgumentParser(
        prog="python -m starboard_x.charts",
        description="Pure Vega-Lite-style chart-spec builder (no render deps).",
    )
    parser.add_argument("--format", choices=["json"], default="json")
    parser.add_argument(
        "--kind",
        choices=list(CHART_KINDS),
        default=None,
        help="Chart kind to build (default: all kinds keyed by name).",
    )
    parser.set_defaults(func=_cmd_build, command="build")
    return parser


def main(argv: list[str] | None = None) -> None:
    _cli.run(domain=_DOMAIN, parser=build_parser(), argv=argv)


if __name__ == "__main__":
    main()
