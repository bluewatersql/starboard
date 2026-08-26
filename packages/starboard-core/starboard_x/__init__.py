# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x`` — the dep-light middle tier CLI namespace (Phase-1 B2).

Each capability is a runnable module (``python -m starboard_x.<domain>``) that
wraps the re-homed pure analyzers and emits the stable JSON envelope
(:mod:`starboard_x.contract`). Base install is pydantic-only; each capability
installs only its extra (see ``starboard-core`` ``[project.optional-dependencies]``).

This top-level package intentionally does **no eager imports** of the
sub-modules so that ``python -m starboard_x.diagnostic`` pulls in only the
diagnostic trio (stdlib-only) and none of the heavier capabilities.
"""

__all__: list[str] = []
