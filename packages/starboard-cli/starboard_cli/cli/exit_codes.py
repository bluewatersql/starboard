# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Standard exit codes for CLI processes.

These constants provide semantic exit codes so that shell scripts and CI
pipelines can distinguish between failure modes without parsing stderr.
"""

SUCCESS = 0
GENERAL_ERROR = 1
USAGE_ERROR = 2
CONFIG_ERROR = 3
AUTH_ERROR = 4
CONNECTION_ERROR = 5
TIMEOUT_ERROR = 6
INTERRUPTED = 130  # 128 + SIGINT
