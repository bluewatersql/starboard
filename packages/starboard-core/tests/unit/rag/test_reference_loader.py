# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the embedding-free RAG reference loader (Phase 2 C1).

Covers:
- reference files exist for every RagResourceDomain (parametric completeness)
- each file parses (front-matter + sections) into a populated RAGContext
- unknown/missing domains degrade to an empty context (no crash)
- the default path imports/loads with NO vector driver in sys.modules
- governance: no internal namespaces leak into shipped knowledge files
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from starboard_core.rag import reference_loader as rl
from starboard_core.rag.models import RAGContext
from starboard_core.rag.resource_domains import RagResourceDomain

ALL_DOMAINS = [d.value for d in RagResourceDomain]


class TestCompleteness:
    def test_every_domain_has_a_reference_file(self):
        available = set(rl.available_domains())
        missing = set(ALL_DOMAINS) - available
        assert not missing, f"missing reference files for domains: {sorted(missing)}"

    @pytest.mark.parametrize("domain", ALL_DOMAINS)
    def test_each_file_parses_front_matter_and_sections(self, domain):
        ref = rl.load_domain_reference(domain)
        assert ref is not None, f"{domain}.md not found"
        # front-matter names the domain
        assert ref.domain == domain
        # canonical sections are all present as parsed sections
        for section in ("Tables", "Nuance", "Codebook", "Facets"):
            assert section in ref.sections, f"{domain}: missing section {section}"


class TestLoadDomainReferences:
    def test_populated_context_from_disk(self):
        ctx = rl.load_domain_references(["finops_billing"])
        assert isinstance(ctx, RAGContext)
        # finops_billing is the richest domain in the corpus
        assert ctx.tables, "expected tables from reference file"
        assert ctx.nuance, "expected nuance from reference file"
        assert ctx.codebook, "expected codebook from reference file"
        assert ctx.facets, "expected facets from reference file"
        # domain is stamped on every record
        assert all(t.domain == "finops_billing" for t in ctx.tables)
        assert all(n.domain == "finops_billing" for n in ctx.nuance)

    def test_multiple_domains_are_merged(self):
        one = rl.load_domain_references(["finops_billing"])
        two = rl.load_domain_references(["finops_billing", "compute_warehouses"])
        assert len(two.tables) >= len(one.tables)
        assert len(two.nuance) >= len(one.nuance)

    def test_section_filter_restricts_output(self):
        ctx = rl.load_domain_references(["finops_billing"], sections=["Tables"])
        assert ctx.tables
        assert ctx.nuance == []
        assert ctx.codebook == []
        assert ctx.facets == []

    def test_none_domains_yields_empty_context(self):
        assert rl.load_domain_references(None) == RAGContext()
        assert rl.load_domain_references([]) == RAGContext()

    def test_duplicate_domains_deduplicated(self):
        once = rl.load_domain_references(["finops_billing"])
        twice = rl.load_domain_references(["finops_billing", "finops_billing"])
        assert len(twice.tables) == len(once.tables)

    def test_facet_values_are_parsed(self):
        ctx = rl.load_domain_references(["finops_billing"])
        assert ctx.facets
        assert any(f.values for f in ctx.facets)


class TestGracefulDegradation:
    def test_unknown_domain_returns_empty_context(self):
        ctx = rl.load_domain_references(["does_not_exist_domain"])
        assert ctx == RAGContext()

    def test_mixed_known_and_unknown(self):
        ctx = rl.load_domain_references(["finops_billing", "nope"])
        assert ctx.tables  # known domain still loaded, unknown skipped

    def test_missing_base_dir_returns_empty(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert rl.available_domains(base_dir=empty) == []
        ctx = rl.load_domain_references(["finops_billing"], base_dir=empty)
        assert ctx == RAGContext()


class TestNoVectorDriverImport:
    def test_default_path_imports_no_vector_driver(self):
        """Loading reference context must not import sqlite_vec or vector-search."""
        code = (
            "import sys; "
            "from starboard_core.rag.reference_loader import load_domain_references; "
            "ctx = load_domain_references(['finops_billing']); "
            "assert ctx.tables, 'expected populated context'; "
            "bad = [m for m in sys.modules "
            "if 'sqlite_vec' in m or 'vector_search' in m or m == 'databricks']; "
            "assert not bad, f'unexpected vector driver imported: {bad}'; "
            "print('OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout


class TestGovernance:
    _FORBIDDEN = (
        "centralized_system_tables",
        "fin_live_gold",
        "hmr_stack_hash",
        "logfood",
        "clickhouse",
        "go/",
    )

    def test_no_internal_namespaces_in_knowledge_files(self):
        directory = rl.KNOWLEDGE_DIR
        offenders: list[str] = []
        for md in directory.glob("*.md"):
            text = md.read_text(encoding="utf-8").lower()
            for token in self._FORBIDDEN:
                if token in text:
                    offenders.append(f"{md.name}: {token}")
        assert not offenders, f"internal namespace leaked: {offenders}"
