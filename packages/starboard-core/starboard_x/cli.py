# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Public host-facing surface of the shared ``starboard_x`` CLI plumbing.

:mod:`starboard_x._cli` is the private, stdlib-only implementation shared by
every ``python -m starboard_x.<domain>`` helper. Code outside ``starboard_x``
(the ``starboard`` CLI, plugins) imports the refusal / storage error types and
the overlay intake helpers from here instead of reaching into the private
module.
"""

from __future__ import annotations

from starboard_x._cli import (
    LocalFileIntakeRefused,
    RefusedError,
    StorageFailureError,
    local_intake_refusal,
    read_text_file,
)

__all__ = [
    "LocalFileIntakeRefused",
    "RefusedError",
    "StorageFailureError",
    "local_intake_refusal",
    "read_text_file",
]
