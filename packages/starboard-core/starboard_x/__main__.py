# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard-x`` / ``python -m starboard_x`` — dispatcher to capability modules.

Delegates ``starboard-x <domain> <verb> ...`` to ``python -m starboard_x.<domain>``
so the console-script entry point and the ``python -m`` interface share one code
path. Only ``diagnostic`` is implemented in Phase 1; the other capabilities are
declared in the extras taxonomy (D-1.3) and land in Phase 2.

Sub-modules are imported lazily (inside :func:`main`) so invoking one capability
never pulls another capability's dependencies into the process.
"""

from __future__ import annotations

import sys

from starboard_x.contract import EXIT_ARG

# Capabilities whose ``__main__`` this dispatcher can route to. Only the
# diagnostic trio is implemented in Phase 1 (D-1.3).
_IMPLEMENTED: dict[str, str] = {
    "diagnostic": "starboard_x.diagnostic.__main__",
}

# Declared-but-not-yet-implemented capabilities (extras stubs, Phase 2+).
_DECLARED: tuple[str, ...] = (
    "discovery",
    "sparklog",
    "warehouse",
    "uc",
    "cluster",
    "charts",
)


def _usage() -> str:
    domains = ", ".join(sorted(_IMPLEMENTED))
    return (
        "usage: starboard-x <domain> <verb> [options]\n"
        f"  implemented domains: {domains}\n"
        f"  declared (Phase 2+): {', '.join(_DECLARED)}\n"
    )


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        sys.stdout.write(_usage())
        sys.exit(0 if args else EXIT_ARG)

    domain = args[0]
    module_name = _IMPLEMENTED.get(domain)
    if module_name is None:
        if domain in _DECLARED:
            sys.stderr.write(
                f"starboard-x: '{domain}' is declared but not implemented in this "
                f"release. Install its extra and use a future version.\n"
            )
        else:
            sys.stderr.write(f"starboard-x: unknown domain '{domain}'\n{_usage()}")
        sys.exit(EXIT_ARG)

    import importlib

    module = importlib.import_module(module_name)
    module.main(args[1:])


if __name__ == "__main__":
    main()
