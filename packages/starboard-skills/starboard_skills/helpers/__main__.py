#!/usr/bin/env python3
"""starboard-helper <domain> <command> [options]

Thin Databricks data-fetching helper for Claude skills.
Outputs structured JSON to stdout. Errors go to stderr with exit codes:
  0 = ok
  1 = authentication error
  2 = not found
  3 = API error
  4 = argument error
"""
import json
import sys
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="starboard-helper",
        description="Thin Databricks data-fetching helper for Claude skills.",
    )
    subparsers = parser.add_subparsers(dest="domain", required=True)

    from starboard_skills.helpers import (
        job,
        query,
        warehouse,
        uc,
        cluster,
        finops,
        diagnostic,
    )

    for mod in [job, query, warehouse, uc, cluster, finops, diagnostic]:
        mod.register(subparsers)

    args = parser.parse_args()
    try:
        result = args.func(args)
        print(json.dumps(result, indent=2, default=str))
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
