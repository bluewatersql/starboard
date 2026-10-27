# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live run 9: a family whose only gap is capped evidence asks for nothing.

``evidence_capped`` means a rule's evidence query hit its row limit. No discovery
flag lifts that cap and a review re-run reads the same capped rows, so the family
read carries no acquisition request (run 9 printed a ``starboard review`` re-run,
which the engagement skill forbids and which cannot help).
"""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement.families import rule_coverage

from .test_families import finding, manifest
from .test_health import CUR, EV, INTERVAL, family, health
from .test_records_phase3 import make_family
from .test_run5_group_a_families import _CODES

pytestmark = pytest.mark.unit

_REQUEST = {
    "owner_role": "operator",
    "missing": ("findings_manifest",),
    "command": "starboard review --json",
    "placeholders": (),
}


def _gov(*findings: dict[str, Any], domains: list[str], **over: Any) -> Any:
    cur = rule_coverage(
        manifest(*findings, **over),
        run_id=CUR,
        account_key="acme",
        workspace_id="123",
        interval=INTERVAL,
        evidence_ids=(EV,),
        reviewed_domains=domains,
    )
    return family(health(list(cur)), "governance")


_CAPPED = finding(
    "portfolio_unattended_production_job",
    "job-1",
    severity="medium",
    evidence_capped=True,
)


def test_capped_only_family_asks_for_nothing() -> None:
    gov = _gov(_CAPPED, domains=["uc", "portfolio_readiness"])
    assert (gov.assessment, gov.coverage) == ("assessed", "partial")
    assert "evidence_capped" in gov.uncertainty
    assert gov.acquisition_request is None


def test_capped_beside_a_recoverable_gap_keeps_that_request() -> None:
    # uc was not reviewed: the review re-run recovers that, so the request stays.
    gov = _gov(_CAPPED, domains=["portfolio_readiness"])
    assert gov.acquisition_request is not None


def test_record_allows_no_request_for_capped_or_suppressed_reads() -> None:
    make_family("governance", coverage="partial", uncertainty=("evidence_capped",))
    make_family(
        "governance", coverage="partial", uncertainty=(*_CODES, "evidence_capped")
    )


@pytest.mark.parametrize(
    "codes",
    [
        ("evidence_capped", "per_job_cap_25"),
        ("evidence_capped", "missing_source:PO-01"),
        ("evidence_capped", "not_reviewed:uc"),
    ],
)
def test_record_still_requires_a_request_beside_a_recoverable_gap(
    codes: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="needs an acquisition_request"):
        make_family("governance", coverage="partial", uncertainty=codes)
    make_family(
        "governance",
        coverage="partial",
        uncertainty=codes,
        acquisition_request=_REQUEST,
    )
