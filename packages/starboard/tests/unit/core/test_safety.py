# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for safety and approval management."""

from unittest.mock import patch

from starboard.infra.constraints.safety import ApprovalManager


class TestApprovalManager:
    """Test ApprovalManager functionality."""

    def test_approve_table_stats_update_approved_yes(self):
        """Test approval with 'yes' input."""
        with patch("builtins.input", return_value="yes"):
            result = ApprovalManager.approve_table_stats_update(["table1", "table2"])
            assert result == "APPROVED"

    def test_approve_table_stats_update_approved_y(self):
        """Test approval with 'y' input."""
        with patch("builtins.input", return_value="y"):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "APPROVED"

    def test_approve_table_stats_update_denied_no(self):
        """Test denial with 'no' input."""
        with patch("builtins.input", return_value="no"):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "DENY"

    def test_approve_table_stats_update_denied_empty(self):
        """Test denial with empty input."""
        with patch("builtins.input", return_value=""):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "DENY"

    def test_approve_table_stats_update_denied_random(self):
        """Test denial with random input."""
        with patch("builtins.input", return_value="maybe"):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "DENY"

    def test_approve_table_stats_update_keyboard_interrupt(self):
        """Test handling of keyboard interrupt (Ctrl+C)."""
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "DENY"

    def test_approve_table_stats_update_eof_error(self):
        """Test handling of EOF error."""
        with patch("builtins.input", side_effect=EOFError):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "DENY"

    def test_approve_table_stats_update_case_insensitive(self):
        """Test case insensitivity for yes/y."""
        with patch("builtins.input", return_value="YES"):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "APPROVED"

        with patch("builtins.input", return_value="Y"):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "APPROVED"

        with patch("builtins.input", return_value="Yes"):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "APPROVED"

    def test_approve_table_stats_update_whitespace(self):
        """Test handling of whitespace in input."""
        with patch("builtins.input", return_value="  yes  "):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "APPROVED"

        with patch("builtins.input", return_value="  no  "):
            result = ApprovalManager.approve_table_stats_update(["table1"])
            assert result == "DENY"

    def test_approve_table_stats_update_empty_table_list(self):
        """Test approval with empty table list."""
        with patch("builtins.input", return_value="yes"):
            result = ApprovalManager.approve_table_stats_update([])
            assert result == "APPROVED"

    def test_approve_sql_execution_approved_yes(self):
        """Test SQL execution approval with 'yes'."""
        with patch("builtins.input", return_value="yes"):
            result = ApprovalManager.approve_sql_execution("SELECT * FROM table")
            assert result == "APPROVED"

    def test_approve_sql_execution_approved_y(self):
        """Test SQL execution approval with 'y'."""
        with patch("builtins.input", return_value="y"):
            result = ApprovalManager.approve_sql_execution("SELECT * FROM table")
            assert result == "APPROVED"

    def test_approve_sql_execution_denied_no(self):
        """Test SQL execution denial with 'no'."""
        with patch("builtins.input", return_value="no"):
            result = ApprovalManager.approve_sql_execution("DROP TABLE table")
            assert result == "DENY"

    def test_approve_sql_execution_denied_random(self):
        """Test SQL execution denial with random input."""
        with patch("builtins.input", return_value="maybe"):
            result = ApprovalManager.approve_sql_execution("DELETE FROM table")
            assert result == "DENY"

    def test_approve_sql_execution_keyboard_interrupt(self):
        """Test SQL execution handling of keyboard interrupt."""
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = ApprovalManager.approve_sql_execution("UPDATE table SET col=val")
            assert result == "DENY"

    def test_approve_sql_execution_eof_error(self):
        """Test SQL execution handling of EOF error."""
        with patch("builtins.input", side_effect=EOFError):
            result = ApprovalManager.approve_sql_execution("ALTER TABLE table")
            assert result == "DENY"

    def test_approve_sql_execution_case_insensitive(self):
        """Test SQL execution case insensitivity."""
        with patch("builtins.input", return_value="YES"):
            result = ApprovalManager.approve_sql_execution("SELECT 1")
            assert result == "APPROVED"

        with patch("builtins.input", return_value="Y"):
            result = ApprovalManager.approve_sql_execution("SELECT 1")
            assert result == "APPROVED"

    def test_approve_sql_execution_long_query(self):
        """Test SQL execution with very long query."""
        long_sql = "SELECT * FROM table WHERE " + " AND ".join(
            [f"col{i} = {i}" for i in range(100)]
        )
        with patch("builtins.input", return_value="yes"):
            result = ApprovalManager.approve_sql_execution(long_sql)
            assert result == "APPROVED"

    def test_static_methods(self):
        """Test that approval methods are static."""
        # Should be callable without instantiation
        assert callable(ApprovalManager.approve_table_stats_update)
        assert callable(ApprovalManager.approve_sql_execution)

        # Should not require instance
        with patch("builtins.input", return_value="yes"):
            result = ApprovalManager.approve_table_stats_update(["table"])
            assert result == "APPROVED"
