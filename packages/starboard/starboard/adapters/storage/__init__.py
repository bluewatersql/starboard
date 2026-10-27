# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Remote storage adapters for the engagement storage port."""

from starboard.adapters.storage.google_drive import (
    AUTH_HINT as DRIVE_AUTH_HINT,
)
from starboard.adapters.storage.google_drive import (
    GoogleDriveStorage,
    gcloud_access_token,
)

__all__ = ["DRIVE_AUTH_HINT", "GoogleDriveStorage", "gcloud_access_token"]
