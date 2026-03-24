"""Unit tests for PositionTracker."""

from starboard_server.agents.utils.position_tracker import (
    PositionTracker,
    ToolPositionData,
)


class TestToolPositionData:
    """Tests for ToolPositionData dataclass."""

    def test_create_position_data(self) -> None:
        """Test creating position data."""
        pos = ToolPositionData(
            tool_call_id="tool_123",
            position=42,
            display="inline",
        )

        assert pos.tool_call_id == "tool_123"
        assert pos.position == 42
        assert pos.display == "inline"

    def test_default_display(self) -> None:
        """Test default display value is inline."""
        pos = ToolPositionData(tool_call_id="t1", position=10)

        assert pos.display == "inline"

    def test_to_dict(self) -> None:
        """Test converting to dict."""
        pos = ToolPositionData("tool_1", 10, "group")
        result = pos.to_dict()

        assert result == {
            "tool_call_id": "tool_1",
            "position": 10,
            "display": "group",
        }

    def test_to_dict_preserves_all_fields(self) -> None:
        """Test to_dict includes all fields."""
        pos = ToolPositionData(
            tool_call_id="unique_id",
            position=999,
            display="hidden",
        )
        result = pos.to_dict()

        assert "tool_call_id" in result
        assert "position" in result
        assert "display" in result
        assert result["tool_call_id"] == "unique_id"
        assert result["position"] == 999
        assert result["display"] == "hidden"


class TestPositionTracker:
    """Tests for PositionTracker class."""

    def test_init_empty(self) -> None:
        """Test initialization creates empty tracker."""
        tracker = PositionTracker()

        assert tracker.content_length == 0
        assert len(tracker.tool_positions) == 0
        assert tracker.get_all_positions() == []

    def test_add_thinking_updates_length(self) -> None:
        """Test adding thinking updates content length."""
        tracker = PositionTracker()

        tracker.add_thinking("Hello ")
        assert tracker.content_length == 6

        tracker.add_thinking("world")
        assert tracker.content_length == 11

    def test_add_thinking_with_empty_string(self) -> None:
        """Test empty string doesn't affect length."""
        tracker = PositionTracker()

        tracker.add_thinking("")
        assert tracker.content_length == 0

        tracker.add_thinking("Text")
        tracker.add_thinking("")
        assert tracker.content_length == 4

    def test_add_thinking_with_none(self) -> None:
        """Test None is handled gracefully."""
        tracker = PositionTracker()

        tracker.add_thinking(None)
        assert tracker.content_length == 0

    def test_add_thinking_with_unicode(self) -> None:
        """Test Unicode characters are counted correctly."""
        tracker = PositionTracker()

        # Python len() counts Unicode code points, not bytes
        # "Hello " = 6 chars + "🌍" = 1 char = 7 total
        tracker.add_thinking("Hello 🌍")
        assert tracker.content_length == 7

    def test_add_thinking_with_newlines(self) -> None:
        """Test newlines are counted in length."""
        tracker = PositionTracker()

        tracker.add_thinking("Line 1\nLine 2")
        assert tracker.content_length == 13

    def test_add_tool_position_at_current_length(self) -> None:
        """Test tool position is at current content length."""
        tracker = PositionTracker()

        tracker.add_thinking("Analyzing query. ")
        pos = tracker.add_tool_position("tool_1", "fetch_query")

        assert pos.position == 17
        assert pos.tool_call_id == "tool_1"
        assert pos.display == "inline"

    def test_add_tool_position_with_custom_display(self) -> None:
        """Test tool position with custom display mode."""
        tracker = PositionTracker()

        tracker.add_thinking("Content ")
        pos = tracker.add_tool_position("tool_1", "fetch", display="group")

        assert pos.display == "group"

    def test_multiple_tools_sequential_positions(self) -> None:
        """Test multiple tools get increasing positions."""
        tracker = PositionTracker()

        tracker.add_thinking("Step 1. ")
        pos1 = tracker.add_tool_position("tool_1", "fetch_query")

        tracker.add_thinking("Step 2. ")
        pos2 = tracker.add_tool_position("tool_2", "analyze_plan")

        assert pos1.position == 8
        assert pos2.position == 16
        assert pos2.position > pos1.position

    def test_tool_position_without_prior_thinking(self) -> None:
        """Test tool at position 0 if no thinking yet."""
        tracker = PositionTracker()

        pos = tracker.add_tool_position("tool_1", "fetch")

        assert pos.position == 0

    def test_get_all_positions_returns_list_of_dicts(self) -> None:
        """Test get_all_positions returns serializable dicts."""
        tracker = PositionTracker()

        tracker.add_thinking("Content ")
        tracker.add_tool_position("tool_1", "fetch")
        tracker.add_thinking("More ")
        tracker.add_tool_position("tool_2", "analyze")

        positions = tracker.get_all_positions()

        assert len(positions) == 2
        assert positions[0] == {
            "tool_call_id": "tool_1",
            "position": 8,
            "display": "inline",
        }
        assert positions[1] == {
            "tool_call_id": "tool_2",
            "position": 13,
            "display": "inline",
        }

    def test_get_all_positions_returns_new_list(self) -> None:
        """Test get_all_positions returns a new list each time."""
        tracker = PositionTracker()
        tracker.add_thinking("Text")
        tracker.add_tool_position("tool_1", "fetch")

        positions1 = tracker.get_all_positions()
        positions2 = tracker.get_all_positions()

        assert positions1 == positions2
        assert positions1 is not positions2  # Different list objects

    def test_monotonic_positions(self) -> None:
        """Test positions never go backward."""
        tracker = PositionTracker()

        tracker.add_thinking("Text ")
        pos1 = tracker.add_tool_position("tool_1", "fetch")

        # Even if content doesn't grow, position shouldn't go back
        pos2 = tracker.add_tool_position("tool_2", "analyze")

        assert pos2.position >= pos1.position

    def test_monotonic_positions_multiple_tools_same_position(self) -> None:
        """Test multiple tools at same content position maintain order."""
        tracker = PositionTracker()

        # Two tools start immediately
        pos1 = tracker.add_tool_position("tool_1", "fetch")
        pos2 = tracker.add_tool_position("tool_2", "analyze")
        pos3 = tracker.add_tool_position("tool_3", "validate")

        # All at position 0, but should not go backward
        assert pos1.position == 0
        assert pos2.position >= pos1.position
        assert pos3.position >= pos2.position

    def test_reset(self) -> None:
        """Test reset clears tracker state."""
        tracker = PositionTracker()

        tracker.add_thinking("Content")
        tracker.add_tool_position("tool_1", "fetch")

        tracker.reset()

        assert tracker.content_length == 0
        assert tracker.get_all_positions() == []
        assert tracker._last_tool_position == 0

    def test_reset_allows_reuse(self) -> None:
        """Test tracker can be reused after reset."""
        tracker = PositionTracker()

        # First use
        tracker.add_thinking("First")
        tracker.add_tool_position("t1", "fetch")

        tracker.reset()

        # Second use
        tracker.add_thinking("Second")
        pos = tracker.add_tool_position("t2", "analyze")

        assert pos.position == 6  # Length of "Second"
        assert len(tracker.get_all_positions()) == 1

    def test_realistic_scenario(self) -> None:
        """Test realistic message streaming scenario."""
        tracker = PositionTracker()

        # LLM generates thinking in chunks
        tracker.add_thinking("I'll analyze ")
        tracker.add_thinking("the query ")
        tracker.add_thinking("to understand ")
        tracker.add_thinking("its structure. ")

        # Tool 1 starts
        pos1 = tracker.add_tool_position("tool_abc", "fetch_query")
        assert pos1.position == 52  # After "its structure. "

        # More thinking
        tracker.add_thinking("Based on the ")
        tracker.add_thinking("query plan, ")

        # Tool 2 starts
        pos2 = tracker.add_tool_position("tool_def", "analyze_plan")
        assert pos2.position == 77  # 52 + 25 = 77

        # Final thinking
        tracker.add_thinking("here are my recommendations.")

        # Get all positions for storage
        positions = tracker.get_all_positions()
        assert len(positions) == 2
        assert positions[0]["position"] == 52
        assert positions[1]["position"] == 77

    def test_position_stored_in_list(self) -> None:
        """Test positions are stored in internal list."""
        tracker = PositionTracker()

        tracker.add_thinking("Test ")
        pos = tracker.add_tool_position("t1", "fetch")

        assert len(tracker.tool_positions) == 1
        assert tracker.tool_positions[0] is pos

    def test_multiple_tools_order_preserved(self) -> None:
        """Test order of tools is preserved in positions."""
        tracker = PositionTracker()

        tracker.add_thinking("Content ")
        tracker.add_tool_position("first", "fetch")
        tracker.add_thinking("More ")
        tracker.add_tool_position("second", "analyze")
        tracker.add_thinking("More ")
        tracker.add_tool_position("third", "validate")

        positions = tracker.get_all_positions()

        assert positions[0]["tool_call_id"] == "first"
        assert positions[1]["tool_call_id"] == "second"
        assert positions[2]["tool_call_id"] == "third"

    def test_long_content(self) -> None:
        """Test with longer content chunks."""
        tracker = PositionTracker()

        # Simulate a long analysis
        long_thinking = "A" * 1000
        tracker.add_thinking(long_thinking)

        pos = tracker.add_tool_position("t1", "fetch")

        assert pos.position == 1000
        assert tracker.content_length == 1000

    def test_tool_name_not_used_yet(self) -> None:
        """Test tool_name parameter exists for future use."""
        tracker = PositionTracker()

        tracker.add_thinking("Test ")
        # tool_name is captured but not used yet (for future smart positioning)
        pos = tracker.add_tool_position("t1", "get_cluster_config")

        assert pos.tool_call_id == "t1"
        # Position is based on content length, not tool name
        assert pos.position == 5


class TestPositionTrackerEdgeCases:
    """Edge case tests for PositionTracker."""

    def test_empty_tool_call_id(self) -> None:
        """Test empty tool_call_id is allowed."""
        tracker = PositionTracker()

        pos = tracker.add_tool_position("", "fetch")

        assert pos.tool_call_id == ""
        assert pos.position == 0

    def test_empty_tool_name(self) -> None:
        """Test empty tool_name is allowed."""
        tracker = PositionTracker()

        pos = tracker.add_tool_position("t1", "")

        assert pos.tool_call_id == "t1"

    def test_special_characters_in_content(self) -> None:
        """Test content with special characters."""
        tracker = PositionTracker()

        tracker.add_thinking("SELECT * FROM `table` WHERE id = 'test';")

        assert tracker.content_length == 40

    def test_whitespace_only_content(self) -> None:
        """Test whitespace-only content."""
        tracker = PositionTracker()

        tracker.add_thinking("   ")
        assert tracker.content_length == 3

        tracker.add_thinking("\t\n")
        assert tracker.content_length == 5
