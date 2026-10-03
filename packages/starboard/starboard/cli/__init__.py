# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Starboard CLI - Command-line interface for Starboard AI Agent.

This package provides the CLI for interacting with Starboard:
- Query optimization commands
- Job optimization commands
- Pipeline optimization commands
- Rich terminal output
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("starboard")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "__version__",
]
