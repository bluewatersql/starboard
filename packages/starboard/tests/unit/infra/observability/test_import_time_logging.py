# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for import-time structlog configuration and level filtering.

Covers the fix for DEBUG logs leaking during module import before
setup_structured_logging() is called (e.g. formatter registration side effects).
"""

from __future__ import annotations

import logging

import pytest
import structlog

import starboard.infra.observability.logging as slog
from starboard.infra.observability.logging import get_logger, setup_structured_logging


class TestImportTimeConfiguration:
    """structlog is configured at module import time."""

    def test_configured_at_import(self) -> None:
        """After importing the logging module, structlog must be configured."""
        assert structlog.is_configured() is True


class TestImportTimeDebugFiltered:
    """DEBUG is filtered by default (stdlib root defaults to WARNING)."""

    def test_debug_not_emitted_by_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        """With no explicit setup call, a debug log must not reach stderr."""
        # The stdlib root logger starts at WARNING (30), so a DEBUG event
        # routed through LoggerFactory() is dropped by the stdlib handler
        # before it can be rendered.
        root = logging.getLogger()
        original_level = root.level
        try:
            # Ensure root is at WARNING (it should be, but be explicit)
            root.setLevel(logging.WARNING)
            logger = get_logger("test.import_default")
            logger.debug("should_be_filtered_at_import_time", x=1)
            captured = capsys.readouterr()
            assert "should_be_filtered_at_import_time" not in captured.err
            assert "should_be_filtered_at_import_time" not in captured.out
        finally:
            root.setLevel(original_level)


class TestSetupWarningLevel:
    """setup_structured_logging(WARNING) suppresses debug but passes warning."""

    def test_debug_absent_at_warning_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        setup_structured_logging(level=logging.WARNING)
        logger = get_logger("test.warning_level")
        logger.debug("nope_debug", flag=True)
        captured = capsys.readouterr()
        assert "nope_debug" not in captured.err
        assert "nope_debug" not in captured.out

    def test_warning_present_at_warning_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        setup_structured_logging(level=logging.WARNING)
        logger = get_logger("test.warning_level")
        logger.warning("yes_warning", flag=True)
        captured = capsys.readouterr()
        assert "yes_warning" in captured.err or "yes_warning" in captured.out


class TestSetupDebugLevel:
    """setup_structured_logging(DEBUG) shows debug messages."""

    def test_debug_present_at_debug_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        setup_structured_logging(level=logging.DEBUG)
        logger = get_logger("test.debug_level")
        logger.debug("shown_at_debug", flag=True)
        captured = capsys.readouterr()
        assert "shown_at_debug" in captured.err or "shown_at_debug" in captured.out

    def teardown_method(self) -> None:
        # Restore to WARNING after the debug test so other tests aren't polluted
        setup_structured_logging(level=logging.WARNING)


class TestReconfigurationWithCachedLogger:
    """Reconfiguration works even when cache_logger_on_first_use=True."""

    def test_cached_logger_respects_reconfiguration(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A logger obtained before reconfiguration must obey the new level."""
        # Get a logger (may or may not be cached from prior use)
        logger = get_logger("test.cached_reconfig")

        # Set to WARNING — debug should be silent
        setup_structured_logging(level=logging.WARNING)
        logger.debug("should_be_silent", step=1)
        captured = capsys.readouterr()
        assert "should_be_silent" not in captured.err
        assert "should_be_silent" not in captured.out

        # Reconfigure to DEBUG — debug should now appear
        setup_structured_logging(level=logging.DEBUG)
        logger.debug("should_be_visible", step=2)
        captured = capsys.readouterr()
        assert "should_be_visible" in captured.err or "should_be_visible" in captured.out

    def teardown_method(self) -> None:
        setup_structured_logging(level=logging.WARNING)
