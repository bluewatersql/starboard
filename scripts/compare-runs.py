#!/usr/bin/env python3
"""Cross-run comparison harness for Starboard engagement runs.

Usage:
    python scripts/compare-runs.py --gold starboard-reports/<model>/<run> starboard-reports/*/*/
    python scripts/compare-runs.py --gold starboard-reports/claude-opus-5-5/* starboard-reports/*/* --json

Outputs a Markdown (or JSON with --json) report to stdout containing:

1. **Facts diff** — compares numeric fields in discovery.json ``data.facts``
   (``<run>/discovery.json`` or ``<run>/discovery/discovery.json``) vs the gold run;
   flags diffs > 10 %.
2. **Catalog-id comparison** — for each (OPP-* id, ``target``) item in
   analysis/backlog.json: tier, sizing kind, sizing value (flagged > 10 % apart; not
   compared when both sides name a different ``sizing.metric`` or ``sizing.unit`` — a
   missing metric/unit on one side is tolerated), and whether the item is present vs
   gold — a gold item the run cut (same target, or the id untargeted) shows
   "cut: [<rule>] <reason>", and one the run folds into another target's item (its raw
   id in that item's formula/notes/title) shows "aggregated", rather than "missing".
   Items without ``target`` (pre-round-4 backlogs, or a prose target) key on their
   occurrence of the id (#1, #2 …).  A legacy string ``sizing.value`` ("1,400 DBU") is
   parsed for its leading number and reported as a warning.
3. **Conformance matrix** — runs ``starboard-helper run check`` per-run and
   prints a PASS/FAIL × 16-item matrix.

Only directories holding ``discovery.json``, ``discovery/discovery.json`` or
``README.md`` count as runs; anything else a glob matches (``ws-*`` trend roots,
``trend/``, ``charts/`` …) is skipped with a note on stderr.

Degrades gracefully when facts or backlog are absent (reports "absent").

Stdlib only: json, pathlib, subprocess, sys, re, argparse, textwrap.
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECKLIST_ITEMS = [
    "1:README.md has '## Delivery' and '## Recur' sections",
    "2:discovery.json has data.facts",
    "3:discovery/domains/ >=3 .md files",
    "4:discovery/analysis.md has 'Grade'",
    "5:analysis/verify/ .sql/.json pairs (min count)",
    "6:analysis/backlog.json valid per §3",
    "7:analysis/action-plan.md",
    "8:analysis/technical-review.md has '## Humanize'",
    "9:deliverables/ required files",
    "10:one notebook per Act-now/Investigate item (Not-now needs none)",
    "11:deliverables/charts/ >=1 .png",
    "12:internal: .clean siblings for deliverables",
    "13:findings-manifest.json",
    "14:backlog carries or cuts every fired catalog trigger",
    "15:analysis/recur-result.json ok + history entry",
    "16:internal: .clean prose has no sanitizer findings",
]

# Prefix identifiers used to match items (e.g. "1:", "10:")
ITEM_PREFIXES = [f"{i + 1}:" for i in range(len(CHECKLIST_ITEMS))]

# Threshold for flagging numeric diffs vs gold
DIFF_THRESHOLD_PCT = 10.0

# Files whose presence marks a directory as an engagement run dir.
RUN_MARKERS = ("discovery.json", "discovery/discovery.json", "README.md")


# ---------------------------------------------------------------------------
# Run discovery
# ---------------------------------------------------------------------------


def is_run_dir(p: Path) -> bool:
    """True when ``p`` holds one of :data:`RUN_MARKERS` (a trend root or charts dir does not)."""
    return p.is_dir() and any((p / m).is_file() for m in RUN_MARKERS)


def find_runs(paths: list[str]) -> list[Path]:
    """Expand glob patterns and return only the directories that are run dirs."""
    candidates: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            candidates.append(p)
        else:
            # Try as a glob pattern
            candidates.extend(Path(m) for m in sorted(_glob.glob(raw)) if Path(m).is_dir())
    runs: list[Path] = []
    for c in candidates:
        if is_run_dir(c):
            runs.append(c.resolve())
        else:
            print(f"note: skipping non-run dir (no {', '.join(RUN_MARKERS)}): {c}", file=sys.stderr)
    # Deduplicate, preserve order
    seen: set[Path] = set()
    result: list[Path] = []
    for r in runs:
        if r not in seen:
            seen.add(r)
            result.append(r)
    return result


def run_label(run_dir: Path) -> str:
    """Return a short label: <model>/<run-id> based on directory structure."""
    parts = run_dir.parts
    # Look for the pattern: .../starboard-reports/<model>/<run-id>
    for i, part in enumerate(parts):
        if part == "starboard-reports" and i + 2 < len(parts):
            return f"{parts[i + 1]}/{parts[i + 2][:8]}"
    # Fallback: last two path components
    return f"{run_dir.parent.name}/{run_dir.name[:8]}"


# ---------------------------------------------------------------------------
# Facts extraction and comparison
# ---------------------------------------------------------------------------


def _flatten_facts(facts: dict[str, Any], prefix: str = "") -> dict[str, float]:
    """Recursively extract all numeric leaf values from a facts dict."""
    result: dict[str, float] = {}
    for k, v in facts.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            result[key] = float(v)
        elif isinstance(v, dict):
            result.update(_flatten_facts(v, key))
        elif isinstance(v, list):
            for idx, item in enumerate(v):
                if isinstance(item, dict):
                    result.update(_flatten_facts(item, f"{key}[{idx}]"))
    return result


def load_facts(run_dir: Path) -> dict[str, Any] | None:
    """Load data.facts from discovery.json (root or discovery/); return None if absent."""
    djson = next(
        (run_dir / rel for rel in ("discovery.json", "discovery/discovery.json") if (run_dir / rel).is_file()),
        None,
    )
    if djson is None:
        return None
    try:
        d = json.loads(djson.read_text())
        facts = (d.get("data") or {}).get("facts")
        return facts if isinstance(facts, dict) else None
    except Exception:  # noqa: BLE001
        return None


def compare_facts(
    gold_facts: dict[str, Any] | None,
    run_facts: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """
    Return a list of comparison records for numeric fields.

    Each record has: field, gold, run, diff_pct, flagged (bool).
    """
    if gold_facts is None and run_facts is None:
        return []

    gold_flat = _flatten_facts(gold_facts) if gold_facts else {}
    run_flat = _flatten_facts(run_facts) if run_facts else {}

    all_keys = sorted(set(gold_flat) | set(run_flat))
    records: list[dict[str, Any]] = []
    for key in all_keys:
        g = gold_flat.get(key)
        r = run_flat.get(key)
        if g is None or r is None:
            diff_pct = None
            flagged = False
        elif g == 0:
            diff_pct = 0.0 if r == 0 else None  # avoid div/0
            flagged = r != 0
        else:
            diff_pct = abs(r - g) / abs(g) * 100.0
            flagged = diff_pct > DIFF_THRESHOLD_PCT
        records.append(
            {
                "field": key,
                "gold": g,
                "run": r,
                "diff_pct": diff_pct,
                "flagged": flagged,
            }
        )
    return records


# ---------------------------------------------------------------------------
# Backlog / catalog-id comparison
# ---------------------------------------------------------------------------


def load_backlog_items(run_dir: Path) -> list[dict[str, Any]] | None:
    """Load items from analysis/backlog.json; return None if absent."""
    bp = run_dir / "analysis" / "backlog.json"
    if not bp.is_file():
        return None
    try:
        bl = json.loads(bp.read_text())
        items = bl.get("items")
        return items if isinstance(items, list) else None
    except Exception:  # noqa: BLE001
        return None


def load_backlog_cut(run_dir: Path) -> list[dict[str, Any]]:
    """Load the top-level ``cut`` list from analysis/backlog.json ([] when absent)."""
    try:
        bl = json.loads((run_dir / "analysis" / "backlog.json").read_text())
    except Exception:  # noqa: BLE001
        return []
    cut = bl.get("cut") if isinstance(bl, dict) else None
    return [c for c in cut if isinstance(c, dict)] if isinstance(cut, list) else []


# Same pattern as ``_TARGET_RE`` in starboard_skills/helpers/run.py (kept stdlib-standalone here).
_TARGET_RE = re.compile(
    r"^(workspace|(job|warehouse|pipeline|cluster|dashboard|genie|schema|endpoint|instance):\S+)$"
)


def _item_key(it: dict[str, Any], occurrence: int) -> tuple[str, str]:
    """(id, target).  An item without a canonical ``target`` (pre-round-4 backlogs, or prose such
    as "Warehouse abc — Starter") keys on its occurrence of that id (#1, #2…)."""
    target = it.get("target")
    key = target if isinstance(target, str) and _TARGET_RE.match(target) else f"#{occurrence}"
    return (str(it.get("id", "<no id>")), key)


def _items_by_key(items: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    seen: dict[str, int] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        n = seen[str(it.get("id"))] = seen.get(str(it.get("id")), 0) + 1
        out[_item_key(it, n)] = it
    return out


def _cut_reasons(cut: list[dict[str, Any]] | None) -> dict[tuple[str, str | None], str]:
    """(id, target or None) → "[rule] reason" (joined when the same key is cut more than once)."""
    out: dict[tuple[str, str | None], list[str]] = {}
    for c in cut or []:
        if isinstance(c.get("id"), str):
            rule = c.get("rule")
            reason = str(c.get("reason") or "").strip() or "no reason"
            target = c.get("target") if isinstance(c.get("target"), str) else None
            out.setdefault((c["id"], target), []).append(f"[{rule}] {reason}" if rule else reason)
    return {k: " / ".join(v) for k, v in out.items()}


def _cut_reason_for(cuts: dict[tuple[str, str | None], str], opp_id: str, target: str) -> str | None:
    """The cut covering (id, target): a cut of that exact target, else an untargeted cut of the id."""
    return cuts.get((opp_id, target)) or cuts.get((opp_id, None))


def _aggregated_into(
    opp_id: str, target: str, items_by_key: dict[tuple[str, str], dict[str, Any]]
) -> str | None:
    """Target of a same-id item on the other side that names ``target``'s raw id in its
    ``sizing.formula`` / ``notes`` / ``title`` (one item aggregating several targets), else None."""
    raw = target.split(":", 1)[1] if ":" in target else None
    if not raw:
        return None
    for (oid, other_target), it in items_by_key.items():
        if oid != opp_id or other_target == target:
            continue
        sizing = it.get("sizing") if isinstance(it.get("sizing"), dict) else {}
        text = " ".join(str(v) for v in (sizing.get("formula"), it.get("notes"), it.get("title")) if v)
        if raw in text:
            return other_target
    return None


def _sizing_basis(it: dict[str, Any] | None) -> tuple[Any, Any]:
    """(metric, unit) of an item's sizing — what its value measures."""
    s = (it.get("sizing") or {}) if it else {}
    return s.get("metric"), s.get("unit")


def _same_basis(g: dict[str, Any], r: dict[str, Any]) -> bool:
    """Values are comparable unless both sides name a metric (or a unit) and they differ —
    a missing ``sizing.metric`` / ``sizing.unit`` on one side is tolerated."""
    return all(a is None or b is None or a == b for a, b in zip(_sizing_basis(g), _sizing_basis(r)))


_LEADING_NUMBER = re.compile(r"^\s*([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)")


def parse_sizing_value(value: Any) -> tuple[float | None, str | None]:
    """``sizing.value`` → (number or None, warning or None).

    Numbers pass through.  A string (pre-schema backlogs wrote "4,819.5 DBU") yields its
    leading number — or None when it has none — plus a warning naming the raw value.
    """
    if value is None or isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, str):
        m = _LEADING_NUMBER.match(value)
        num = float(m.group(1).replace(",", "")) if m else None
        return num, f"string sizing.value {value!r} → {num if num is not None else 'no leading number'}"
    return None, f"non-numeric sizing.value {value!r} ignored"


def compare_catalog(
    gold_items: list[dict[str, Any]] | None,
    run_items: list[dict[str, Any]] | None,
    gold_cut: list[dict[str, Any]] | None = None,
    run_cut: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return per-(id, target) comparison records.

    A gold item absent from the run is ``missing`` unless the run cut that (id, target) — or the
    id without a target — (then ``run_cut_reason`` carries "[rule] reason"), or the run carries the
    id on another target whose formula/notes/title names this target (``run_aggregated_into``);
    a run item absent from gold is ``extra`` (``gold_cut_reason`` / ``gold_aggregated_into``
    likewise).  Sizing values are compared unless both sides name a different ``sizing.metric`` or
    ``sizing.unit`` (a missing metric/unit on one side is tolerated); otherwise
    ``sizing_comparable`` is False and no value diff is flagged.  A value on one side only is
    ``value_missing``.
    """
    if gold_items is None and run_items is None:
        return []

    gold_by_key = _items_by_key(gold_items or [])
    run_by_key = _items_by_key(run_items or [])
    gold_cuts, run_cuts = _cut_reasons(gold_cut), _cut_reasons(run_cut)
    all_keys = sorted(set(gold_by_key) | set(run_by_key))

    records: list[dict[str, Any]] = []
    for key in all_keys:
        opp_id, target = key
        g = gold_by_key.get(key)
        r = run_by_key.get(key)
        gold_tier = g.get("tier") if g else None
        run_tier = r.get("tier") if r else None
        gold_kind = (g.get("sizing") or {}).get("kind") if g else None
        run_kind = (r.get("sizing") or {}).get("kind") if r else None
        warnings: list[str] = []
        values: list[float | None] = []
        for side, it in (("gold", g), ("run", r)):
            v, w = parse_sizing_value((it.get("sizing") or {}).get("value") if it else None)
            values.append(v)
            if w:
                warnings.append(f"{side} {opp_id}: {w}")
        gold_value, run_value = values

        run_cut_reason = _cut_reason_for(run_cuts, opp_id, target) if g is not None and r is None else None
        gold_cut_reason = _cut_reason_for(gold_cuts, opp_id, target) if r is not None and g is None else None
        run_aggregated_into = (
            _aggregated_into(opp_id, target, run_by_key) if g is not None and r is None and not run_cut_reason else None
        )
        gold_aggregated_into = (
            _aggregated_into(opp_id, target, gold_by_key) if r is not None and g is None and not gold_cut_reason else None
        )
        missing = g is not None and r is None and run_cut_reason is None and run_aggregated_into is None
        extra = r is not None and g is None
        tier_flip = (gold_tier is not None and run_tier is not None and gold_tier != run_tier)
        kind_change = (gold_kind is not None and run_kind is not None and gold_kind != run_kind)
        sizing_comparable = g is not None and r is not None and _same_basis(g, r)
        value_missing = sizing_comparable and (gold_value is None) != (run_value is None)
        value_diff = (
            sizing_comparable
            and gold_value is not None
            and run_value is not None
            and (
                abs(run_value - gold_value) / abs(gold_value) * 100.0 > DIFF_THRESHOLD_PCT
                if gold_value
                else run_value != 0
            )
        )
        basis_differs = (
            g is not None and r is not None and not sizing_comparable
            and (gold_value is not None or run_value is not None)
        )
        flagged = bool(
            missing or run_cut_reason or run_aggregated_into or extra or tier_flip or kind_change
            or value_diff or value_missing or basis_differs
        )

        records.append(
            {
                "id": opp_id,
                "target": target,
                "run_cut_reason": run_cut_reason,
                "gold_cut_reason": gold_cut_reason,
                "run_aggregated_into": run_aggregated_into,
                "gold_aggregated_into": gold_aggregated_into,
                "extra_in_run": extra,
                "sizing_comparable": sizing_comparable,
                "gold_sizing_basis": "/".join(str(x) for x in _sizing_basis(g)) if g else None,
                "run_sizing_basis": "/".join(str(x) for x in _sizing_basis(r)) if r else None,
                "gold_tier": gold_tier or "absent",
                "run_tier": run_tier or "absent",
                "gold_sizing_kind": gold_kind or "absent",
                "run_sizing_kind": run_kind or "absent",
                "gold_sizing_value": gold_value,
                "run_sizing_value": run_value,
                "missing_from_run": missing,
                "tier_flip": tier_flip,
                "kind_change": kind_change,
                "value_diff": value_diff,
                "value_missing": value_missing,
                "warnings": warnings,
                "flagged": flagged,
            }
        )
    return records


# ---------------------------------------------------------------------------
# Conformance check (runs starboard-helper run check)
# ---------------------------------------------------------------------------


def run_conformance_check(run_dir: Path, internal: bool = False) -> dict[str, str]:
    """
    Run ``starboard-helper run check <run-dir> [--internal]`` and return
    a dict mapping item-prefix → "PASS" | "FAIL".

    Falls back to all-FAIL on subprocess error.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "starboard_skills.helpers", "run", "check", str(run_dir)]
            + (["--internal"] if internal else []),
            capture_output=True,
            text=True,
            timeout=120,
        )
        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError:
            return dict.fromkeys(ITEM_PREFIXES, "FAIL")

        data = envelope.get("data") or {}
        passed = set(data.get("passed", []))
        failed_items = {f["item"] for f in data.get("failed", [])}

        status: dict[str, str] = {}
        for prefix in ITEM_PREFIXES:
            p_match = any(i.startswith(prefix) for i in passed)
            f_match = any(i.startswith(prefix) for i in failed_items)
            if p_match:
                status[prefix] = "PASS"
            elif f_match:
                status[prefix] = "FAIL"
            else:
                status[prefix] = "?"  # not seen
        return status
    except Exception:  # noqa: BLE001
        return dict.fromkeys(ITEM_PREFIXES, "ERR")


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _md_facts_section(
    gold_facts: dict[str, Any] | None,
    run_facts: dict[str, Any] | None,
    label: str,
) -> str:
    lines: list[str] = [f"### Facts diff — {label}"]
    if gold_facts is None:
        lines.append("Gold run has no `data.facts` (absent).")
    if run_facts is None:
        lines.append("This run has no `data.facts` (absent).")
    if gold_facts is None or run_facts is None:
        return "\n".join(lines) + "\n"

    records = compare_facts(gold_facts, run_facts)
    flagged = [r for r in records if r["flagged"]]
    if not records:
        lines.append("No numeric fields found.")
        return "\n".join(lines) + "\n"
    if not flagged:
        lines.append(f"All {len(records)} numeric field(s) within {DIFF_THRESHOLD_PCT}% of gold.")
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append("| Field | Gold | Run | Diff% | Flag |")
    lines.append("|---|---|---|---|---|")
    for r in flagged:
        diff_str = f"{r['diff_pct']:.1f}%" if r["diff_pct"] is not None else "n/a"
        lines.append(
            f"| `{r['field']}` | {r['gold']} | {r['run']} | {diff_str} | ⚠ |"
        )
    lines.append("")
    lines.append(
        f"({len(flagged)} of {len(records)} field(s) flagged as >{DIFF_THRESHOLD_PCT}% diff)"
    )
    return "\n".join(lines) + "\n"


def _cell(value: Any) -> str:
    """Escape a value for a Markdown table cell."""
    return str(value).replace("|", "\\|")


def _md_catalog_section(
    gold_items: list[dict[str, Any]] | None,
    run_items: list[dict[str, Any]] | None,
    label: str,
    gold_cut: list[dict[str, Any]] | None = None,
    run_cut: list[dict[str, Any]] | None = None,
) -> str:
    lines: list[str] = [f"### Catalog-id comparison — {label}"]
    if gold_items is None:
        lines.append("Gold run has no `analysis/backlog.json` (absent).")
    if run_items is None:
        lines.append("This run has no `analysis/backlog.json` (absent).")
    if gold_items is None or run_items is None:
        return "\n".join(lines) + "\n"

    records = compare_catalog(gold_items, run_items, gold_cut, run_cut)
    flagged = [r for r in records if r["flagged"]]
    if not records:
        lines.append("No items in either run.")
        return "\n".join(lines) + "\n"
    if not flagged:
        lines.append(f"All {len(records)} (id, target) item(s) match gold (tier + sizing kind).")
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append("| Id | Target | Gold tier | Run tier | Gold sizing | Run sizing | Issues |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in flagged:
        issues = []
        if r["missing_from_run"]:
            issues.append("missing")
        if r["run_cut_reason"]:
            issues.append(f"cut: {r['run_cut_reason']}")
        if r["run_aggregated_into"]:
            issues.append(f"aggregated (run carries it in {r['run_aggregated_into']})")
        if r["extra_in_run"]:
            if r["gold_cut_reason"]:
                issues.append(f"not in gold (gold cut: {r['gold_cut_reason']})")
            elif r["gold_aggregated_into"]:
                issues.append(f"aggregated in gold ({r['gold_aggregated_into']})")
            else:
                issues.append("not in gold")
        if r["tier_flip"]:
            issues.append(f"tier {r['gold_tier']}→{r['run_tier']}")
        if r["kind_change"]:
            issues.append(f"sizing {r['gold_sizing_kind']}→{r['run_sizing_kind']}")
        if r["value_diff"] or r["value_missing"]:
            issues.append(f"value {r['gold_sizing_value']}→{r['run_sizing_value']}")
        if r["gold_tier"] != "absent" and r["run_tier"] != "absent" and not r["sizing_comparable"] and (
            r["gold_sizing_value"] is not None or r["run_sizing_value"] is not None
        ):
            issues.append(
                f"sizing not comparable ({r['gold_sizing_basis']} vs {r['run_sizing_basis']}; "
                f"values {r['gold_sizing_value']} / {r['run_sizing_value']})"
            )
        lines.append(
            f"| `{r['id']}` | {_cell(r['target'])} | {r['gold_tier']} | {r['run_tier']} "
            f"| {r['gold_sizing_kind']} | {r['run_sizing_kind']} "
            f"| {_cell('; '.join(issues))} |"
        )
    return "\n".join(lines) + "\n"


def render_markdown(
    gold_dir: Path,
    runs: list[Path],
    conformance: dict[Path, dict[str, str]],
    gold_facts: dict[str, Any] | None,
    gold_items: list[dict[str, Any]] | None,
    gold_cut: list[dict[str, Any]] | None = None,
) -> str:
    sections: list[str] = []
    gold_label = run_label(gold_dir)

    sections.append("# Starboard Cross-Run Comparison\n")
    sections.append(f"Gold: `{gold_label}` (`{gold_dir}`)\n")
    sections.append(f"Runs compared: {len(runs)}\n")

    # --- Conformance matrix ---
    sections.append("## Conformance Matrix\n")
    # Header
    col_labels = [run_label(r) for r in runs]
    header = "| Item | " + " | ".join(col_labels) + " |"
    sep = "|---|" + "|".join(["---"] * len(runs)) + "|"
    table_rows = [header, sep]
    for prefix, description in zip(ITEM_PREFIXES, CHECKLIST_ITEMS):
        cells = []
        for rd in runs:
            status = conformance.get(rd, {}).get(prefix, "?")
            cells.append(status)
        table_rows.append(f"| `{description}` | " + " | ".join(cells) + " |")
    sections.append("\n".join(table_rows) + "\n")

    # --- Per-run facts + catalog diffs ---
    for rd in runs:
        label = run_label(rd)
        if rd == gold_dir:
            continue  # skip gold vs itself
        run_facts = load_facts(rd)
        run_items = load_backlog_items(rd)
        sections.append(f"## Run: {label}\n")
        sections.append(_md_facts_section(gold_facts, run_facts, label))
        sections.append(_md_catalog_section(gold_items, run_items, label, gold_cut, load_backlog_cut(rd)))

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def render_json(
    gold_dir: Path,
    runs: list[Path],
    conformance: dict[Path, dict[str, str]],
    gold_facts: dict[str, Any] | None,
    gold_items: list[dict[str, Any]] | None,
    gold_cut: list[dict[str, Any]] | None = None,
) -> str:
    run_results: list[dict[str, Any]] = []
    for rd in runs:
        label = run_label(rd)
        run_facts = load_facts(rd)
        run_items = load_backlog_items(rd)
        run_results.append(
            {
                "label": label,
                "path": str(rd),
                "is_gold": rd == gold_dir,
                "facts_diff": compare_facts(gold_facts, run_facts) if (gold_facts and run_facts) else "absent",
                "catalog_diff": (
                    compare_catalog(gold_items, run_items, gold_cut, load_backlog_cut(rd))
                    if (gold_items and run_items)
                    else "absent"
                ),
                "conformance": conformance.get(rd, {}),
            }
        )
    return json.dumps(
        {
            "gold": {"label": run_label(gold_dir), "path": str(gold_dir)},
            "runs": run_results,
        },
        indent=2,
        default=str,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="compare-runs.py",
        description=textwrap.dedent(
            """\
            Compare Starboard engagement run directories against a gold run.
            Outputs Markdown (default) or JSON to stdout.
            """
        ),
    )
    parser.add_argument(
        "--gold",
        required=True,
        metavar="RUN_DIR",
        help="Gold run directory (e.g. starboard-reports/claude-opus-5-5/<run-id>)",
    )
    parser.add_argument(
        "runs",
        nargs="+",
        metavar="RUN_DIR",
        help="Run directories or glob patterns to compare (gold included if matched)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output JSON instead of Markdown",
    )
    parser.add_argument(
        "--internal",
        action="store_true",
        help="Pass --internal to run check (items 12 and 16: .clean siblings + sanitizer)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    gold_dir = Path(args.gold).expanduser().resolve()
    if not gold_dir.is_dir():
        print(f"error: gold dir not found: {gold_dir}", file=sys.stderr)
        sys.exit(2)

    all_dirs = find_runs(args.runs)
    # Always include gold in the run set
    if gold_dir not in all_dirs:
        all_dirs.insert(0, gold_dir)

    if not all_dirs:
        print("error: no run directories found", file=sys.stderr)
        sys.exit(2)

    gold_facts = load_facts(gold_dir)
    gold_items = load_backlog_items(gold_dir)
    gold_cut = load_backlog_cut(gold_dir)

    # Run conformance checks in sequence (one subprocess per run)
    conformance: dict[Path, dict[str, str]] = {}
    for rd in all_dirs:
        conformance[rd] = run_conformance_check(rd, internal=args.internal)

    sizing_warnings: list[str] = []
    for rd in all_dirs:
        if rd == gold_dir:
            continue
        run_items = load_backlog_items(rd)
        if gold_items is not None and run_items is not None:
            for rec in compare_catalog(gold_items, run_items, gold_cut, load_backlog_cut(rd)):
                for w in rec["warnings"]:
                    who = run_label(gold_dir) if w.startswith("gold ") else run_label(rd)
                    sizing_warnings.append(f"warning: {who}: {w}")
    for w in dict.fromkeys(sizing_warnings):
        print(w, file=sys.stderr)

    if args.json_output:
        print(render_json(gold_dir, all_dirs, conformance, gold_facts, gold_items, gold_cut))
    else:
        print(render_markdown(gold_dir, all_dirs, conformance, gold_facts, gold_items, gold_cut))


if __name__ == "__main__":
    main()
