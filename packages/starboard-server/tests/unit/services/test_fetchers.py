# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for context fetchers.

The _parse_job_id function extracts the first numeric sequence from any string,
allowing flexible input formats without requiring specific prefixes.
"""

import pytest
from starboard_server.services.context.fetchers import _parse_job_id


class TestParseJobId:
    """Tests for the _parse_job_id helper function.

    This function uses regex to extract the first numeric ID from any string format,
    supporting legacy prefixed formats while enabling direct numeric input.
    """

    def test_parse_plain_numeric(self):
        """Test parsing plain numeric string (primary use case)."""
        result = _parse_job_id("266829928906781")
        assert result == 266829928906781
        assert isinstance(result, int)

    def test_parse_small_numeric(self):
        """Test parsing small numeric ID."""
        result = _parse_job_id("12345")
        assert result == 12345

    def test_parse_with_surrounding_whitespace(self):
        """Test parsing strips whitespace automatically."""
        result = _parse_job_id("  266829928906781  ")
        assert result == 266829928906781

    def test_parse_legacy_format_with_colon(self):
        """Test backward compatibility with legacy 'job_id:' format."""
        result = _parse_job_id("job_id:266829928906781")
        assert result == 266829928906781

    def test_parse_legacy_format_with_whitespace(self):
        """Test legacy format handles extra whitespace."""
        result = _parse_job_id("  job_id:  12345  ")
        assert result == 12345

    def test_parse_extracts_first_number(self):
        """Test extracts first numeric sequence when multiple present."""
        result = _parse_job_id("job_id:123:456")
        assert result == 123

    def test_parse_from_mixed_text(self):
        """Test extracts number from mixed alphanumeric text."""
        result = _parse_job_id("run_123_final")
        assert result == 123

    def test_parse_after_text_prefix(self):
        """Test extracts number that appears after text."""
        result = _parse_job_id("abc123def")
        assert result == 123

    def test_parse_multiple_numbers_gets_first(self):
        """Test with multiple numbers returns the first one."""
        result = _parse_job_id("123 456 789")
        assert result == 123

    def test_parse_zero_is_valid(self):
        """Test that zero is a valid job ID."""
        result = _parse_job_id("0")
        assert result == 0

    def test_parse_negative_number(self):
        """Test that negative numbers are extracted (edge case)."""
        result = _parse_job_id("-123")
        assert result == -123

    def test_parse_empty_string_raises_error(self):
        """Test that empty string raises descriptive error."""
        with pytest.raises(ValueError, match="job_id cannot be empty"):
            _parse_job_id("")

    def test_parse_none_raises_error(self):
        """Test that None input raises descriptive error."""
        with pytest.raises(ValueError, match="job_id cannot be empty"):
            _parse_job_id(None)

    def test_parse_no_numbers_raises_error(self):
        """Test that string without numbers raises error."""
        with pytest.raises(ValueError, match="No numeric ID found"):
            _parse_job_id("invalid_job_name")

    def test_parse_text_only_raises_error(self):
        """Test that text-only string raises error."""
        with pytest.raises(ValueError, match="No numeric ID found"):
            _parse_job_id("job_id:not_a_number")
