# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Deterministic, embedding-free RAG reference loader (kernel-tier).

Loads curated Markdown reference files shipped as package data under
``starboard_core/rag/knowledge/domains/<domain>.md`` and assembles them into a
:class:`~starboard_core.rag.models.RAGContext` — the *same* downstream contract
the vector-store path returns, minus the embedding round-trip.

This module is intentionally pure and SDK-free (plain file reads only), so it
stays on the kernel side of the import-linter boundary: no ``databricks``,
``openai``, ``fastapi``, or ``mcp`` imports. It is the default (``vector_backend
= "none"``) analytics-context path; managed Databricks Vector Search remains the
opt-in escape hatch behind ``starboard[vectorsearch]``.

Reference-file format (one file per :class:`RagResourceDomain`)::

    ---
    domain: finops_billing
    system_tables:
    - system.billing.usage
    - system.billing.list_prices
    ---

    # Reference: finops_billing

    ## Tables

    ### system.billing.usage
    Usage/consumption fact table ...

    ## Nuance

    ### cost_attribution | rule
    <free text, possibly multi-line>

    ## Codebook

    ### system.access.audit.audit_level
    <free text>

    ## Facets

    ### system.access.audit.audit_level
    ACCOUNT_LEVEL, WORKSPACE_LEVEL
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from starboard_core.rag.models import (
    RAGCodebookContext,
    RAGContext,
    RAGFacetContext,
    RAGNuanceContext,
    RAGTableContext,
)
from starboard_core.rag.resource_domains import RagResourceDomain

# Directory of shipped reference files (package data).
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge" / "domains"

# Canonical section names inside a reference file.
_SECTION_TABLES = "Tables"
_SECTION_NUANCE = "Nuance"
_SECTION_CODEBOOK = "Codebook"
_SECTION_FACETS = "Facets"

# Default sections loaded when a caller does not restrict them.
DEFAULT_SECTIONS: tuple[str, ...] = (
    _SECTION_TABLES,
    _SECTION_NUANCE,
    _SECTION_CODEBOOK,
    _SECTION_FACETS,
)


@dataclass(frozen=True)
class _Entry:
    """A single ``### <header>`` entry within a section."""

    header: str
    body: str


@dataclass(frozen=True)
class DomainReference:
    """Parsed representation of one domain reference file."""

    domain: str
    system_tables: tuple[str, ...]
    sections: dict[str, tuple[_Entry, ...]]


def _knowledge_dir(base_dir: Path | None = None) -> Path:
    return base_dir if base_dir is not None else KNOWLEDGE_DIR


def domain_file_path(domain: str, base_dir: Path | None = None) -> Path:
    """Return the on-disk path for a domain's reference file."""
    return _knowledge_dir(base_dir) / f"{domain}.md"


def available_domains(base_dir: Path | None = None) -> list[str]:
    """List domains that have a reference file on disk (sorted)."""
    directory = _knowledge_dir(base_dir)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))


def _split_front_matter(text: str) -> tuple[dict[str, object], str]:
    """Split YAML-ish front-matter (delimited by ``---``) from the body.

    Only the tiny subset needed here is parsed: ``key: value`` scalars and
    ``key:`` followed by ``- item`` list entries. No external YAML dependency
    (keeps the loader kernel-clean).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    fm_lines: list[str] = []
    body_start = len(lines)
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            body_start = idx + 1
            break
        fm_lines.append(lines[idx])

    front: dict[str, object] = {}
    current_key: str | None = None
    for raw in fm_lines:
        if not raw.strip():
            continue
        stripped = raw.strip()
        if stripped.startswith("- ") and current_key is not None:
            item = stripped[2:].strip()
            existing = front.get(current_key)
            if isinstance(existing, list):
                existing.append(item)
            else:
                front[current_key] = [item]
            continue
        if ":" in raw:
            key, _, value = raw.partition(":")
            key = key.strip()
            value = value.strip()
            current_key = key
            if value:
                front[key] = value
            else:
                # A bare ``key:`` introduces a list on subsequent lines.
                front.setdefault(key, [])
    body = "\n".join(lines[body_start:])
    return front, body


def _parse_sections(body: str) -> dict[str, tuple[_Entry, ...]]:
    """Parse ``## Section`` / ``### Entry`` structure into entries per section."""
    sections: dict[str, list[_Entry]] = {}
    current_section: str | None = None
    current_header: str | None = None
    current_body: list[str] = []

    def _flush_entry() -> None:
        nonlocal current_header, current_body
        if current_section is not None and current_header is not None:
            sections.setdefault(current_section, []).append(
                _Entry(
                    header=current_header.strip(),
                    body="\n".join(current_body).strip(),
                )
            )
        current_header = None
        current_body = []

    for line in body.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            _flush_entry()
            current_section = line[3:].strip()
            sections.setdefault(current_section, [])
        elif line.startswith("### "):
            _flush_entry()
            current_header = line[4:].strip()
        elif current_header is not None:
            current_body.append(line)
        # Lines before the first entry header (e.g. the "# Reference:" title or
        # section preamble) are intentionally ignored.

    _flush_entry()
    return {name: tuple(entries) for name, entries in sections.items()}


def parse_domain_reference(text: str) -> DomainReference:
    """Parse the raw Markdown of a reference file into a :class:`DomainReference`."""
    front, body = _split_front_matter(text)
    domain = str(front.get("domain", "")).strip()
    raw_tables = front.get("system_tables", [])
    if isinstance(raw_tables, list):
        system_tables = tuple(str(t).strip() for t in raw_tables if str(t).strip())
    elif isinstance(raw_tables, str) and raw_tables.strip():
        system_tables = (raw_tables.strip(),)
    else:
        system_tables = ()
    sections = _parse_sections(body)
    return DomainReference(
        domain=domain, system_tables=system_tables, sections=sections
    )


def load_domain_reference(
    domain: str, base_dir: Path | None = None
) -> DomainReference | None:
    """Load and parse a single domain reference file, or ``None`` if missing."""
    path = domain_file_path(domain, base_dir)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_domain_reference(text)


def _tables_from(ref: DomainReference) -> list[RAGTableContext]:
    entries = ref.sections.get(_SECTION_TABLES, ())
    tables: list[RAGTableContext] = []
    for entry in entries:
        tables.append(
            RAGTableContext(
                table_name=entry.header,
                description=entry.body or None,
                table_columns=None,
                relationships=None,
                use_cases=None,
                domain=ref.domain,
                relevance_score=1.0,
            )
        )
    return tables


def _nuance_from(ref: DomainReference) -> list[RAGNuanceContext]:
    entries = ref.sections.get(_SECTION_NUANCE, ())
    nuance: list[RAGNuanceContext] = []
    for entry in entries:
        topic, _, ntype = entry.header.partition("|")
        nuance.append(
            RAGNuanceContext(
                topic=topic.strip() or entry.header,
                type=ntype.strip() or "nuance",
                content=entry.body,
                domain=ref.domain,
                relevance_score=1.0,
            )
        )
    return nuance


def _codebook_from(ref: DomainReference) -> list[RAGCodebookContext]:
    entries = ref.sections.get(_SECTION_CODEBOOK, ())
    codebook: list[RAGCodebookContext] = []
    for entry in entries:
        codebook.append(
            RAGCodebookContext(
                code=entry.header,
                description=entry.body,
                sku_family="all",
                warehouse_type="na",
                time_validity="stable",
                involves_tags=False,
                domain=ref.domain,
                relevance_score=1.0,
            )
        )
    return codebook


def _facets_from(ref: DomainReference) -> list[RAGFacetContext]:
    entries = ref.sections.get(_SECTION_FACETS, ())
    facets: list[RAGFacetContext] = []
    for entry in entries:
        values = [v.strip() for v in entry.body.replace("\n", ",").split(",")]
        values = [v for v in values if v]
        facets.append(
            RAGFacetContext(
                code=entry.header,
                values=values,
                domain=ref.domain,
                relevance_score=1.0,
            )
        )
    return facets


def load_domain_references(
    domains: list[str] | None,
    sections: list[str] | None = None,
    *,
    base_dir: Path | None = None,
) -> RAGContext:
    """Assemble a :class:`RAGContext` from the given domains' reference files.

    Args:
        domains: Domain labels (``RagResourceDomain`` values). ``None``/empty
            yields an empty context (deterministic graceful degradation).
        sections: Optional subset of section names to include (defaults to all:
            Tables, Nuance, Codebook, Facets).
        base_dir: Override the knowledge directory (used by tests).

    Returns:
        A populated ``RAGContext``. Missing domain files are skipped silently so
        an unknown/absent domain degrades to an empty context rather than raising.
    """
    context = RAGContext()
    if not domains:
        return context

    wanted = set(sections) if sections is not None else set(DEFAULT_SECTIONS)

    seen: set[str] = set()
    for domain in domains:
        key = str(domain).strip()
        if not key or key in seen:
            continue
        seen.add(key)

        ref = load_domain_reference(key, base_dir=base_dir)
        if ref is None:
            continue

        if _SECTION_TABLES in wanted:
            context.tables.extend(_tables_from(ref))
        if _SECTION_NUANCE in wanted:
            context.nuance.extend(_nuance_from(ref))
        if _SECTION_CODEBOOK in wanted:
            context.codebook.extend(_codebook_from(ref))
        if _SECTION_FACETS in wanted:
            context.facets.extend(_facets_from(ref))

    return context


def all_domain_labels() -> list[str]:
    """Return every ``RagResourceDomain`` label (the expected reference-file set)."""
    return [d.value for d in RagResourceDomain]
