"""Tests for LLM schema Pydantic models.

Tests cover:
- Model validation (required fields, types)
- Field defaults and optional fields
- Serialization/deserialization
- Edge cases (empty lists, None values)
"""

import pytest
from pydantic import ValidationError
from starboard_core.domain.models.llm_schemas import (
    CodeHotspot,
    CriticVerdict,
    EffortEstimate,
    Finding,
    ImpactEstimate,
    InputClassification,
    OptimizationPlan,
    PlanIntent,
    Proofs,
    TableExtraction,
    TableReference,
)


class TestPlanIntent:
    """Tests for PlanIntent model."""

    def test_valid_plan_intent(self):
        """Test creating valid PlanIntent."""
        intent = PlanIntent(intent="optimize_table", reason="Table is fragmented")

        assert intent.intent == "optimize_table"
        assert intent.reason == "Table is fragmented"

    def test_plan_intent_default_reason(self):
        """Test default reason is empty string."""
        intent = PlanIntent(intent="analyze")

        assert intent.intent == "analyze"
        assert intent.reason == ""

    def test_plan_intent_requires_intent(self):
        """Test that intent field is required."""
        with pytest.raises(ValidationError):
            PlanIntent(reason="Test")


class TestInputClassification:
    """Tests for InputClassification model."""

    def test_valid_input_classification(self):
        """Test creating valid InputClassification."""
        classification = InputClassification(
            input_type="job_id",
            target="job_123",
            confidence="high",
            reasoning="Matches job ID pattern",
        )

        assert classification.input_type == "job_id"
        assert classification.target == "job_123"
        assert classification.confidence == "high"
        assert classification.reasoning == "Matches job ID pattern"

    def test_input_classification_sql_type(self):
        """Test classification with SQL input type."""
        classification = InputClassification(
            input_type="sql",
            target="SELECT * FROM table",
            confidence="medium",
            reasoning="Contains SQL keywords",
        )

        assert classification.input_type == "sql"
        assert classification.target == "SELECT * FROM table"

    def test_input_classification_invalid_type(self):
        """Test that invalid input_type is rejected."""
        with pytest.raises(ValidationError):
            InputClassification(
                input_type="invalid_type",
                target="test",
                confidence="high",
                reasoning="Test",
            )

    def test_input_classification_invalid_confidence(self):
        """Test that invalid confidence is rejected."""
        with pytest.raises(ValidationError):
            InputClassification(
                input_type="sql",
                target="SELECT *",
                confidence="very_high",
                reasoning="Test",
            )


class TestOptimizationPlan:
    """Tests for OptimizationPlan model."""

    def test_valid_optimization_plan(self):
        """Test creating valid OptimizationPlan."""
        plan = OptimizationPlan(
            goal="Improve query performance",
            mode="query",
            input_classification=InputClassification(
                input_type="sql",
                target="SELECT * FROM table",
                confidence="high",
                reasoning="SQL detected",
            ),
            intents=[
                PlanIntent(intent="analyze_query", reason="Check execution plan"),
                PlanIntent(intent="optimize_table"),
            ],
        )

        assert plan.goal == "Improve query performance"
        assert plan.mode == "query"
        assert len(plan.intents) == 2
        assert plan.intents[0].intent == "analyze_query"

    def test_optimization_plan_empty_intents(self):
        """Test plan with empty intents list."""
        plan = OptimizationPlan(
            goal="Test",
            mode="test",
            input_classification=InputClassification(
                input_type="undetermined",
                target="test",
                confidence="low",
                reasoning="Unknown",
            ),
            intents=[],
        )

        assert plan.intents == []

    def test_optimization_plan_requires_all_fields(self):
        """Test that all required fields must be provided."""
        with pytest.raises(ValidationError):
            OptimizationPlan(goal="Test", mode="test")


class TestCriticVerdict:
    """Tests for CriticVerdict model."""

    def test_critic_verdict_ok(self):
        """Test verdict with ok status."""
        verdict = CriticVerdict(status="ok", reason="Plan looks good")

        assert verdict.status == "ok"
        assert verdict.reason == "Plan looks good"
        assert verdict.revised_intents is None

    def test_critic_verdict_revise_with_intents(self):
        """Test verdict with revise status and revised intents."""
        verdict = CriticVerdict(
            status="revise",
            reason="Need more analysis",
            revised_intents=[
                PlanIntent(intent="analyze_more", reason="Additional check needed")
            ],
        )

        assert verdict.status == "revise"
        assert len(verdict.revised_intents) == 1
        assert verdict.revised_intents[0].intent == "analyze_more"

    def test_critic_verdict_reject(self):
        """Test verdict with reject status."""
        verdict = CriticVerdict(status="reject", reason="Plan is infeasible")

        assert verdict.status == "reject"
        assert verdict.revised_intents is None

    def test_critic_verdict_invalid_status(self):
        """Test that invalid status is rejected."""
        with pytest.raises(ValidationError):
            CriticVerdict(status="maybe", reason="Not sure")


class TestTableReference:
    """Tests for TableReference model."""

    def test_valid_table_reference(self):
        """Test creating valid TableReference."""
        table = TableReference(
            raw="catalog.schema.table",
            catalog="catalog",
            schema_name="schema",
            table="table",
            type="table",
            is_source=True,
        )

        assert table.raw == "catalog.schema.table"
        assert table.catalog == "catalog"
        assert table.schema_name == "schema"
        assert table.table == "table"
        assert table.is_source is True
        assert table.is_destination is False

    def test_table_reference_minimal(self):
        """Test TableReference with minimal required fields."""
        table = TableReference(raw="my_table", table="my_table")

        assert table.raw == "my_table"
        assert table.table == "my_table"
        assert table.catalog is None
        assert table.schema_name is None
        assert table.type == "table"
        assert table.is_source is False

    def test_table_reference_temp_view(self):
        """Test TableReference for temp view."""
        table = TableReference(
            raw="temp_view", table="temp_view", type="temp_view", is_destination=True
        )

        assert table.type == "temp_view"
        assert table.is_destination is True

    def test_table_reference_schema_alias(self):
        """Test that 'schema' alias works for schema_name."""
        table = TableReference(raw="table", table="table", schema="my_schema")

        assert table.schema_name == "my_schema"


class TestTableExtraction:
    """Tests for TableExtraction model."""

    def test_valid_table_extraction(self):
        """Test creating valid TableExtraction."""
        extraction = TableExtraction(
            language="SQL",
            tables=[
                TableReference(raw="table1", table="table1"),
                TableReference(raw="table2", table="table2", is_source=True),
            ],
        )

        assert extraction.language == "SQL"
        assert len(extraction.tables) == 2
        assert extraction.tables[1].is_source is True

    def test_table_extraction_empty_tables(self):
        """Test extraction with no tables."""
        extraction = TableExtraction(language="Python", tables=[])

        assert extraction.language == "Python"
        assert extraction.tables == []

    def test_table_extraction_requires_fields(self):
        """Test that all required fields must be provided."""
        with pytest.raises(ValidationError):
            TableExtraction(language="SQL")


class TestCodeHotspot:
    """Tests for CodeHotspot model."""

    def test_valid_code_hotspot(self):
        """Test creating valid CodeHotspot."""
        hotspot = CodeHotspot(
            artifact="query.sql",
            line_range="10-15",
            issue="Inefficient JOIN",
            signal=["Full table scan", "High memory usage"],
            evidence="Execution plan shows scan",
            risk="high",
            fix_strategy="Add index on join column",
            snippet_before="SELECT * FROM large_table",
            snippet_after="SELECT id, name FROM large_table WHERE indexed_col = ?",
        )

        assert hotspot.artifact == "query.sql"
        assert hotspot.line_range == "10-15"
        assert hotspot.risk == "high"
        assert len(hotspot.signal) == 2

    def test_code_hotspot_defaults(self):
        """Test CodeHotspot default values."""
        hotspot = CodeHotspot(
            artifact="file.py", issue="Performance issue", fix_strategy="Optimize loop"
        )

        assert hotspot.line_range == ""
        assert hotspot.signal == []
        assert hotspot.evidence == ""
        assert hotspot.risk == "medium"
        assert hotspot.snippet_before == ""
        assert hotspot.snippet_after == ""

    def test_code_hotspot_requires_core_fields(self):
        """Test that core fields are required."""
        with pytest.raises(ValidationError):
            CodeHotspot(artifact="file.py", issue="Problem")


class TestFinding:
    """Tests for Finding model with all category types."""

    def _make_finding(self, category: str) -> Finding:
        """Helper to create a valid Finding with specified category."""
        return Finding(
            id=f"finding_{category.lower()}_001",
            category=category,
            title=f"Test {category} finding",
            recommendation=f"Fix the {category} issue",
            proofs=Proofs(evidence=["Evidence 1"]),
            impact_estimate=ImpactEstimate(
                query_time_pct=-20.0,
                confidence="medium",
            ),
            effort=EffortEstimate(level="low"),
            rank=1,
        )

    def test_finding_query_category(self):
        """Test Finding with QUERY category."""
        finding = self._make_finding("QUERY")
        assert finding.category == "QUERY"
        assert finding.id == "finding_query_001"

    def test_finding_table_category(self):
        """Test Finding with TABLE category."""
        finding = self._make_finding("TABLE")
        assert finding.category == "TABLE"

    def test_finding_warehouse_category(self):
        """Test Finding with WAREHOUSE category."""
        finding = self._make_finding("WAREHOUSE")
        assert finding.category == "WAREHOUSE"

    def test_finding_schema_category(self):
        """Test Finding with SCHEMA category."""
        finding = self._make_finding("SCHEMA")
        assert finding.category == "SCHEMA"

    # UC-specific categories
    def test_finding_lineage_category(self):
        """Test Finding with UC-specific LINEAGE category."""
        finding = self._make_finding("LINEAGE")
        assert finding.category == "LINEAGE"

    def test_finding_policy_category(self):
        """Test Finding with UC-specific POLICY category."""
        finding = self._make_finding("POLICY")
        assert finding.category == "POLICY"

    def test_finding_storage_category(self):
        """Test Finding with UC-specific STORAGE category."""
        finding = self._make_finding("STORAGE")
        assert finding.category == "STORAGE"

    def test_finding_invalid_category_rejected(self):
        """Test that invalid category is rejected."""
        with pytest.raises(ValidationError):
            Finding(
                id="finding_001",
                category="INVALID_CATEGORY",
                title="Test",
                recommendation="Test",
                proofs=Proofs(evidence=[]),
                impact_estimate=ImpactEstimate(query_time_pct=0, confidence="low"),
                effort=EffortEstimate(level="low"),
                rank=1,
            )

    def test_finding_all_valid_categories(self):
        """Test all valid categories are accepted."""
        valid_categories = [
            "QUERY",
            "TABLE",
            "WAREHOUSE",
            "JOB_CONFIG",
            "CODE",
            "CLUSTER",
            "DATA",
            "RUNTIME",
            "SCHEMA",
            "RESOURCE",
            # UC-specific categories
            "LINEAGE",
            "POLICY",
            "STORAGE",
        ]
        for category in valid_categories:
            finding = self._make_finding(category)
            assert finding.category == category

    def test_finding_serialization(self):
        """Test Finding can be serialized and deserialized."""
        finding = self._make_finding("LINEAGE")

        # Serialize
        data = finding.model_dump()
        assert data["category"] == "LINEAGE"
        assert data["id"] == "finding_lineage_001"

        # Deserialize
        new_finding = Finding(**data)
        assert new_finding.category == finding.category
        assert new_finding.id == finding.id


class TestModelSerialization:
    """Tests for model serialization/deserialization."""

    def test_plan_intent_serialization(self):
        """Test PlanIntent can be serialized and deserialized."""
        intent = PlanIntent(intent="test", reason="test reason")

        # Serialize
        data = intent.model_dump()
        assert data == {"intent": "test", "reason": "test reason"}

        # Deserialize
        new_intent = PlanIntent(**data)
        assert new_intent.intent == intent.intent
        assert new_intent.reason == intent.reason

    def test_optimization_plan_json(self):
        """Test OptimizationPlan JSON serialization."""
        plan = OptimizationPlan(
            goal="Test",
            mode="test",
            input_classification=InputClassification(
                input_type="sql",
                target="SELECT *",
                confidence="high",
                reasoning="Test",
            ),
            intents=[PlanIntent(intent="analyze")],
        )

        # To JSON and back
        json_str = plan.model_dump_json()
        assert "Test" in json_str
        assert "analyze" in json_str

        # Parse back
        new_plan = OptimizationPlan.model_validate_json(json_str)
        assert new_plan.goal == plan.goal
        assert new_plan.intents[0].intent == "analyze"
