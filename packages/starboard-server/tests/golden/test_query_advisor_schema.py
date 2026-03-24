"""
Golden tests for optimizer advisor response schema.

These tests validate the structure and field requirements of the
optimizer advisor LLM response format (query, job, table, compute, diagnostic domains).
"""

import pytest
from starboard_core.domain.models.llm_schemas import (
    EffortEstimate,
    Finding,
    ImpactEstimate,
    OptimizerAdvisorReport,
)


class TestQueryAdvisorSchema:
    """Test query advisor response schema structure."""

    def test_finding_schema_required_fields(self):
        """Test Finding schema has all required fields."""
        schema = Finding.model_json_schema()

        assert "properties" in schema
        required_fields = [
            "id",
            "category",
            "title",
            "recommendation",
            "impact_estimate",
            "effort",
            "rank",
        ]

        for field in required_fields:
            assert field in schema["properties"], f"Missing field: {field}"

        assert "required" in schema
        for field in required_fields:
            assert field in schema["required"], f"Field not required: {field}"

    def test_impact_estimate_validation(self):
        """Test ImpactEstimate validation works correctly."""
        valid_impact = {
            "query_time_pct": -35.0,  # Negative means improvement
            "confidence": "high",
        }

        impact = ImpactEstimate.model_validate(valid_impact)
        assert impact.query_time_pct == -35.0
        assert impact.confidence == "high"
        assert impact.data_read_pct == 0.0  # Default value

    def test_impact_estimate_confidence_enum(self):
        """Test confidence must be one of allowed values."""
        from pydantic import ValidationError

        invalid_impact = {
            "query_time_pct": -20.0,
            "confidence": "very_high",  # Invalid value
        }

        with pytest.raises(ValidationError):
            ImpactEstimate.model_validate(invalid_impact)

    def test_effort_estimate_level_enum(self):
        """Test effort level must be one of allowed values."""
        from pydantic import ValidationError

        valid_effort = {"level": "medium", "estimate_hours": 4.0}
        effort = EffortEstimate.model_validate(valid_effort)
        assert effort.level == "medium"

        invalid_effort = {"level": "super_high"}
        with pytest.raises(ValidationError):
            EffortEstimate.model_validate(invalid_effort)

    def test_finding_validation_complete(self):
        """Test complete Finding validation with all fields."""
        valid_finding = {
            "id": "finding_001",
            "category": "QUERY",
            "title": "Missing predicate pushdown",
            "recommendation": "Add filter before join",
            "fixes": [
                {
                    "type": "SQL_REWRITE",
                    "snippet": "SELECT * FROM t WHERE id > 100",
                    "notes": "Apply filter early",
                }
            ],
            "impact_estimate": {
                "query_time_pct": -40.0,
                "confidence": "high",
            },
            "effort": {
                "level": "low",
                "estimate_hours": 1.0,
            },
            "risks": ["May change result ordering"],
            "rank": 1,
            "proofs": {  # Added required field
                "evidence": [],
                "code_line_refs": [],
                "references": [],
            },
        }

        finding = Finding.model_validate(valid_finding)
        assert finding.id == "finding_001"
        assert finding.category == "QUERY"
        assert len(finding.fixes) == 1
        assert finding.fixes[0].type == "SQL_REWRITE"
        assert finding.impact_estimate.confidence == "high"
        assert finding.effort.level == "low"
        assert finding.rank == 1

    def test_query_advisor_report_structure(self):
        """Test complete OptimizerAdvisorReport validation."""
        valid_report = {
            "summary": {
                "overview": "Query analysis complete",
                "current_state": {
                    "cloud_provider": "AWS",
                    "runtime_version": "13.3",
                    "warehouse_tier": "Pro",
                    "warehouse_size": "Medium",
                    "key_symptoms": ["High shuffle", "Long duration"],
                },
            },
            "analysis": {
                "findings": [
                    {
                        "id": "f1",
                        "category": "TABLE",
                        "title": "Missing statistics",
                        "recommendation": "Run ANALYZE TABLE",
                        "impact_estimate": {
                            "query_time_pct": -25.0,
                            "confidence": "medium",
                        },
                        "effort": {"level": "low"},
                        "rank": 1,
                        "proofs": {
                            "evidence": [],
                            "code_line_refs": [],
                            "references": [],
                        },
                    }
                ],
                "query_rewrite": {
                    "applicable": True,
                    "sql": "SELECT * FROM t WHERE filter",
                    "notes": "Optimized version",
                },
            },
            "next_steps": [
                {
                    "id": "step_1",
                    "number": 1,
                    "title": "Would you like me to analyze the...",
                    "description": "Would you like me to analyze the warehouse configuration for optimization opportunities?",
                    "action_type": "continue",
                }
            ],
        }

        report = OptimizerAdvisorReport.model_validate(valid_report)
        assert report.summary.overview == "Query analysis complete"
        assert report.summary.current_state.cloud_provider == "AWS"
        assert len(report.analysis.findings) == 1
        assert report.analysis.query_rewrite.applicable is True
        assert len(report.next_steps) == 1
