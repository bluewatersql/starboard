# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit Tests: BoundaryValidator

Tests for consolidated schema validation and repair at agent output boundary.
The validator performs ONE repair attempt, then marks as partial if still invalid.
"""

import pytest


class TestBoundaryValidatorRepairLogic:
    """Tests for report structure repair."""

    def test_unwraps_response_wrapper(self) -> None:
        """Unwraps OpenAI strict mode {response: {...}} wrapper."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        # OpenAI strict mode wraps in "response"
        raw = {
            "response": {
                "summary": {"overview": "Test"},
                "analysis": {"findings": []},
                "next_steps": [],
            }
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        assert "response" not in result.payload
        assert result.payload.get("summary", {}).get("overview") == "Test"
        assert "unwrap_response" in result.repairs_applied

    def test_unwraps_report_wrapper(self) -> None:
        """Unwraps {report: {...}} wrapper to root level."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "report": {
                "report_type": "advisor",
                "summary": {"overview": "Analysis"},
                "analysis": {"findings": []},
            },
            "next_steps": [],
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        assert "report" not in result.payload
        assert result.payload.get("summary", {}).get("overview") == "Analysis"
        assert result.payload.get("report_type") == "advisor"
        assert "unwrap_report" in result.repairs_applied

    def test_parses_json_string_report(self) -> None:
        """Parses report when it's a JSON string."""
        import json

        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        inner = {"summary": {"overview": "Parsed"}, "analysis": {"findings": []}}
        raw = {"report": json.dumps(inner)}

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        assert result.payload.get("summary", {}).get("overview") == "Parsed"
        assert "parse_json_report" in result.repairs_applied

    def test_fixes_summary_inside_analysis(self) -> None:
        """Moves summary from inside analysis to root level."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "analysis": {
                "summary": {"overview": "Misplaced"},
                "findings": [{"id": "1", "title": "Finding"}],
            },
            "next_steps": [],
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        # Summary should be at root
        assert result.payload.get("summary", {}).get("overview") == "Misplaced"
        # Analysis should no longer contain summary
        assert "summary" not in result.payload.get("analysis", {})
        assert "move_summary_to_root" in result.repairs_applied

    def test_unwraps_double_nested_analysis(self) -> None:
        """Fixes {analysis: {analysis: {...}}} double nesting."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "analysis": {
                "analysis": {"findings": [{"id": "1"}]},
                "summary": {"overview": "Nested"},
                "next_steps": [],
            }
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        # Inner analysis should be promoted
        assert "findings" in result.payload.get("analysis", {})
        # Summary should be at root (extracted from outer analysis)
        assert result.payload.get("summary", {}).get("overview") == "Nested"
        assert "unwrap_double_analysis" in result.repairs_applied

    def test_parses_json_string_analysis(self) -> None:
        """Parses analysis when it's a JSON string."""
        import json

        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "summary": {"overview": "Test"},
            "analysis": json.dumps({"findings": [{"id": "1"}]}),
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        assert isinstance(result.payload.get("analysis"), dict)
        assert "parse_json_analysis" in result.repairs_applied


class TestBoundaryValidatorValidReport:
    """Tests for already-valid report structures."""

    def test_valid_advisor_report_unchanged(self) -> None:
        """Valid advisor report passes through unchanged."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "report_type": "advisor",
            "summary": {"overview": "Analysis complete", "key_findings": []},
            "analysis": {"findings": [{"id": "1", "title": "Finding"}]},
            "next_steps": [{"id": "step_1", "title": "Continue"}],
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        assert result.is_valid
        assert len(result.repairs_applied) == 0
        assert result.payload == raw

    def test_valid_analytics_report_unchanged(self) -> None:
        """Valid analytics report passes through unchanged."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "report_type": "analytics",
            "summary": {"overview": "Cost analysis"},
            "data": {"values": [1, 2, 3]},
            "charts": [],
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="analytics")

        assert result.is_valid
        assert len(result.repairs_applied) == 0

    def test_valid_compute_report_unchanged(self) -> None:
        """Valid compute report passes through unchanged."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "report_type": "compute",
            "summary": {"overview": "Cluster analysis"},
            "cluster_info": {"name": "test-cluster"},
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="compute")

        assert result.is_valid
        assert len(result.repairs_applied) == 0


class TestBoundaryValidatorPartialResponses:
    """Tests for partial response handling."""

    def test_missing_summary_creates_partial(self) -> None:
        """Missing summary field results in partial response."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "report_type": "advisor",
            "analysis": {"findings": []},
            # Missing summary
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        assert result.is_partial
        assert "summary" in result.missing_fields

    def test_empty_payload_creates_partial(self) -> None:
        """Empty payload results in partial response."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        validator = BoundaryValidator()
        result = validator.validate_and_repair({}, domain="query")

        assert result.is_partial
        assert len(result.missing_fields) > 0

    def test_none_payload_creates_partial(self) -> None:
        """None payload results in partial response."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        validator = BoundaryValidator()
        result = validator.validate_and_repair(None, domain="query")

        assert result.is_partial
        assert result.payload == {}

    def test_unfixable_structure_creates_partial(self) -> None:
        """Malformed structure that can't be repaired creates partial."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "garbage": "data",
            "unrecognized": {"nested": "stuff"},
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        assert result.is_partial
        assert "summary" in result.missing_fields


class TestBoundaryValidatorReportTypeInference:
    """Tests for report_type field handling."""

    def test_preserves_existing_report_type(self) -> None:
        """Existing report_type is preserved."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "report_type": "analytics",
            "summary": {"overview": "Test"},
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        assert result.payload.get("report_type") == "analytics"

    def test_infers_report_type_from_domain(self) -> None:
        """Missing report_type is inferred from domain."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "summary": {"overview": "Test"},
            "analysis": {"findings": []},
        }

        validator = BoundaryValidator()

        # Query domain -> advisor
        result = validator.validate_and_repair(raw, domain="query")
        assert result.payload.get("report_type") == "advisor"

        # Analytics domain -> analytics
        result = validator.validate_and_repair(raw, domain="analytics")
        assert result.payload.get("report_type") == "analytics"

        # Warehouse domain -> compute
        result = validator.validate_and_repair(raw, domain="warehouse")
        assert result.payload.get("report_type") == "compute"


class TestBoundaryValidatorResult:
    """Tests for ValidationResult structure."""

    def test_result_contains_all_fields(self) -> None:
        """ValidationResult has all expected fields."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {"summary": {"overview": "Test"}}

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        assert hasattr(result, "is_valid")
        assert hasattr(result, "is_partial")
        assert hasattr(result, "payload")
        assert hasattr(result, "repairs_applied")
        assert hasattr(result, "missing_fields")
        assert hasattr(result, "validation_errors")

    def test_result_repairs_are_logged(self) -> None:
        """All applied repairs are recorded."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        # Structure that needs multiple repairs (unwrap_report + move_summary_to_root)
        raw = {
            "report": {
                "analysis": {
                    "summary": {"overview": "Nested in report and analysis"},
                    "findings": [],
                },
            }
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        # Should have multiple repairs (unwrap_report, move_summary_to_root, infer_report_type)
        assert len(result.repairs_applied) >= 2
        assert "unwrap_report" in result.repairs_applied


class TestBoundaryValidatorEdgeCases:
    """Edge case tests for BoundaryValidator."""

    def test_handles_non_dict_summary(self) -> None:
        """Handles summary as string instead of dict."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = {
            "summary": "Just a string overview",
            "analysis": {"findings": []},
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        # Should wrap string in proper structure
        assert isinstance(result.payload.get("summary"), dict)
        assert result.payload["summary"]["overview"] == "Just a string overview"

    def test_handles_list_at_root(self) -> None:
        """Handles list at root (should be dict)."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        raw = [{"finding": "1"}, {"finding": "2"}]

        validator = BoundaryValidator()
        # Should handle gracefully even though it's invalid
        result = validator.validate_and_repair(raw, domain="query")  # type: ignore

        assert result.is_partial

    def test_max_one_repair_pass(self) -> None:
        """Validator does ONE repair pass, not recursive."""
        from starboard_server.agents.output.boundary_validator import BoundaryValidator

        # Construct something that would need multiple recursive repairs
        raw = {
            "response": {
                "report": {
                    "analysis": {
                        "summary": {"overview": "Deep"},
                    }
                }
            }
        }

        validator = BoundaryValidator()
        result = validator.validate_and_repair(raw, domain="query")

        # Should make progress but may not fully fix deeply nested issues
        # The key is it doesn't hang or recurse infinitely
        assert isinstance(result.payload, dict)


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
