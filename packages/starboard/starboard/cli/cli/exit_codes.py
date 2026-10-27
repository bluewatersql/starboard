# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Standard exit codes for CLI processes.

These constants provide semantic exit codes so that shell scripts and CI
pipelines can distinguish between failure modes without parsing stderr.
"""

# ``CAPTURE_INCOMPLETE`` (9): a ``--run-folder`` discovery capture reached its
# ``--max-seconds`` budget; progress is saved and the same command resumes it.
from starboard_core.domain.models.discovery.capture import (
    EXIT_CAPTURE_INCOMPLETE as CAPTURE_INCOMPLETE,
)

# ``STORAGE_FAILURE`` (7): a storage / integrity / access failure on an engagement run
# (``BLOCKED_ACCESS`` ...). The kernel's code, shared with ``starboard review`` and the
# ``starboard_x`` helpers: one source of truth.
from starboard_core.engagement.sink import EXIT_STORAGE_FAILURE as STORAGE_FAILURE

# ``STORAGE_TRANSIENT`` (8): a retryable Drive failure (nothing refused; run the same
# command again), the same code on every writer surface.
from starboard_core.engagement.sink import EXIT_STORAGE_TRANSIENT as STORAGE_TRANSIENT

__all__ = [
    "AUTH_ERROR",
    "CAPTURE_INCOMPLETE",
    "CONFIG_ERROR",
    "CONNECTION_ERROR",
    "GENERAL_ERROR",
    "INTERRUPTED",
    "STORAGE_FAILURE",
    "STORAGE_TRANSIENT",
    "SUCCESS",
    "TIMEOUT_ERROR",
    "USAGE_ERROR",
]

SUCCESS = 0
GENERAL_ERROR = 1
USAGE_ERROR = 2
CONFIG_ERROR = 3
AUTH_ERROR = 4
CONNECTION_ERROR = 5
TIMEOUT_ERROR = 6
INTERRUPTED = 130  # 128 + SIGINT
