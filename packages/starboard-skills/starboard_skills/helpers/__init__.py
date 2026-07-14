"""Thin Databricks data-fetching helpers for Claude skills.

Each module exposes a register(subparsers) function that wires CLI subcommands.
Helpers output structured JSON to stdout; errors go to stderr with exit codes:
  0 = ok
  1 = authentication error
  2 = not found
  3 = API error
  4 = argument error
"""
