# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Logging set up by one test must not leak into the next (order-dependent flake).

``setup_cli_logging`` binds structlog's ``PrintLoggerFactory`` and the root
``StreamHandler`` to the current ``sys.stderr``. Under ``capsys`` that stream is
closed at teardown, so a later test that logs through the CLI logger (with
``setup_cli_logging`` patched out) used to fail with "I/O operation on closed file".
The two tests run in file order: the first pollutes, the second logs.
"""

from __future__ import annotations

import logging

import pytest
from starboard.cli.cli import main as cli_main


@pytest.mark.unit
def test_a_real_cli_logging_setup_under_capsys(capsys: pytest.CaptureFixture[str]) -> None:
    cli_main.setup_cli_logging(log_level="WARNING")
    cli_main.logger.warning("bound_to_the_captured_stream")
    assert "bound_to_the_captured_stream" in capsys.readouterr().err


@pytest.mark.unit
def test_b_a_later_test_can_still_log() -> None:
    cli_main.logger.error("after_the_capture_closed")
    logging.getLogger("starboard.cli").error("stdlib_after_the_capture_closed")
    for handler in logging.getLogger().handlers:
        stream = getattr(handler, "stream", None)
        assert stream is None or not getattr(stream, "closed", False)
