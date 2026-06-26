# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the user_input_policy shared prompt module.

This module tests the date interpretation policy, parameter defaults,
and user input guidelines that should be used consistently across all agents.
"""


class TestDatePolicy:
    """Tests for the DATE_POLICY constant."""

    def test_date_policy_exists(self) -> None:
        """DATE_POLICY should be importable."""
        from starboard_server.prompts.shared.user_input_policy import DATE_POLICY

        assert DATE_POLICY is not None
        assert isinstance(DATE_POLICY, str)

    def test_date_policy_contains_30_day_default(self) -> None:
        """DATE_POLICY should specify 30-day rolling window."""
        from starboard_server.prompts.shared.user_input_policy import DATE_POLICY

        assert "30" in DATE_POLICY
        assert "day" in DATE_POLICY.lower()

    def test_date_policy_covers_common_phrases(self) -> None:
        """DATE_POLICY should cover common date phrases."""
        from starboard_server.prompts.shared.user_input_policy import DATE_POLICY

        policy_lower = DATE_POLICY.lower()
        assert "last month" in policy_lower
        assert "past month" in policy_lower
        assert "recently" in policy_lower

    def test_date_policy_forbids_clarification(self) -> None:
        """DATE_POLICY should explicitly forbid asking for date clarification."""
        from starboard_server.prompts.shared.user_input_policy import DATE_POLICY

        policy_lower = DATE_POLICY.lower()
        assert "never ask" in policy_lower


class TestParameterDefaults:
    """Tests for the PARAMETER_DEFAULTS constant."""

    def test_parameter_defaults_exists(self) -> None:
        """PARAMETER_DEFAULTS should be importable."""
        from starboard_server.prompts.shared.user_input_policy import (
            PARAMETER_DEFAULTS,
        )

        assert PARAMETER_DEFAULTS is not None
        assert isinstance(PARAMETER_DEFAULTS, str)

    def test_parameter_defaults_has_start_date(self) -> None:
        """PARAMETER_DEFAULTS should specify start_date default."""
        from starboard_server.prompts.shared.user_input_policy import (
            PARAMETER_DEFAULTS,
        )

        assert "start_date" in PARAMETER_DEFAULTS

    def test_parameter_defaults_has_end_date(self) -> None:
        """PARAMETER_DEFAULTS should specify end_date default."""
        from starboard_server.prompts.shared.user_input_policy import (
            PARAMETER_DEFAULTS,
        )

        assert "end_date" in PARAMETER_DEFAULTS

    def test_parameter_defaults_has_limit(self) -> None:
        """PARAMETER_DEFAULTS should specify limit default."""
        from starboard_server.prompts.shared.user_input_policy import (
            PARAMETER_DEFAULTS,
        )

        assert "limit" in PARAMETER_DEFAULTS


class TestUserInputPolicy:
    """Tests for the USER_INPUT_POLICY constant."""

    def test_user_input_policy_exists(self) -> None:
        """USER_INPUT_POLICY should be importable."""
        from starboard_server.prompts.shared.user_input_policy import USER_INPUT_POLICY

        assert USER_INPUT_POLICY is not None
        assert isinstance(USER_INPUT_POLICY, str)

    def test_user_input_policy_specifies_when_to_ask(self) -> None:
        """USER_INPUT_POLICY should specify when to ask for input."""
        from starboard_server.prompts.shared.user_input_policy import USER_INPUT_POLICY

        policy_lower = USER_INPUT_POLICY.lower()
        # Should mention required IDs as valid reason to ask
        assert "required" in policy_lower or "missing" in policy_lower

    def test_user_input_policy_mentions_id_parameters(self) -> None:
        """USER_INPUT_POLICY should mention ID parameters."""
        from starboard_server.prompts.shared.user_input_policy import USER_INPUT_POLICY

        # Should mention at least one ID type
        assert any(
            id_type in USER_INPUT_POLICY
            for id_type in ["job_id", "warehouse_id", "cluster_id", "statement_id"]
        )


class TestCombinedSection:
    """Tests for the combined USER_INPUT_POLICY_SECTION."""

    def test_combined_section_exists(self) -> None:
        """USER_INPUT_POLICY_SECTION should be importable."""
        from starboard_server.prompts.shared.user_input_policy import (
            USER_INPUT_POLICY_SECTION,
        )

        assert USER_INPUT_POLICY_SECTION is not None
        assert isinstance(USER_INPUT_POLICY_SECTION, str)

    def test_combined_section_contains_all_parts(self) -> None:
        """USER_INPUT_POLICY_SECTION should contain all sub-sections."""
        from starboard_server.prompts.shared.user_input_policy import (
            USER_INPUT_POLICY_SECTION,
        )

        # Combined section should include content from all parts
        assert "30" in USER_INPUT_POLICY_SECTION  # From DATE_POLICY
        assert "start_date" in USER_INPUT_POLICY_SECTION  # From PARAMETER_DEFAULTS


class TestBuilderFunction:
    """Tests for the build_user_input_policy_section function."""

    def test_builder_function_exists(self) -> None:
        """build_user_input_policy_section should be importable."""
        from starboard_server.prompts.shared.user_input_policy import (
            build_user_input_policy_section,
        )

        assert callable(build_user_input_policy_section)

    def test_builder_returns_string(self) -> None:
        """build_user_input_policy_section should return a string."""
        from starboard_server.prompts.shared.user_input_policy import (
            build_user_input_policy_section,
        )

        result = build_user_input_policy_section()
        assert isinstance(result, str)

    def test_builder_default_includes_defaults(self) -> None:
        """build_user_input_policy_section() should include parameter defaults."""
        from starboard_server.prompts.shared.user_input_policy import (
            build_user_input_policy_section,
        )

        result = build_user_input_policy_section()
        assert "start_date" in result

    def test_builder_can_exclude_defaults(self) -> None:
        """build_user_input_policy_section(include_defaults=False) should exclude defaults."""
        from starboard_server.prompts.shared.user_input_policy import (
            build_user_input_policy_section,
        )

        result = build_user_input_policy_section(include_defaults=False)
        # Should still have date policy but not the defaults section header
        assert "30" in result  # Date policy reference
        assert "PARAMETER DEFAULTS" not in result


class TestModuleExports:
    """Tests for module-level exports."""

    def test_all_exports_defined(self) -> None:
        """Module should define __all__ with expected exports."""
        from starboard_server.prompts.shared import user_input_policy

        expected_exports = {
            "DATE_POLICY",
            "PARAMETER_DEFAULTS",
            "USER_INPUT_POLICY",
            "USER_INPUT_POLICY_SECTION",
            "build_user_input_policy_section",
        }
        assert hasattr(user_input_policy, "__all__")
        assert set(user_input_policy.__all__) == expected_exports

    def test_importable_from_shared_package(self) -> None:
        """Exports should be importable from shared package."""
        from starboard_server.prompts.shared import (
            USER_INPUT_POLICY_SECTION,
            build_user_input_policy_section,
        )

        assert USER_INPUT_POLICY_SECTION is not None
        assert callable(build_user_input_policy_section)
