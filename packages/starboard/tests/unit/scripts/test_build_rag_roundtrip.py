# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Parse-roundtrip guard for scripts/build_rag_reference_files.py (D-g).

Cases:
  (a) well-formed input parses to the expected structured model
  (b) malformed input raises PackParseError with a clear message (no silent empty output)
  (c) roundtrip (render -> re-parse) is stable/lossless for a representative fixture
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Locate the scripts directory relative to this test file.
# Test lives at: packages/starboard/tests/unit/scripts/test_build_rag_roundtrip.py
# Repo root is 5 parents up from this file's parent directory.
_SCRIPTS_DIR = Path(__file__).resolve().parents[5] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import build_rag_reference_files as _brf  # noqa: E402
from starboard_core.rag.reference_loader import parse_domain_reference  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures (minimal, representative corpus-pack payloads)
# ---------------------------------------------------------------------------

_GOOD_NUANCE_DATA: dict = {
    "records": [
        {
            "id": "test_nuance_001",
            "document": "Use SUM(usage_quantity) only when usage_unit is homogeneous.",
            "metadata": {
                "domain": "finops_billing",
                "topic_id": "usage_unit_semantics",
                "doc_type": "rule",
            },
        }
    ]
}

_GOOD_CODEBOOK_DATA: dict = {
    "records": [
        {
            "id": "test_cb_001",
            "document": "Cloud provider for the usage row.",
            "metadata": {
                "domain": "finops_billing",
                "code_key": "system.billing.usage.cloud",
                "values_csv": "AWS,AZURE,GCP",
            },
        }
    ]
}


# ---------------------------------------------------------------------------
# Case (a): well-formed input → expected structured model
# ---------------------------------------------------------------------------


class TestParseWellFormed:
    def test_nuance_record_fields(self) -> None:
        records = _brf._parse_nuance_records(_GOOD_NUANCE_DATA, source="test")
        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, _brf.NuanceRecord)
        assert rec.id == "test_nuance_001"
        assert rec.domain == "finops_billing"
        assert rec.topic_id == "usage_unit_semantics"
        assert rec.doc_type == "rule"
        assert "SUM(usage_quantity)" in rec.document

    def test_codebook_record_fields(self) -> None:
        records = _brf._parse_codebook_records(_GOOD_CODEBOOK_DATA, source="test")
        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, _brf.CodebookRecord)
        assert rec.id == "test_cb_001"
        assert rec.domain == "finops_billing"
        assert rec.code_key == "system.billing.usage.cloud"
        assert rec.values_csv == "AWS,AZURE,GCP"
        assert "Cloud provider" in rec.document

    def test_nuance_optional_fields_default_when_absent(self) -> None:
        """topic_id falls back to id; doc_type falls back to 'nuance'."""
        data = {
            "records": [
                {
                    "id": "bare_001",
                    "document": "Some content.",
                    "metadata": {"domain": "compute_warehouses"},
                }
            ]
        }
        records = _brf._parse_nuance_records(data, source="test")
        assert len(records) == 1
        assert records[0].topic_id == "bare_001"
        assert records[0].doc_type == "nuance"

    def test_codebook_values_csv_is_optional(self) -> None:
        """values_csv absent → None (no error)."""
        data = {
            "records": [
                {
                    "id": "cb_bare",
                    "document": "A codebook entry without values.",
                    "metadata": {
                        "domain": "compute_warehouses",
                        "code_key": "some.field",
                    },
                }
            ]
        }
        records = _brf._parse_codebook_records(data, source="test")
        assert records[0].values_csv is None

    def test_multiple_records_all_returned(self) -> None:
        data = {
            "records": [
                {
                    "id": f"rec_{i}",
                    "document": f"Content {i}.",
                    "metadata": {"domain": "finops_billing", "topic_id": f"t{i}", "doc_type": "rule"},
                }
                for i in range(5)
            ]
        }
        records = _brf._parse_nuance_records(data, source="test")
        assert len(records) == 5


# ---------------------------------------------------------------------------
# Case (b): malformed input → PackParseError, no silent empty output
# ---------------------------------------------------------------------------


class TestParseMalformed:
    # --- top-level shape errors ---

    @pytest.mark.parametrize(
        "bad_data,match",
        [
            ([], "JSON object"),
            ("a string", "JSON object"),
            (None, "JSON object"),
            ({"items": []}, "'records'"),
            ({"records": {}}, "list"),
            ({"records": "oops"}, "list"),
        ],
    )
    def test_nuance_top_level_errors(self, bad_data: object, match: str) -> None:
        with pytest.raises(_brf.PackParseError, match=match):
            _brf._parse_nuance_records(bad_data, source="nuance_pack.json")

    @pytest.mark.parametrize(
        "bad_data,match",
        [
            ([], "JSON object"),
            ({"items": []}, "'records'"),
            ({"records": {}}, "list"),
        ],
    )
    def test_codebook_top_level_errors(self, bad_data: object, match: str) -> None:
        with pytest.raises(_brf.PackParseError, match=match):
            _brf._parse_codebook_records(bad_data, source="codebook_pack.json")

    # --- per-record errors ---

    def test_nuance_missing_id(self) -> None:
        data = {"records": [{"document": "x", "metadata": {"domain": "finops_billing"}}]}
        with pytest.raises(_brf.PackParseError, match="'id'"):
            _brf._parse_nuance_records(data, source="test")

    def test_nuance_empty_id(self) -> None:
        data = {"records": [{"id": "", "document": "x", "metadata": {"domain": "finops_billing"}}]}
        with pytest.raises(_brf.PackParseError, match="'id'"):
            _brf._parse_nuance_records(data, source="test")

    def test_nuance_missing_document(self) -> None:
        data = {"records": [{"id": "x", "metadata": {"domain": "finops_billing"}}]}
        with pytest.raises(_brf.PackParseError, match="'document'"):
            _brf._parse_nuance_records(data, source="test")

    def test_nuance_empty_document(self) -> None:
        data = {"records": [{"id": "x", "document": "", "metadata": {"domain": "finops_billing"}}]}
        with pytest.raises(_brf.PackParseError, match="'document'"):
            _brf._parse_nuance_records(data, source="test")

    def test_nuance_missing_metadata(self) -> None:
        data = {"records": [{"id": "x", "document": "y"}]}
        with pytest.raises(_brf.PackParseError, match="'metadata'"):
            _brf._parse_nuance_records(data, source="test")

    def test_nuance_metadata_not_dict(self) -> None:
        data = {"records": [{"id": "x", "document": "y", "metadata": "bad"}]}
        with pytest.raises(_brf.PackParseError, match="'metadata'"):
            _brf._parse_nuance_records(data, source="test")

    def test_nuance_missing_domain(self) -> None:
        data = {"records": [{"id": "x", "document": "y", "metadata": {"doc_type": "rule"}}]}
        with pytest.raises(_brf.PackParseError, match="domain"):
            _brf._parse_nuance_records(data, source="test")

    def test_nuance_empty_domain(self) -> None:
        data = {"records": [{"id": "x", "document": "y", "metadata": {"domain": ""}}]}
        with pytest.raises(_brf.PackParseError, match="domain"):
            _brf._parse_nuance_records(data, source="test")

    def test_codebook_missing_code_key(self) -> None:
        data = {
            "records": [{"id": "x", "document": "y", "metadata": {"domain": "finops_billing"}}]
        }
        with pytest.raises(_brf.PackParseError, match="code_key"):
            _brf._parse_codebook_records(data, source="test")

    def test_codebook_empty_code_key(self) -> None:
        data = {
            "records": [
                {"id": "x", "document": "y", "metadata": {"domain": "finops_billing", "code_key": ""}}
            ]
        }
        with pytest.raises(_brf.PackParseError, match="code_key"):
            _brf._parse_codebook_records(data, source="test")

    def test_packparseerror_is_valueerror_subclass(self) -> None:
        """PackParseError must be a ValueError so callers can use broad except clauses."""
        with pytest.raises(ValueError):
            _brf._parse_nuance_records([], source="test")

    def test_error_message_includes_record_index(self) -> None:
        """Error context must identify which record index triggered the failure."""
        data = {
            "records": [
                {"id": "ok", "document": "fine", "metadata": {"domain": "finops_billing"}},
                # second record is malformed
                {"id": "bad", "document": "", "metadata": {"domain": "finops_billing"}},
            ]
        }
        with pytest.raises(_brf.PackParseError, match=r"\[1\]"):
            _brf._parse_nuance_records(data, source="my_file.json")


# ---------------------------------------------------------------------------
# Case (c): roundtrip (render → re-parse) is stable/lossless
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_tables_survive_roundtrip(self) -> None:
        """Tables rendered by _render_domain_md survive parse_domain_reference."""
        tables = ["system.billing.usage", "system.billing.list_prices"]
        md = _brf._render_domain_md("finops_billing", tables, [], [])
        ref = parse_domain_reference(md)

        assert ref.domain == "finops_billing"
        assert set(ref.system_tables) == set(tables)
        table_headers = {e.header for e in ref.sections.get("Tables", ())}
        assert table_headers == set(tables)

    def test_nuance_entry_survives_roundtrip(self) -> None:
        """Nuance entries round-trip with header (topic_id | doc_type) and body intact."""
        nuances = [
            _brf.NuanceRecord(
                id="n1",
                document="Always filter by workspace_id to reduce scan costs.",
                domain="finops_billing",
                topic_id="workspace_filter",
                doc_type="rule",
            )
        ]
        md = _brf._render_domain_md("finops_billing", [], nuances, [])
        ref = parse_domain_reference(md)

        entries = ref.sections.get("Nuance", ())
        assert len(entries) == 1
        assert entries[0].header == "workspace_filter | rule"
        assert "workspace_id" in entries[0].body

    def test_codebook_entry_survives_roundtrip(self) -> None:
        """Codebook entries round-trip with code_key as header."""
        codebooks = [
            _brf.CodebookRecord(
                id="cb1",
                document="Cloud provider for the usage row.",
                domain="finops_billing",
                code_key="system.billing.usage.cloud",
                values_csv="AWS,AZURE,GCP",
            )
        ]
        md = _brf._render_domain_md("finops_billing", [], [], codebooks)
        ref = parse_domain_reference(md)

        cb_entries = ref.sections.get("Codebook", ())
        assert len(cb_entries) == 1
        assert cb_entries[0].header == "system.billing.usage.cloud"

    def test_facets_from_values_csv_survive_roundtrip(self) -> None:
        """values_csv is rendered in the Facets section and survives round-trip."""
        codebooks = [
            _brf.CodebookRecord(
                id="cb1",
                document="Cloud provider.",
                domain="finops_billing",
                code_key="system.billing.usage.cloud",
                values_csv="AWS,AZURE,GCP",
            )
        ]
        md = _brf._render_domain_md("finops_billing", [], [], codebooks)
        ref = parse_domain_reference(md)

        facet_entries = ref.sections.get("Facets", ())
        assert len(facet_entries) == 1
        assert facet_entries[0].header == "system.billing.usage.cloud"
        # The loader splits on commas; all three values must be present.
        assert "AWS" in facet_entries[0].body
        assert "AZURE" in facet_entries[0].body
        assert "GCP" in facet_entries[0].body

    def test_codebook_without_values_csv_produces_no_facet_entry(self) -> None:
        """Codebook entry with values_csv=None must not appear in Facets section."""
        codebooks = [
            _brf.CodebookRecord(
                id="cb1",
                document="No facets here.",
                domain="finops_billing",
                code_key="some.key",
                values_csv=None,
            )
        ]
        md = _brf._render_domain_md("finops_billing", [], [], codebooks)
        ref = parse_domain_reference(md)
        # Facets section exists but has no real entries (only the placeholder line).
        facets = ref.sections.get("Facets", ())
        # The placeholder text is not a ### entry so no entries should parse.
        assert len(facets) == 0

    def test_render_is_idempotent(self) -> None:
        """Rendering the same data twice yields identical Markdown."""
        nuances = [
            _brf.NuanceRecord(
                id="n1",
                document="Content.",
                domain="finops_billing",
                topic_id="topic_a",
                doc_type="rule",
            )
        ]
        codebooks = [
            _brf.CodebookRecord(
                id="cb1",
                document="Codebook.",
                domain="finops_billing",
                code_key="some.key",
                values_csv="A,B",
            )
        ]
        tables = ["system.billing.usage"]
        md1 = _brf._render_domain_md("finops_billing", tables, nuances, codebooks)
        md2 = _brf._render_domain_md("finops_billing", tables, nuances, codebooks)
        assert md1 == md2

    def test_full_parse_then_render_matches_original(self) -> None:
        """Round-trip from raw pack data → render → parse produces consistent structure."""
        nuance_records = _brf._parse_nuance_records(_GOOD_NUANCE_DATA, source="test")
        codebook_records = _brf._parse_codebook_records(_GOOD_CODEBOOK_DATA, source="test")

        md = _brf._render_domain_md(
            "finops_billing",
            ["system.billing.usage"],
            nuance_records,
            codebook_records,
        )
        ref = parse_domain_reference(md)

        assert ref.domain == "finops_billing"
        assert "system.billing.usage" in ref.system_tables
        nuance_entries = ref.sections.get("Nuance", ())
        assert any("usage_unit_semantics" in e.header for e in nuance_entries)
        codebook_entries = ref.sections.get("Codebook", ())
        assert any("system.billing.usage.cloud" in e.header for e in codebook_entries)
