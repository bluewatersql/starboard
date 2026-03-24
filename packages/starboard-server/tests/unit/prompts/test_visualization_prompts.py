"""
Unit tests for visualization prompts.

Tests prompt templates, few-shot examples, and metadata integration.
"""

from __future__ import annotations


class TestVisualizationPromptV1:
    """Test visualization prompt version 1."""

    def test_system_prompt_exists(self):
        """Test that system prompt constant exists."""
        from starboard_server.prompts.visualization.v1 import (
            VISUALIZATION_SYSTEM_PROMPT,
        )

        assert isinstance(VISUALIZATION_SYSTEM_PROMPT, str)
        assert len(VISUALIZATION_SYSTEM_PROMPT) > 100  # Should be substantial

    def test_system_prompt_includes_role(self):
        """Test that system prompt defines the role."""
        from starboard_server.prompts.visualization.v1 import (
            VISUALIZATION_SYSTEM_PROMPT,
        )

        assert (
            "visualization" in VISUALIZATION_SYSTEM_PROMPT.lower()
            or "chart" in VISUALIZATION_SYSTEM_PROMPT.lower()
        )
        assert "expert" in VISUALIZATION_SYSTEM_PROMPT.lower()

    def test_system_prompt_includes_constraints(self):
        """Test that system prompt includes constraints."""
        from starboard_server.prompts.visualization.v1 import (
            VISUALIZATION_SYSTEM_PROMPT,
        )

        # Should mention chart types
        assert "bar" in VISUALIZATION_SYSTEM_PROMPT.lower()
        assert "line" in VISUALIZATION_SYSTEM_PROMPT.lower()
        assert "table" in VISUALIZATION_SYSTEM_PROMPT.lower()

    def test_system_prompt_includes_output_format(self):
        """Test that system prompt specifies output format."""
        from starboard_server.prompts.visualization.v1 import (
            VISUALIZATION_SYSTEM_PROMPT,
        )

        # Should mention JSON or structured output
        assert (
            "json" in VISUALIZATION_SYSTEM_PROMPT.lower()
            or "format" in VISUALIZATION_SYSTEM_PROMPT.lower()
        )

    def test_few_shot_examples_exist(self):
        """Test that few-shot examples are defined."""
        from starboard_server.prompts.visualization.v1 import FEW_SHOT_EXAMPLES

        assert isinstance(FEW_SHOT_EXAMPLES, list)
        assert len(FEW_SHOT_EXAMPLES) >= 3  # At least 3 examples

    def test_few_shot_examples_structure(self):
        """Test that few-shot examples have correct structure."""
        from starboard_server.prompts.visualization.v1 import FEW_SHOT_EXAMPLES

        for example in FEW_SHOT_EXAMPLES:
            assert isinstance(example, dict)
            assert "input" in example
            assert "output" in example
            assert isinstance(example["input"], dict)
            assert isinstance(example["output"], dict)

    def test_few_shot_examples_cover_chart_types(self):
        """Test that few-shot examples cover multiple chart types."""
        from starboard_server.prompts.visualization.v1 import FEW_SHOT_EXAMPLES

        chart_types_covered = set()
        for example in FEW_SHOT_EXAMPLES:
            output = example.get("output", {})
            chart_config = output.get("chart_config", {})
            if chart_config:
                chart_type = chart_config.get("chart_type")
                if chart_type:
                    chart_types_covered.add(chart_type)

        # Should cover at least 3 different chart types
        assert len(chart_types_covered) >= 3

    def test_few_shot_examples_include_line_chart(self):
        """Test that examples include a line chart (common for timeseries)."""
        from starboard_server.prompts.visualization.v1 import FEW_SHOT_EXAMPLES

        has_line_chart = any(
            example.get("output", {}).get("chart_config", {}).get("chart_type")
            == "line"
            for example in FEW_SHOT_EXAMPLES
        )
        assert has_line_chart, "Should include at least one line chart example"

    def test_few_shot_examples_include_bar_chart(self):
        """Test that examples include a bar chart (common for categorical)."""
        from starboard_server.prompts.visualization.v1 import FEW_SHOT_EXAMPLES

        has_bar_chart = any(
            example.get("output", {}).get("chart_config", {}).get("chart_type") == "bar"
            for example in FEW_SHOT_EXAMPLES
        )
        assert has_bar_chart, "Should include at least one bar chart example"

    def test_build_prompt_function_exists(self):
        """Test that build_visualization_prompt function exists."""
        from starboard_server.prompts.visualization.v1 import (
            build_visualization_prompt,
        )

        assert callable(build_visualization_prompt)

    def test_build_prompt_with_metadata(self):
        """Test building prompt with query metadata."""
        from starboard_server.prompts.visualization.v1 import (
            build_visualization_prompt,
        )

        # Sample query metadata
        query_metadata = {
            "id": "test_query",
            "name": "Test Query",
            "description": "Test description",
            "recommended_chart_types": ["line", "area"],
            "goals": ["Show trends"],
        }

        # Sample data profile
        data_profile = {
            "row_count": 30,
            "columns": {
                "date": {"type": "Date"},
                "value": {"type": "Float64", "mean": 100.0},
            },
        }

        messages = build_visualization_prompt(query_metadata, data_profile)

        # Should return list of messages
        assert isinstance(messages, list)
        assert len(messages) >= 2  # At least system + user message

    def test_build_prompt_includes_system_message(self):
        """Test that built prompt includes system message."""
        from starboard_server.prompts.visualization.v1 import (
            build_visualization_prompt,
        )

        query_metadata = {"id": "test", "name": "Test"}
        data_profile = {"row_count": 10}

        messages = build_visualization_prompt(query_metadata, data_profile)

        # First message should be system message
        assert messages[0]["role"] == "system"
        assert len(messages[0]["content"]) > 50

    def test_build_prompt_includes_query_metadata(self):
        """Test that built prompt includes query metadata in user message."""
        from starboard_server.prompts.visualization.v1 import (
            build_visualization_prompt,
        )

        query_metadata = {
            "id": "test_query",
            "name": "Daily Cost Analysis",
            "description": "Analyze daily costs",
            "recommended_chart_types": ["line"],
            "goals": ["Show cost trends over time"],
        }
        data_profile = {"row_count": 30}

        messages = build_visualization_prompt(query_metadata, data_profile)

        # User message should include query name
        user_message = messages[1]["content"]
        assert (
            "Daily Cost Analysis" in user_message
            or "daily cost" in user_message.lower()
        )

    def test_build_prompt_includes_data_profile(self):
        """Test that built prompt includes data profile in user message."""
        from starboard_server.prompts.visualization.v1 import (
            build_visualization_prompt,
        )

        query_metadata = {"id": "test", "name": "Test"}
        data_profile = {
            "row_count": 42,
            "columns": {"timestamp": {"type": "Date"}, "cost": {"type": "Float64"}},
        }

        messages = build_visualization_prompt(query_metadata, data_profile)

        user_message = messages[1]["content"]
        # Should include row count
        assert "42" in user_message
        # Should include column names
        assert "timestamp" in user_message.lower() or "cost" in user_message.lower()

    def test_build_prompt_includes_recommended_charts(self):
        """Test that prompt includes recommended chart types from metadata."""
        from starboard_server.prompts.visualization.v1 import (
            build_visualization_prompt,
        )

        query_metadata = {
            "id": "test",
            "name": "Test",
            "recommended_chart_types": ["line", "area"],
        }
        data_profile = {"row_count": 10}

        messages = build_visualization_prompt(query_metadata, data_profile)

        # System or user message should mention recommended charts
        all_content = " ".join(msg["content"] for msg in messages)
        assert "line" in all_content.lower()

    def test_version_constant_exists(self):
        """Test that version constant exists with semantic versioning."""
        from starboard_server.prompts.visualization.v1 import PROMPT_VERSION

        # PROMPT_VERSION uses semantic versioning (1.0.0 format)
        assert PROMPT_VERSION == "1.0.0"


class TestPromptImports:
    """Test that prompts can be imported from package."""

    def test_import_from_package(self):
        """Test importing prompts from visualization package."""
        from starboard_server.prompts.visualization import v1

        assert hasattr(v1, "VISUALIZATION_SYSTEM_PROMPT")
        assert hasattr(v1, "FEW_SHOT_EXAMPLES")
        assert hasattr(v1, "build_visualization_prompt")


class TestPromptDocumentation:
    """Test that prompts have proper documentation."""

    def test_system_prompt_has_docstring(self):
        """Test that prompt module has docstring."""
        from starboard_server.prompts import visualization

        assert visualization.__doc__ is not None
        assert len(visualization.__doc__) > 20

    def test_build_function_has_docstring(self):
        """Test that build function has comprehensive docstring."""
        from starboard_server.prompts.visualization.v1 import (
            build_visualization_prompt,
        )

        assert build_visualization_prompt.__doc__ is not None
        assert "Args:" in build_visualization_prompt.__doc__
        assert "Returns:" in build_visualization_prompt.__doc__
