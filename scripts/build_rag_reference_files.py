#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Generate curated per-domain RAG reference files (Phase 2 C1).

Reads the source-of-truth corpus packs
(``starboard_core/rag/data/{nuance_pack,codebook_pack}.json``) and the
system-table -> domain mapping (``starboard_core/rag/resource_domains.py``) and
emits one Markdown reference file per ``RagResourceDomain`` under
``starboard_core/rag/knowledge/domains/<domain>.md``.

These files are shipped as package data and read at runtime by
``starboard_core.rag.reference_loader`` (the default, embedding-free analytics
context path). Re-run this script whenever the corpus packs change::

    python scripts/build_rag_reference_files.py

The output format is consumed verbatim by ``reference_loader.parse_domain_reference``.

Input contract
--------------
Both ``nuance_pack.json`` and ``codebook_pack.json`` must be JSON objects with a
``"records"`` list.  See ``scripts/README_BUILD_RAG.md`` §Input Contract for the
full field specification and what ``PackParseError`` is raised on violation.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "packages" / "starboard-core"
sys.path.insert(0, str(CORE))

from starboard_core.rag.resource_domains import (  # noqa: E402
    _EXACT,
    RagResourceDomain,
)

DATA_DIR = CORE / "starboard_core" / "rag" / "data"
OUT_DIR = CORE / "starboard_core" / "rag" / "knowledge" / "domains"

# Corpus `metadata.domain` labels that are not RagResourceDomain values, mapped
# onto the canonical enum. Keeps all curated content addressable by the enum the
# loader/mapper key on.
_DOMAIN_ALIASES = {
    "sql_policy": RagResourceDomain.QUERY.value,
    "query_history": RagResourceDomain.QUERY.value,
    "security_audit": RagResourceDomain.SECURITY_ACCESS.value,
    "governance_lineage": RagResourceDomain.LINEAGE.value,
}


# ---------------------------------------------------------------------------
# Structured corpus-pack models
# ---------------------------------------------------------------------------


class PackParseError(ValueError):
    """Raised when a corpus pack file fails structural validation.

    Always a ``ValueError`` subclass so callers can use a broad ``except
    ValueError`` if they choose.  The message always identifies the source file
    and, for per-record errors, the zero-based record index.
    """


@dataclass(frozen=True)
class NuanceRecord:
    """One validated entry from ``nuance_pack.json``."""

    id: str
    document: str
    domain: str    # raw domain label from metadata (may be an alias)
    topic_id: str  # falls back to ``id`` when absent in the source
    doc_type: str  # falls back to ``"nuance"`` when absent in the source


@dataclass(frozen=True)
class CodebookRecord:
    """One validated entry from ``codebook_pack.json``."""

    id: str
    document: str
    domain: str         # raw domain label from metadata (may be an alias)
    code_key: str       # required; used verbatim as the Markdown entry header
    values_csv: str | None  # optional comma-separated categorical values


# ---------------------------------------------------------------------------
# Pack parsers — fail loud on malformed input
# ---------------------------------------------------------------------------


def _parse_nuance_records(
    data: object, *, source: str = "<data>"
) -> list[NuanceRecord]:
    """Parse and validate nuance pack JSON data.

    Args:
        data:   Decoded JSON value (the result of ``json.loads`` on the pack file).
        source: Human-readable label for error messages (e.g. the filename).

    Returns:
        A list of validated :class:`NuanceRecord` objects.

    Raises:
        PackParseError: when the top-level shape is wrong, or any record is
            missing a required field.  Never silently returns partial/empty
            results for a structurally invalid pack.
    """
    if not isinstance(data, dict):
        raise PackParseError(
            f"{source}: expected a JSON object, got {type(data).__name__}"
        )
    if "records" not in data:
        raise PackParseError(f"{source}: missing required key 'records'")
    records_raw = data["records"]
    if not isinstance(records_raw, list):
        raise PackParseError(
            f"{source}: 'records' must be a list, got {type(records_raw).__name__}"
        )

    out: list[NuanceRecord] = []
    for idx, rec in enumerate(records_raw):
        ctx = f"{source}[{idx}]"
        if not isinstance(rec, dict):
            raise PackParseError(
                f"{ctx}: expected a dict, got {type(rec).__name__}"
            )

        rid = rec.get("id")
        if not rid or not isinstance(rid, str):
            raise PackParseError(f"{ctx}: missing or empty required field 'id'")

        document = rec.get("document")
        if not document or not isinstance(document, str):
            raise PackParseError(
                f"{ctx}: missing or empty required field 'document'"
            )

        metadata = rec.get("metadata")
        if not isinstance(metadata, dict):
            raise PackParseError(
                f"{ctx}: missing or invalid 'metadata' (expected a dict)"
            )

        domain_raw = metadata.get("domain")
        if not domain_raw or not isinstance(domain_raw, str):
            raise PackParseError(
                f"{ctx}: 'metadata.domain' is missing or empty — "
                "every nuance record must declare which domain it belongs to"
            )

        out.append(
            NuanceRecord(
                id=rid,
                document=document,
                domain=domain_raw,
                topic_id=str(metadata.get("topic_id") or rid),
                doc_type=str(metadata.get("doc_type") or "nuance"),
            )
        )
    return out


def _parse_codebook_records(
    data: object, *, source: str = "<data>"
) -> list[CodebookRecord]:
    """Parse and validate codebook pack JSON data.

    Args:
        data:   Decoded JSON value (the result of ``json.loads`` on the pack file).
        source: Human-readable label for error messages (e.g. the filename).

    Returns:
        A list of validated :class:`CodebookRecord` objects.

    Raises:
        PackParseError: on structural violations (see :func:`_parse_nuance_records`).
    """
    if not isinstance(data, dict):
        raise PackParseError(
            f"{source}: expected a JSON object, got {type(data).__name__}"
        )
    if "records" not in data:
        raise PackParseError(f"{source}: missing required key 'records'")
    records_raw = data["records"]
    if not isinstance(records_raw, list):
        raise PackParseError(
            f"{source}: 'records' must be a list, got {type(records_raw).__name__}"
        )

    out: list[CodebookRecord] = []
    for idx, rec in enumerate(records_raw):
        ctx = f"{source}[{idx}]"
        if not isinstance(rec, dict):
            raise PackParseError(
                f"{ctx}: expected a dict, got {type(rec).__name__}"
            )

        rid = rec.get("id")
        if not rid or not isinstance(rid, str):
            raise PackParseError(f"{ctx}: missing or empty required field 'id'")

        document = rec.get("document")
        if not document or not isinstance(document, str):
            raise PackParseError(
                f"{ctx}: missing or empty required field 'document'"
            )

        metadata = rec.get("metadata")
        if not isinstance(metadata, dict):
            raise PackParseError(
                f"{ctx}: missing or invalid 'metadata' (expected a dict)"
            )

        domain_raw = metadata.get("domain")
        if not domain_raw or not isinstance(domain_raw, str):
            raise PackParseError(
                f"{ctx}: 'metadata.domain' is missing or empty — "
                "every codebook record must declare which domain it belongs to"
            )

        code_key = metadata.get("code_key")
        if not code_key or not isinstance(code_key, str):
            raise PackParseError(
                f"{ctx}: 'metadata.code_key' is missing or empty — "
                "every codebook record must have a code_key"
            )

        values_csv_raw = metadata.get("values_csv")
        values_csv: str | None = (
            str(values_csv_raw)
            if values_csv_raw and isinstance(values_csv_raw, str)
            else None
        )

        out.append(
            CodebookRecord(
                id=rid,
                document=document,
                domain=domain_raw,
                code_key=code_key,
                values_csv=values_csv,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_domain(raw: str) -> str | None:
    if raw in {d.value for d in RagResourceDomain}:
        return raw
    return _DOMAIN_ALIASES.get(raw)


def _reverse_table_map() -> dict[str, list[str]]:
    rev: dict[str, list[str]] = defaultdict(list)
    for table, domains in _EXACT.items():
        for d in domains:
            if table not in rev[d.value]:
                rev[d.value].append(table)
    return rev


def _load(pack: str) -> object:
    """Load a corpus pack JSON file and return the raw decoded object."""
    return json.loads((DATA_DIR / f"{pack}.json").read_text(encoding="utf-8"))


def _indent_body(text: str) -> str:
    # Preserve content verbatim; the loader treats everything up to the next
    # `###`/`##` as the entry body. Corpus documents never start a line with
    # `#`/`---`, verified during authoring.
    return text.rstrip()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_domain_md(
    domain: str,
    tables: list[str],
    nuances: list[NuanceRecord],
    codebooks: list[CodebookRecord],
) -> str:
    """Render one domain reference file as a Markdown string.

    This is the pure rendering step: no I/O, no domain-enum lookups.  The
    output format is consumed verbatim by
    ``starboard_core.rag.reference_loader.parse_domain_reference``.

    Args:
        domain:    Domain label (e.g. ``"finops_billing"``).
        tables:    Sorted list of system-table names mapped to this domain.
        nuances:   Validated nuance records for this domain.
        codebooks: Validated codebook records for this domain.

    Returns:
        Complete Markdown text for the domain reference file (trailing newline
        guaranteed).
    """
    lines: list[str] = []
    lines.append("---")
    lines.append(f"domain: {domain}")
    lines.append("system_tables:")
    for t in tables:
        lines.append(f"- {t}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Reference: {domain}")
    lines.append("")
    lines.append(
        "> Curated Databricks system-table knowledge for the "
        f"`{domain}` RAG resource domain. SQL corpus lives in "
        "`discovery/query_packs/*` (reused in place, not duplicated here)."
    )
    lines.append("")

    # Tables
    lines.append("## Tables")
    lines.append("")
    if tables:
        for t in tables:
            lines.append(f"### {t}")
            lines.append(
                f"System table in the `{domain}` domain. See query packs for "
                "vetted SQL over this table."
            )
            lines.append("")
    else:
        lines.append(
            "_No system tables are exclusively mapped to this domain; see "
            "related domains._"
        )
        lines.append("")

    # Nuance
    lines.append("## Nuance")
    lines.append("")
    if nuances:
        for n in nuances:
            lines.append(f"### {n.topic_id} | {n.doc_type}")
            lines.append(_indent_body(n.document))
            lines.append("")
    else:
        lines.append("_No curated nuance entries for this domain yet._")
        lines.append("")

    # Codebook
    lines.append("## Codebook")
    lines.append("")
    if codebooks:
        for cb in codebooks:
            lines.append(f"### {cb.code_key}")
            lines.append(_indent_body(cb.document))
            lines.append("")
    else:
        lines.append("_No curated codebook entries for this domain yet._")
        lines.append("")

    # Facets (derived from codebook values_csv)
    lines.append("## Facets")
    lines.append("")
    facet_count = 0
    for cb in codebooks:
        if not cb.values_csv:
            continue
        lines.append(f"### {cb.code_key}")
        lines.append(cb.values_csv)
        lines.append("")
        facet_count += 1
    if facet_count == 0:
        lines.append("_No categorical facets for this domain yet._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rev_tables = _reverse_table_map()
    nuance_records = _parse_nuance_records(
        _load("nuance_pack"), source="nuance_pack.json"
    )
    codebook_records = _parse_codebook_records(
        _load("codebook_pack"), source="codebook_pack.json"
    )

    nuance_by_domain: dict[str, list[NuanceRecord]] = defaultdict(list)
    for n in nuance_records:
        dom = _canonical_domain(n.domain)
        if dom:
            nuance_by_domain[dom].append(n)

    codebook_by_domain: dict[str, list[CodebookRecord]] = defaultdict(list)
    for cb in codebook_records:
        dom = _canonical_domain(cb.domain)
        if dom:
            codebook_by_domain[dom].append(cb)

    written = []
    for domain in RagResourceDomain:
        d = domain.value
        tables = sorted(rev_tables.get(d, []))
        nuances = nuance_by_domain.get(d, [])
        codebooks = codebook_by_domain.get(d, [])

        md = _render_domain_md(d, tables, nuances, codebooks)
        out = OUT_DIR / f"{d}.md"
        out.write_text(md, encoding="utf-8")

        facet_count = sum(1 for cb in codebooks if cb.values_csv)
        written.append((d, len(tables), len(nuances), len(codebooks), facet_count))

    print(f"Wrote {len(written)} reference files to {OUT_DIR}")
    for d, nt, nn, nc, nf in written:
        print(f"  {d:28s} tables={nt} nuance={nn} codebook={nc} facets={nf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
