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
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
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


def _load(pack: str) -> list[dict]:
    return json.loads((DATA_DIR / f"{pack}.json").read_text(encoding="utf-8"))[
        "records"
    ]


def _indent_body(text: str) -> str:
    # Preserve content verbatim; the loader treats everything up to the next
    # `###`/`##` as the entry body. Corpus documents never start a line with
    # `#`/`---`, verified during authoring.
    return text.rstrip()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rev_tables = _reverse_table_map()
    nuance_records = _load("nuance_pack")
    codebook_records = _load("codebook_pack")

    nuance_by_domain: dict[str, list[dict]] = defaultdict(list)
    for rec in nuance_records:
        dom = _canonical_domain(rec["metadata"].get("domain", ""))
        if dom:
            nuance_by_domain[dom].append(rec)

    codebook_by_domain: dict[str, list[dict]] = defaultdict(list)
    for rec in codebook_records:
        dom = _canonical_domain(rec["metadata"].get("domain", ""))
        if dom:
            codebook_by_domain[dom].append(rec)

    written = []
    for domain in RagResourceDomain:
        d = domain.value
        tables = sorted(rev_tables.get(d, []))
        nuances = nuance_by_domain.get(d, [])
        codebooks = codebook_by_domain.get(d, [])

        lines: list[str] = []
        lines.append("---")
        lines.append(f"domain: {d}")
        lines.append("system_tables:")
        for t in tables:
            lines.append(f"- {t}")
        lines.append("---")
        lines.append("")
        lines.append(f"# Reference: {d}")
        lines.append("")
        lines.append(
            "> Curated Databricks system-table knowledge for the "
            f"`{d}` RAG resource domain. SQL corpus lives in "
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
                    f"System table in the `{d}` domain. See query packs for "
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
            for rec in nuances:
                meta = rec["metadata"]
                topic = meta.get("topic_id", rec.get("id", "nuance"))
                ntype = meta.get("doc_type", "nuance")
                lines.append(f"### {topic} | {ntype}")
                lines.append(_indent_body(rec["document"]))
                lines.append("")
        else:
            lines.append("_No curated nuance entries for this domain yet._")
            lines.append("")

        # Codebook
        lines.append("## Codebook")
        lines.append("")
        if codebooks:
            for rec in codebooks:
                meta = rec["metadata"]
                code = meta.get("code_key", rec.get("id", "code"))
                lines.append(f"### {code}")
                lines.append(_indent_body(rec["document"]))
                lines.append("")
        else:
            lines.append("_No curated codebook entries for this domain yet._")
            lines.append("")

        # Facets (derived from codebook values_csv)
        lines.append("## Facets")
        lines.append("")
        facet_count = 0
        for rec in codebooks:
            meta = rec["metadata"]
            values_csv = meta.get("values_csv")
            if not values_csv:
                continue
            code = meta.get("code_key", rec.get("id", "code"))
            lines.append(f"### {code}")
            lines.append(values_csv)
            lines.append("")
            facet_count += 1
        if facet_count == 0:
            lines.append("_No categorical facets for this domain yet._")
            lines.append("")

        out = OUT_DIR / f"{d}.md"
        out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        written.append(
            (d, len(tables), len(nuances), len(codebooks), facet_count)
        )

    print(f"Wrote {len(written)} reference files to {OUT_DIR}")
    for d, nt, nn, nc, nf in written:
        print(f"  {d:28s} tables={nt} nuance={nn} codebook={nc} facets={nf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
