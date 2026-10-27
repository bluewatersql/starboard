# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for engagement run IDs and idempotency keys."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from starboard_core.engagement.run_id import (
    idempotency_key,
    is_run_id,
    new_run_id,
    parse_run_id,
)

FIXED_UUID = uuid.UUID("12345678-1234-4234-8234-123456789abc")


def test_new_run_id_format_uses_utc_date() -> None:
    # 23:30 at UTC-5 on Oct 6 is already Oct 7 in UTC.
    local = datetime(2026, 10, 6, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    rid = new_run_id(local, uuid_factory=lambda: FIXED_UUID)
    assert rid == "20261007_12345678-1234-4234-8234-123456789abc"
    assert is_run_id(rid)


def test_naive_now_is_treated_as_utc() -> None:
    rid = new_run_id(datetime(2026, 1, 2, 3, 4), uuid_factory=lambda: FIXED_UUID)
    assert rid.startswith("20260102_")


def test_two_ids_same_day_are_distinct() -> None:
    now = datetime(2026, 10, 7, tzinfo=UTC)
    assert new_run_id(now) != new_run_id(now)


def test_default_now_and_factory_valid() -> None:
    assert is_run_id(new_run_id())


def test_parse_round_trip() -> None:
    rid = new_run_id(datetime(2026, 10, 7, tzinfo=UTC), lambda: FIXED_UUID)
    assert parse_run_id(rid) == (date(2026, 10, 7), FIXED_UUID)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "20261007",
        "20261007_",
        "20261007_12345678-1234-4234-8234-123456789ABC",  # uppercase
        "20261007_12345678-1234-1234-8234-123456789abc",  # v1, not v4
        "20261007_12345678-1234-4234-c234-123456789abc",  # bad variant
        "20261307_12345678-1234-4234-8234-123456789abc",  # month 13
        "20260230_12345678-1234-4234-8234-123456789abc",  # Feb 30
        "2026107_12345678-1234-4234-8234-123456789abc",  # short date
        "20261007_12345678123442348234123456789abc",  # no dashes
        " 20261007_12345678-1234-4234-8234-123456789abc",
        "20261007_12345678-1234-4234-8234-123456789abc\n",
        "../20261007_12345678-1234-4234-8234-123456789abc",
    ],
)
def test_invalid_ids_rejected(bad: str) -> None:
    assert not is_run_id(bad)
    with pytest.raises(ValueError):
        parse_run_id(bad)


def test_non_string_is_not_run_id() -> None:
    assert not is_run_id(None)  # type: ignore[arg-type]


def test_idempotency_key_deterministic_and_prefixed() -> None:
    rid = "20261007_12345678-1234-4234-8234-123456789abc"
    k1 = idempotency_key(rid, "folder", "acct-1")
    k2 = idempotency_key(rid, "folder", "acct-1")
    assert k1 == k2
    assert k1.startswith("sbk1_")
    assert len(k1) == len("sbk1_") + 64


def test_idempotency_key_known_vector_is_stable() -> None:
    # Pin the exact value so the derivation can never silently change.
    rid = "20261007_12345678-1234-4234-8234-123456789abc"
    assert (
        idempotency_key(rid, "a")
        == "sbk1_40a986354d766529d0ab773ede6aec39c0b04467758c134038c36fbedccbf536"
    )
    assert idempotency_key(rid) != idempotency_key(rid, "")


def test_idempotency_key_unambiguous_joining() -> None:
    rid = "20261007_12345678-1234-4234-8234-123456789abc"
    assert idempotency_key(rid, "ab", "c") != idempotency_key(rid, "a", "bc")
    assert idempotency_key(rid, "a|b") != idempotency_key(rid, "a", "b")
    assert idempotency_key(rid, "a", "b") != idempotency_key(rid, "b", "a")


def test_idempotency_key_differs_by_run_id() -> None:
    a = new_run_id()
    b = new_run_id()
    assert idempotency_key(a, "x") != idempotency_key(b, "x")


def test_idempotency_key_rejects_bad_run_id() -> None:
    with pytest.raises(ValueError):
        idempotency_key("not-a-run-id", "x")


def test_idempotency_key_handles_unicode() -> None:
    rid = "20261007_12345678-1234-4234-8234-123456789abc"
    assert idempotency_key(rid, "é") != idempotency_key(rid, "e")
