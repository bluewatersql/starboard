# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Contract: the engagement layer is a composable, host-led scaffold — not a monolith.

The engagement capability is deliberately structured as a shared scaffold skill
(`starboard-engagement`) that carries the phase beats, the modular primitives, and the
doc/slide templates, plus **thin vertical** skills (`starboard-action-plan`,
`starboard-deliver`) that *compose* the scaffold rather than duplicating it. There is no
deterministic ranking kernel (`starboard_x.plan_portable` was removed) and no compute
script — the host reasons, prioritizes, validates, and writes.

This test guards that structure: the scaffold exists with its primitives + templates, the
verticals stay thin and reference the scaffold, and nothing re-acquires a compute script or
the removed kernel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SKILLS = Path(__file__).parents[1] / "skills" / "starboard"
_SCAFFOLD = _SKILLS / "starboard-engagement"
_ACTION_PLAN = _SKILLS / "starboard-action-plan"
_DELIVER = _SKILLS / "starboard-deliver"
_VERTICALS = (_ACTION_PLAN, _DELIVER)
_ALL = (_SCAFFOLD, *_VERTICALS)


@pytest.mark.unit
class TestEngagementIsGuidanceOnly:
    @pytest.mark.parametrize("skill_dir", _ALL)
    def test_no_compute_script(self, skill_dir: Path) -> None:
        assert skill_dir.is_dir(), f"missing skill {skill_dir}"
        assert not (skill_dir / "scripts").exists(), (
            f"{skill_dir.name} must be guidance-only — no scripts/ dir"
        )

    @pytest.mark.parametrize("skill_dir", _ALL)
    def test_no_removed_kernel_reference(self, skill_dir: Path) -> None:
        for md in skill_dir.rglob("*.md"):
            assert "plan_portable" not in md.read_text(encoding="utf-8"), (
                f"{md.relative_to(_SKILLS)} references the removed plan_portable kernel"
            )


@pytest.mark.unit
class TestScaffoldCarriesTheReusableAssets:
    def test_primitives_present(self) -> None:
        refs = _SCAFFOLD / "references"
        assert refs.is_dir(), "scaffold must carry references/ primitives"
        for prim in (
            "technical-review",
            "humanize",
            "scope-sanitize",
            "evidence-cite",
            "native-remediation",
            "capability-bind",
        ):
            assert (refs / f"{prim}.md").is_file(), f"missing primitive {prim}.md"

    def test_templates_present(self) -> None:
        tpl = _SCAFFOLD / "templates"
        assert tpl.is_dir(), "scaffold must carry templates/"
        assert (tpl / "cost-review-doc.md").is_file()
        assert (tpl / "deck.md").is_file()

    def test_scaffold_declares_the_beats(self) -> None:
        body = (_SCAFFOLD / "SKILL.md").read_text(encoding="utf-8")
        for beat in ("CONFIRM", "validate", "technical-review", "humanize"):
            assert beat in body, f"scaffold SKILL.md dropped the '{beat}' beat"


@pytest.mark.unit
class TestVerticalsAreThinAndCompose:
    @pytest.mark.parametrize("skill_dir", _VERTICALS)
    def test_vertical_composes_the_scaffold(self, skill_dir: Path) -> None:
        body = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "starboard-engagement" in body, (
            f"{skill_dir.name} must compose the shared scaffold (reference starboard-engagement), "
            "not re-implement the beats"
        )
