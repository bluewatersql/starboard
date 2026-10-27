# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Public surface of the run-authorization (overlay workspace allow-list) loader.

:mod:`starboard_x.discovery._authorization` is the private implementation;
code outside ``starboard_x`` imports these names from here. Kernel + stdlib
only, so importing it never pulls ``starboard`` / ``databricks-sdk`` in.
"""

from __future__ import annotations

from starboard_x.discovery._authorization import (
    AUTHORIZATION_HELP,
    EXIT_STORAGE_REFUSED,
    authorization_run_dir,
    load_authorized_workspace_ids,
    load_authorized_workspace_ids_from_run_folder,
    local_capture_sink,
)

__all__ = [
    "AUTHORIZATION_HELP",
    "EXIT_STORAGE_REFUSED",
    "authorization_run_dir",
    "load_authorized_workspace_ids",
    "load_authorized_workspace_ids_from_run_folder",
    "local_capture_sink",
]
