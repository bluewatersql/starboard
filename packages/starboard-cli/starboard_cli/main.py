# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Starboard CLI - Entry point for the command-line interface.

This module re-exports the main function from the CLI implementation.
"""

from starboard_cli.cli.main import main


# For script entry point
def app():
    """Entry point for console script."""
    main()


if __name__ == "__main__":
    main()
