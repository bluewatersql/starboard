# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 5 (group A): a family whose only gap is a suppressed rule asks for nothing.

A suppressed rule (``suppressed:<rule_id>...``) lacks a source column; neither a
review re-run nor a re-discovery recovers it, so its family read carries no
acquisition request. Every other partial/unknown read still needs one.
"""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement.families import rule_coverage

from .test_health import CUR, EV, INTERVAL, family, health
from .test_records_phase3 import make_family
from .test_run5_group_a_families import _CODES, _IDENTITY, manifest

pytestmark = pytest.mark.unit

_REQUEST = {
    "owner_role": "operator",
    "missing": ("findings_manifest",),
    "command": "starboard review --json",
    "placeholders": (),
}


def _gov(suppressed: dict[str, str], domains: list[str], **over: Any) -> Any:
    cur = rule_coverage(
        manifest(suppressed_rules=suppressed, **over),
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
        evidence_ids=(EV,),
        reviewed_domains=domains,
    )
    return family(health(list(cur)), "governance")


# ---- health: the request ------------------------------------------------------------


def test_partial_suppression_only_family_asks_for_nothing() -> None:
    gov = _gov(_IDENTITY, ["uc", "portfolio_readiness"])
    assert (gov.assessment, gov.coverage) == ("assessed", "partial")
    assert set(gov.uncertainty) == set(_CODES)
    assert gov.acquisition_request is None


def test_unknown_suppression_only_family_asks_for_nothing() -> None:
    every = {**_IDENTITY, "table_missing_maintenance": "no rows"}
    gov = _gov(every, ["uc", "portfolio_readiness"])
    assert (gov.assessment, gov.coverage) == ("unknown", "unknown")
    assert gov.unknown_reason.startswith("suppressed:")
    assert gov.acquisition_request is None


def test_other_gaps_beside_suppression_keep_only_their_request() -> None:
    # uc not reviewed: the review request names that, never the suppression.
    gov = _gov(_IDENTITY, ["portfolio_readiness"])
    assert gov.unknown_reason == "not_reviewed:uc"
    assert gov.acquisition_request is not None
    assert gov.acquisition_request["missing"] == ("findings_manifest",)
    # PO-01 failed: the re-discovery request names only PO-01.
    gov = _gov(_IDENTITY, ["uc", "portfolio_readiness"], unavailable_queries=["PO-01"])
    assert gov.acquisition_request is not None
    assert gov.acquisition_request["missing"] == ("PO-01",)
    assert not any("suppressed" in m for m in gov.acquisition_request["missing"])


# ---- records: the allowance is narrow -------------------------------------------------


def test_record_allows_no_request_for_suppression_only_reads() -> None:
    make_family("governance", coverage="partial", uncertainty=_CODES)
    make_family(
        "governance",
        assessment="unknown",
        coverage="unknown",
        severity=None,
        unknown_reason="suppressed:portfolio_unattended_production_job",
        uncertainty=_CODES,
    )


@pytest.mark.parametrize(
    "over",
    [
        {"coverage": "partial"},  # no codes at all
        {"coverage": "partial", "uncertainty": (*_CODES, "per_job_cap_25")},
        {"coverage": "partial", "uncertainty": (*_CODES, "missing_source:PO-01")},
        {  # unknown for another reason, with suppressed codes beside it
            "assessment": "unknown",
            "coverage": "unknown",
            "severity": None,
            "unknown_reason": "not_reviewed:uc",
            "uncertainty": _CODES,
        },
        {  # suppressed reason without the codes
            "assessment": "unknown",
            "coverage": "unknown",
            "severity": None,
            "unknown_reason": "suppressed:portfolio_unattended_production_job",
        },
    ],
)
def test_record_still_requires_a_request_otherwise(over: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="needs an acquisition_request"):
        make_family("governance", **over)
    make_family("governance", **over, acquisition_request=_REQUEST)  # valid with one
