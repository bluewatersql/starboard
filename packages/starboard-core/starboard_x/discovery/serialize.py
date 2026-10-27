# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Public surface of the dep-light discovery result serializers.

:mod:`starboard_x.discovery._serialize` is the private implementation shared by
``python -m starboard_x.discovery``; code outside ``starboard_x`` (the ``starboard``
CLI) imports these names from here. Kernel + stdlib only.
"""

from __future__ import annotations

from starboard_x.discovery._serialize import (
    SUMMARY_PACK_KEYS,
    fit_summary,
    serialize_result,
    write_envelope_file,
    write_facts_file,
    write_pack_file,
    write_result_files,
)

__all__ = [
    "SUMMARY_PACK_KEYS",
    "fit_summary",
    "serialize_result",
    "write_envelope_file",
    "write_facts_file",
    "write_pack_file",
    "write_result_files",
]
