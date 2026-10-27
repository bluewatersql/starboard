"""Thin Databricks data-fetching helpers for Starboard skills (any host).

Each module exposes a register(subparsers) function that wires CLI subcommands.
Helpers output structured JSON to stdout; errors go to stderr with exit codes:
  0 = ok
  1 = authentication error
  2 = not found
  3 = API error
  4 = argument error
"""
