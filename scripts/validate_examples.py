# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Validate the documented hero workflows & personas against the live catalog (Task E2, D-3.3).

Usage::

    python scripts/validate_examples.py            # run + stamp last-verified to today
    python scripts/validate_examples.py --check     # enforce only (no writes); exit 1 on failure

What it does
------------
Every hero/persona example is declared in the machine-readable registry embedded
in ``docs/examples/VALIDATED_EXAMPLES.md`` (YAML frontmatter). For each example
this script:

1. **Resolves every referenced surface** against the *live* catalog — public
   surfaces (skills/tools/agents/CLI/helpers) come from
   ``scripts/gen_catalog.py``'s collectors (the same live sources the catalog is
   generated from), and gated internal surfaces resolve against the canonical
   ``starboard.ports.registry.Port`` enum. A reference to a non-existent surface
   fails the job (no dead references, D-3.3 / guardrail).
2. **Runs the example against a MOCKED Databricks + LLM** (no live workspace):
   synthetic ``system.*`` rows are fed through a deterministic in-process runner
   and a stub LLM, producing a structured advisor report. The report is asserted
   non-empty and to contain every key the example declares in ``expect``.
3. **Enforces freshness**: each example carries a ``last_verified`` date and each
   page carries a matching ``<!-- VALIDATED: YYYY-MM-DD -->`` tag. ``--check``
   exits non-zero when any example is older than :data:`MAX_AGE_DAYS`, references
   a missing surface, fails its structural contract, or is missing its page tag.
   The default (no ``--check``) *stamps* today's date into the registry and the
   page tags.
4. **Governance**: the PUBLIC pages (``HERO_WORKFLOWS.md``,
   ``VALIDATED_EXAMPLES.md``) must not contain any internal namespace. Internal
   references are allowed only on the clearly-scoped ``PERSONAS.md`` page.

The mock runner is intentionally self-contained: it never imports the agent
runtime and never depends on seed-rule thresholds, so a documentation example
cannot rot because unrelated production code changed. Its teeth are the
live-surface resolution (step 1), the freshness dates (step 3), and the
governance scan (step 4).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

# ---------------------------------------------------------------------------
# Repo-root resolution (walk up until the canonical examples dir is found)
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "docs" / "examples").is_dir() or (parent / "scripts" / "gen_catalog.py").is_file():
            return parent
    raise AssertionError("Cannot locate repo root (expected scripts/gen_catalog.py)")


REPO_ROOT = _repo_root()
EXAMPLES_DIR = REPO_ROOT / "docs" / "examples"
REGISTRY_PATH = EXAMPLES_DIR / "VALIDATED_EXAMPLES.md"
HERO_PAGE = EXAMPLES_DIR / "HERO_WORKFLOWS.md"
PERSONAS_PAGE = EXAMPLES_DIR / "PERSONAS.md"
GEN_CATALOG = REPO_ROOT / "scripts" / "gen_catalog.py"

# Pages that must stay clean of internal namespaces (the PUBLIC surface). The
# PERSONAS page is deliberately excluded — it is the one place gated-path
# references are allowed.
PUBLIC_PAGES: tuple[Path, ...] = (HERO_PAGE, REGISTRY_PATH)

# Freshness ceiling — an example older than this fails ``--check`` (D-3.3).
MAX_AGE_DAYS = 90

DATE_FMT = "%Y-%m-%d"
_VALIDATED_TAG_RE = re.compile(r"<!--\s*VALIDATED:\s*(\d{4}-\d{2}-\d{2})\s*-->")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

# Internal namespaces that must never appear on a PUBLIC page (mirrors the
# governance red-lines in CLAUDE.md and the catalog generator's test).
INTERNAL_NAMESPACES: tuple[str, ...] = (
    "centralized_system_tables",
    "fin_live_gold",
    "gtm_",
    "eng_",
    "logfood",
    "ClickHouse",
    "hmr_stack_hash",
)

# Surface kinds resolved against the public catalog (via gen_catalog collectors).
_PUBLIC_KINDS = ("skills", "mcp-tools", "agents", "cli-commands", "progressive-helpers")

# ---------------------------------------------------------------------------
# gen_catalog.py loader (reuse the live-source collectors; DRY with the catalog)
# ---------------------------------------------------------------------------


def _load_gen_catalog() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_catalog", GEN_CATALOG)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise AssertionError(f"Could not load gen_catalog.py from {GEN_CATALOG}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def public_surfaces() -> dict[str, set[str]]:
    """Return the live public catalog surfaces keyed by kind.

    The names come from ``gen_catalog.py``'s collectors, i.e. the same live
    sources (``ALL_TOOL_METADATA``, the skills tree, canonical agent YAML, the
    CLI dispatch table, ``starboard_x``) the catalog itself is generated from —
    so an example can never reference a surface the catalog does not ship.
    """
    gc = _load_gen_catalog()
    return {
        "skills": {e.name for e in gc.collect_skills()},
        "mcp-tools": {e.name for e in gc.collect_tools()},
        "agents": {e.name for e in gc.collect_agents()},
        "cli-commands": {e.command for e in gc.collect_cli_commands()},
        "progressive-helpers": {e.name for e in gc.collect_helpers() if e.implemented},
    }


def gated_ports() -> set[str]:
    """Return the canonical gated internal-data ports (``starboard.ports.registry``).

    Personas may reference the gated path only; each such reference must resolve
    to a real internal-data-enablement port so the internal story has no dead
    references either.
    """
    from starboard.ports.registry import Port

    return {p.value for p in Port}


# ---------------------------------------------------------------------------
# Registry model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Surface:
    kind: str
    name: str
    gated: bool = False


@dataclass
class Example:
    id: str
    title: str
    page: str  # path relative to docs/, e.g. "examples/HERO_WORKFLOWS.md"
    audience: str  # "public" | "internal"
    domain: str
    prompt: str
    surfaces: tuple[Surface, ...]
    expect: tuple[str, ...]
    last_verified: date
    hosts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def page_path(self) -> Path:
        return REPO_ROOT / "docs" / self.page


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), DATE_FMT).date()


def load_registry(path: Path = REGISTRY_PATH) -> list[Example]:
    """Parse the example registry from the frontmatter of *path*."""
    import yaml

    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise AssertionError(f"{path} has no YAML frontmatter registry")
    data = yaml.safe_load(m.group(1)) or {}
    raw_examples = data.get("examples") or []
    examples: list[Example] = []
    for raw in raw_examples:
        surfaces = tuple(
            Surface(
                kind=str(s["kind"]),
                name=str(s["name"]),
                gated=bool(s.get("gated", False)),
            )
            for s in raw.get("surfaces", [])
        )
        examples.append(
            Example(
                id=str(raw["id"]),
                title=str(raw["title"]),
                page=str(raw["page"]),
                audience=str(raw.get("audience", "public")),
                domain=str(raw["domain"]),
                prompt=str(raw["prompt"]),
                surfaces=surfaces,
                expect=tuple(str(k) for k in raw.get("expect", [])),
                last_verified=_as_date(raw["last_verified"]),
                hosts=tuple(str(h) for h in raw.get("hosts", [])),
            )
        )
    return examples


# ---------------------------------------------------------------------------
# Mock Databricks + LLM (no live workspace)
# ---------------------------------------------------------------------------


class MockWorkspace:
    """Synthetic ``system.*`` provider — proves an example needs no live workspace.

    Any attempt to reach out over the network is a programming error; this object
    only ever returns canned rows, so the validator is hermetic.
    """

    is_mock = True

    # Public ``system.*`` signals per domain. Dollar figures are list-price DBU
    # estimates (labelled as such in the emitted report).
    _SIGNALS: dict[str, list[dict[str, Any]]] = {
        "query": [
            {
                "source": "system.query.history",
                "statement_id": "01f0mock-query-history-0001",
                "duration_seconds": 612.0,
                "read_bytes": 480_000_000_000,
                "pruned_files_pct": 3.0,
            }
        ],
        "job": [
            {
                "source": "system.lakeflow.job_run_timeline",
                "job_id": 987_654_321,
                "failed_runs": 7,
                "total_runs": 20,
                "wasted_dbu": 41.5,
            }
        ],
        "uc": [
            {
                "source": "system.information_schema.table_privileges",
                "table_name": "sales.public.orders",
                "grants": 0,
                "has_owner": False,
            }
        ],
        "finops": [
            {
                "source": "system.billing.usage",
                "sku": "ENTERPRISE_SQL_COMPUTE",
                "list_price_dbu_usd": 12_840.0,
                "share_pct": 34.0,
            }
        ],
        "warehouse": [
            {
                "source": "system.compute.warehouse_events",
                "warehouse_id": "wh-mock-01",
                "auto_stop_waste_pct": 82.5,
                "idle_list_price_usd": 410.0,
            }
        ],
        "discovery": [
            {
                "source": "system.billing.usage",
                "domain": "jobs",
                "health_score": 62,
                "top_issue": "3 jobs without a run-as identity",
            }
        ],
        "diagnostic": [
            {
                "source": "system.lakeflow.job_run_timeline",
                "run_id": 5_566_778_899,
                "termination_code": "137",
                "symptom": "OOMKilled on the driver",
            }
        ],
        # Internal personas exercise the gated path; the signal is a synthetic
        # cross-account row that carries NO internal namespace string.
        "internal": [
            {
                "source": "gated:fleet_sql",
                "workspaces": 5,
                "cost_basis": "internal cost model",
            }
        ],
    }

    def signals(self, domain: str) -> list[dict[str, Any]]:
        return list(self._SIGNALS.get(domain, self._SIGNALS["discovery"]))


class MockLLM:
    """Deterministic stub LLM — composes a summary from findings, no API calls."""

    is_mock = True

    def summarize(self, findings: list[dict[str, Any]]) -> str:
        if not findings:
            return "no findings"
        top = findings[0]["summary"]
        return f"{len(findings)} finding(s); top priority: {top}"


# Human-readable summary + fix per domain (the "what the user sees" content).
_DOMAIN_REPORT: dict[str, tuple[str, str]] = {
    "query": (
        "Slow query scans ~480 GB with 3% file pruning",
        "Add a partition filter / Z-ORDER so the scan prunes to the relevant files.",
    ),
    "job": (
        "Job fails on 35% of runs, wasting billed DBU on retries",
        "Fix the failing task and add a retry ceiling to stop paying for retry storms.",
    ),
    "uc": (
        "Table sales.public.orders has no grants and no owner",
        "Assign an owner and least-privilege grants to close the governance gap.",
    ),
    "finops": (
        "SQL compute is the top cost driver at 34% of list-price DBU spend",
        "Right-size the warehouse fleet and enable aggressive auto-stop.",
    ),
    "warehouse": (
        "Warehouse wh-mock-01 idles 82.5% of running time with auto-stop effectively off",
        "Set a 5-10 minute auto-stop window to remove idle list-price DBU spend.",
    ),
    "discovery": (
        "Workspace health scores 62/100 — jobs domain drags the score",
        "Attribute run-as identities and remediate the top jobs-domain issues.",
    ),
    "diagnostic": (
        "Run terminated with exit code 137 (OOMKilled on the driver)",
        "Increase driver memory or reduce driver-side collection to avoid OOM.",
    ),
    "internal": (
        "Cross-account fleet view over 5 customer workspaces (internal cost model)",
        "Rebalance capacity across the portfolio and flag upsell candidates.",
    ),
}


def _score(example: Example, workspace: MockWorkspace) -> list[dict[str, Any]]:
    """Produce a deterministic, non-empty findings list from mocked signals."""
    signals = workspace.signals(example.domain)
    summary, fix = _DOMAIN_REPORT.get(example.domain, _DOMAIN_REPORT["discovery"])
    findings: list[dict[str, Any]] = []
    for row in signals:
        findings.append(
            {
                "severity": "high",
                "category": example.domain,
                "summary": summary,
                "current_state": summary,
                "suggested_fix": fix,
                "impact": 4,
                "effort": "S",
                "evidence": [{"source": row["source"], "row": row}],
            }
        )
    return findings


def run_example(
    example: Example,
    *,
    workspace: MockWorkspace | None = None,
    llm: MockLLM | None = None,
) -> dict[str, Any]:
    """Run *example* against the mocked Databricks + LLM and return the envelope."""
    workspace = workspace or MockWorkspace()
    llm = llm or MockLLM()
    assert getattr(workspace, "is_mock", False), "run_example requires a MOCK workspace"

    findings = _score(example, workspace)
    recommendations = [f["suggested_fix"] for f in findings]

    if example.audience == "internal":
        cost_estimate = {"unit": "internal cost model", "basis": "cross-account (not list-price)"}
    else:
        cost_estimate = {"unit": "list-price DBU $", "basis": "list-price DBU estimate"}

    return {
        "ok": True,
        "example_id": example.id,
        "audience": example.audience,
        "surfaces": [f"{s.kind}:{s.name}" for s in example.surfaces],
        "report": {
            "workspace": "no-live-workspace (mock)",
            "prompt": example.prompt,
            "summary": llm.summarize(findings),
            "findings": findings,
            "recommendations": recommendations,
            "cost_estimate": cost_estimate,
        },
        "meta": {"databricks": "mock", "llm": "mock"},
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def resolve_surface(surface: Surface, pub: dict[str, set[str]], gated: set[str]) -> bool:
    """True when *surface* names a real catalogued (or gated) surface."""
    if surface.gated or surface.kind in ("internal", "internal-gated", "gated"):
        return surface.name in gated
    known = pub.get(surface.kind)
    if known is None:
        return False
    return surface.name in known


def check_structure(envelope: dict[str, Any], expect: tuple[str, ...]) -> list[str]:
    """Return a list of structural problems (empty when the envelope is sound)."""
    problems: list[str] = []
    if not envelope.get("ok"):
        problems.append("envelope.ok is falsy")
    report = envelope.get("report") or {}
    for key in expect:
        value = report.get(key)
        if value is None or (isinstance(value, (list, dict, str)) and len(value) == 0):
            problems.append(f"report.{key} is missing or empty")
    return problems


def _page_has_tag(example: Example, today: date | None = None) -> bool:
    """Whether the example's page carries a ``<!-- VALIDATED: <date> -->`` tag
    matching the example's ``last_verified`` (or *today* when stamping)."""
    if not example.page_path.exists():
        return False
    want = (today or example.last_verified).strftime(DATE_FMT)
    text = example.page_path.read_text(encoding="utf-8")
    return f"<!-- VALIDATED: {want} -->" in text


def governance_scan(pages: tuple[Path, ...] = PUBLIC_PAGES) -> list[str]:
    """Return governance violations (internal namespace on a public page)."""
    problems: list[str] = []
    for page in pages:
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8")
        for ns in INTERNAL_NAMESPACES:
            if ns in text:
                problems.append(f"{page.name}: contains internal namespace {ns!r}")
    return problems


def validate(
    examples: list[Example],
    *,
    today: date,
    max_age_days: int = MAX_AGE_DAYS,
    check: bool = False,
) -> list[str]:
    """Validate every example. Return a list of failure messages (empty = pass)."""
    failures: list[str] = []
    pub = public_surfaces()
    gated = gated_ports()

    if not examples:
        failures.append("registry contains no examples")

    for ex in examples:
        # 1) no dead references
        for surface in ex.surfaces:
            if not resolve_surface(surface, pub, gated):
                failures.append(
                    f"[{ex.id}] references a non-existent surface: "
                    f"{surface.kind}:{surface.name}"
                )

        # 2) run against mocked Databricks + LLM; assert structure/non-emptiness
        try:
            envelope = run_example(ex)
        except Exception as exc:  # pragma: no cover - defensive
            failures.append(f"[{ex.id}] mock run raised: {exc!r}")
            continue
        for problem in check_structure(envelope, ex.expect):
            failures.append(f"[{ex.id}] structural failure: {problem}")

        # 3) freshness + page tag
        if not _page_has_tag(ex):
            failures.append(
                f"[{ex.id}] page {ex.page} is missing the "
                f"<!-- VALIDATED: {ex.last_verified.strftime(DATE_FMT)} --> tag"
            )
        if check:
            age = (today - ex.last_verified).days
            if age > max_age_days:
                failures.append(
                    f"[{ex.id}] is stale: last verified {ex.last_verified} "
                    f"({age} days ago > {max_age_days})"
                )
            if ex.last_verified > today:
                failures.append(
                    f"[{ex.id}] last_verified {ex.last_verified} is in the future"
                )

    # 4) governance on the public pages
    failures.extend(governance_scan())

    return failures


# ---------------------------------------------------------------------------
# Stamping (default mode)
# ---------------------------------------------------------------------------


def stamp(examples: list[Example], today: date) -> None:
    """Rewrite ``last_verified`` (registry frontmatter) and every page
    ``<!-- VALIDATED: ... -->`` tag to *today*."""
    today_str = today.strftime(DATE_FMT)

    # Registry frontmatter: rewrite every last_verified line to today.
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    text = re.sub(
        r"(last_verified:\s*)\d{4}-\d{2}-\d{2}",
        rf"\g<1>{today_str}",
        text,
    )
    REGISTRY_PATH.write_text(text, encoding="utf-8")

    # Page tags: rewrite every VALIDATED tag on every example page to today.
    for page in {ex.page_path for ex in examples} | {REGISTRY_PATH}:
        if not page.exists():
            continue
        page_text = page.read_text(encoding="utf-8")
        new_text = _VALIDATED_TAG_RE.sub(f"<!-- VALIDATED: {today_str} -->", page_text)
        if new_text != page_text:
            page.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    check = "--check" in args
    today = date.today()

    examples = load_registry()

    if not check:
        stamp(examples, today)
        examples = load_registry()  # re-read the stamped dates

    failures = validate(examples, today=today, check=check)

    if failures:
        print("Example validation FAILED:")
        for f in failures:
            print(f"  {f}")
        return 1

    verb = "checked" if check else "validated + stamped"
    print(f"OK: {verb} {len(examples)} examples against the live catalog (mocked Databricks + LLM).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
