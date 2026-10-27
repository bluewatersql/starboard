# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery capture contract: the resume record and the wall-clock budget.

A ``--run-folder`` discovery capture keeps a progress record in the run sink
(:data:`PROGRESS_PATH`, with each finished query's rows under ``capture/queries/``)
so re-running the **same** command resumes: finished queries are reused, and a
query's statement timeouts carry across runs so one that keeps timing out ends
up skipped. A capture that reaches its wall-clock budget (``--max-seconds``)
stops starting queries, saves its progress and leaves with
:data:`EXIT_CAPTURE_INCOMPLETE` / :data:`CAPTURE_INCOMPLETE` (retryable).

Shared by ``starboard --discover`` and ``python -m starboard_x.discovery``;
stdlib-only.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from typing import Any

#: Envelope ``error_type`` / ``errors[].code`` of a capture stopped by its budget.
CAPTURE_INCOMPLETE = "CAPTURE_INCOMPLETE"
#: Exit code of a capture stopped by its budget (same on every surface).
EXIT_CAPTURE_INCOMPLETE = 9
#: Default ``--max-seconds`` of a ``--run-folder`` capture: under a host's
#: 600 s command limit, with room for a worker blocked past the deadline
#: (up to ~50 s) and the final progress upload.
DEFAULT_MAX_SECONDS = 480
#: Run-relative directory of the capture's working state (not evidence).
CAPTURE_DIR = "capture"
#: Run-relative path of the progress record.
PROGRESS_PATH = f"{CAPTURE_DIR}/discovery-progress.json"
#: ``schema`` of the progress record.
PROGRESS_SCHEMA = "starboard.discovery.capture/v1"


def is_capture_path(path: str) -> bool:
    """Whether ``path`` is capture working state (kept out of stdout ref lists)."""
    return path.startswith(f"{CAPTURE_DIR}/")


def resume_command(prog: Sequence[str], argv: Sequence[str]) -> str:
    """The shell command that resumes this capture: the same ``argv``, quoted."""
    return shlex.join([*prog, *argv])


class CaptureIncomplete(Exception):
    """The capture's wall-clock budget ran out before every query finished.

    Progress is saved in the run sink; re-running the same command resumes.

    Attributes:
        code: :data:`CAPTURE_INCOMPLETE`.
        retryable: Always ``True``.
        done: Queries finished (this run and earlier ones).
        remaining: Scheduled queries not finished, or ``None`` when the budget
            ran out before the packs were selected.
        reused: Queries reused from an earlier run.
    """

    code: str = CAPTURE_INCOMPLETE
    retryable: bool = True

    def __init__(self, *, done: int, remaining: int | None, reused: int) -> None:
        left = "an unknown number of" if remaining is None else str(remaining)
        super().__init__(
            f"capture budget spent: {done} queries done, {left} remaining; progress "
            "is saved -- re-run the same command to resume"
        )
        self.done = done
        self.remaining = remaining
        self.reused = reused

    def progress(self) -> dict[str, Any]:
        """``{done, remaining, reused}`` for the incomplete envelope."""
        return {"done": self.done, "remaining": self.remaining, "reused": self.reused}
