# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 5 (group A): a rule the review suppressed is not evaluated.

A rule whose ``requires_column`` the source does not carry (the internal mirror
has no ``run_as``) is listed in the manifest's ``suppressed_rules``; family rule
coverage must not count it, and must say why (``suppressed:<rule_id>:...``).
"""

from __future__ import annotations

import pytest

from .test_families import manifest, rc
from .test_health import CUR, EV, INTERVAL, family, health

pytestmark = pytest.mark.unit

_REASON = (
    "required evidence column 'run_as' is unavailable in C-J01 (no row carries it); "
    "rule not evaluated"
)
_IDENTITY = {
    "portfolio_untracked_production_consumption": _REASON.replace("C-J01", "C-B01"),
    "portfolio_unattended_production_job": _REASON,
}
_CODES = (
    "suppressed:portfolio_unattended_production_job:missing_column:run_as",
    "suppressed:portfolio_untracked_production_consumption:missing_column:run_as",
)


def test_partly_suppressed_family_is_partial_with_the_reason() -> None:
    m = manifest(suppressed_rules=_IDENTITY)
    out = rc(m, reviewed_domains=["uc", "portfolio_readiness"])
    gov = out[("governance", "rules_evaluated")]
    assert gov.state == "measured" and gov.value == 1.0  # only table_missing_maintenance
    assert gov.coverage == "partial"
    assert set(_CODES) <= set(gov.uncertainty)
    # A suppressed rule's evidence ran: it is no missing source.
    assert not any(c.startswith("missing_source:") for c in gov.uncertainty)


def test_fully_suppressed_family_is_unknown_never_healthy() -> None:
    m = manifest(suppressed_rules=_IDENTITY)
    out = rc(m, reviewed_domains=["portfolio_readiness"])
    gov = out[("governance", "rules_evaluated")]
    assert gov.state == "unknown" and gov.value is None
    # The portfolio rules are suppressed; uc was not reviewed.
    assert gov.unknown_reason == "not_reviewed:uc"
    assert set(_CODES) <= set(gov.uncertainty)


def test_every_rule_suppressed_names_the_suppression() -> None:
    m = manifest(
        suppressed_rules={**_IDENTITY, "table_missing_maintenance": "no PO-01 rows"}
    )
    out = rc(m, reviewed_domains=["uc", "portfolio_readiness"])
    gov = out[("governance", "rules_evaluated")]
    assert gov.state == "unknown"
    assert gov.unknown_reason == (
        "suppressed:portfolio_unattended_production_job,"
        "portfolio_untracked_production_consumption,table_missing_maintenance"
    )
    assert "suppressed:table_missing_maintenance" in gov.uncertainty


def test_health_read_does_not_call_a_suppressed_family_healthy() -> None:
    def gov_read(suppressed: dict[str, str], domains: list[str]):  # type: ignore[no-untyped-def]
        from starboard_core.engagement.families import rule_coverage

        cur = rule_coverage(
            manifest(suppressed_rules=suppressed),
            run_id=CUR,
            account_key="acme",
            workspace_id="123",
            interval=INTERVAL,
            evidence_ids=(EV,),
            reviewed_domains=domains,
        )
        return family(health(list(cur)), "governance")

    whole = gov_read({}, ["uc", "portfolio_readiness"])
    assert (whole.assessment, whole.coverage) == ("assessed", "complete")
    part = gov_read(_IDENTITY, ["uc", "portfolio_readiness"])
    assert (part.assessment, part.coverage) == ("assessed", "partial")
    assert set(_CODES) <= set(part.uncertainty)
    none = gov_read(_IDENTITY, ["portfolio_readiness"])
    assert (none.assessment, none.coverage, none.severity) == ("unknown", "unknown", None)
    assert set(_CODES) <= set(none.uncertainty)


def test_suppressed_rules_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="suppressed_rules"):
        rc(manifest(suppressed_rules=["portfolio_unattended_production_job"]))


def test_manifest_without_suppressed_rules_is_unchanged() -> None:
    out = rc(manifest(), reviewed_domains=["uc", "portfolio_readiness"])
    gov = out[("governance", "rules_evaluated")]
    assert (gov.value, gov.coverage, gov.uncertainty) == (3.0, "complete", ())
