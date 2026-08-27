# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the validator council (Phase-3 D1c / D-3.2).

Drives the council with a deterministic **fake** model client (never a live
model): proves it gates candidate findings, is deterministic under a fixed seed,
votes across a model-ensemble, degrades to single-model self-critique, and — the
load-bearing spend guardrail — never exceeds its ``max_passes`` model-call
ceiling.
"""

from __future__ import annotations

import asyncio

import pytest
from starboard.tools.services.validator_council import (
    MAX_PASSES_CEILING,
    CouncilConfig,
    CritiqueRequest,
    ValidatorCouncil,
    Verdict,
)
from starboard_core.domain.models.finding import Effort, Finding, Severity
from starboard_core.domain.models.review import ReviewFinding


def _rf(fid: str) -> ReviewFinding:
    return ReviewFinding(
        finding=Finding(
            id=fid,
            severity=Severity.HIGH,
            category="jobs",
            summary=f"summary of {fid}",
            rationale="why it matters",
            current_state="observed bad state",
            suggested_fix="do the good thing",
            impact=3,
            effort=Effort.S,
        )
    )


class _FakeModel:
    """Deterministic fake council model — verdict from an injected policy."""

    def __init__(self, model_id: str, policy) -> None:
        self._model_id = model_id
        self._policy = policy
        self.calls: list[tuple[str, int]] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    async def critique(
        self, request: CritiqueRequest, *, seed: int
    ) -> tuple[Verdict, float]:
        self.calls.append((request.finding_id, seed))
        if callable(self._policy):
            return self._policy(request, seed)
        return self._policy


def _run(coro):
    return asyncio.run(coro)


_KEEP = (Verdict.KEEP, 0.9)
_DROP = (Verdict.DROP, 0.9)


@pytest.mark.unit
class TestSingleModelCouncil:
    def test_keeps_findings_the_model_approves(self) -> None:
        council = ValidatorCouncil(
            [_FakeModel("m1", _KEEP)],
            config=CouncilConfig(model_ids=("m1",)),
        )
        result = _run(council.review([_rf("a"), _rf("b")]))
        assert [rf.finding.id for rf in result.kept] == ["a", "b"]
        assert result.suppressed_count == 0

    def test_suppresses_findings_the_model_rejects(self) -> None:
        council = ValidatorCouncil(
            [_FakeModel("m1", _DROP)],
            config=CouncilConfig(model_ids=("m1",)),
        )
        result = _run(council.review([_rf("a")]))
        assert result.kept_count == 0
        assert [rf.finding.id for rf in result.suppressed] == ["a"]

    def test_single_model_is_one_pass_per_finding(self) -> None:
        # A single model is unanimous by definition → consensus stops at pass 0.
        model = _FakeModel("m1", _KEEP)
        council = ValidatorCouncil(
            [model], config=CouncilConfig(model_ids=("m1",), max_passes=3)
        )
        result = _run(council.review([_rf("a")]))
        assert result.finding_verdicts[0].passes_used == 1
        assert result.total_model_calls == 1

    def test_critique_request_carries_no_evidence_rows(self) -> None:
        # The payload sent to a model is paraphrased finding text only.
        request = CritiqueRequest.from_finding(_rf("a"))
        assert not hasattr(request, "row")
        assert request.finding_id == "a"
        assert request.summary == "summary of a"


@pytest.mark.unit
class TestDeterminism:
    def test_same_seed_same_result(self) -> None:
        def policy(request: CritiqueRequest, seed: int) -> tuple[Verdict, float]:
            # Deterministic on finding id + seed.
            keep = (len(request.finding_id) + seed) % 2 == 0
            return (Verdict.KEEP, 0.7) if keep else (Verdict.DROP, 0.7)

        def build() -> ValidatorCouncil:
            return ValidatorCouncil(
                [_FakeModel("m1", policy), _FakeModel("m2", policy)],
                config=CouncilConfig(model_ids=("m1", "m2"), seed=42),
            )

        findings = [_rf("aa"), _rf("bbb"), _rf("cccc")]
        first = _run(build().review(findings))
        second = _run(build().review(findings))
        assert [rf.finding.id for rf in first.kept] == [
            rf.finding.id for rf in second.kept
        ]
        assert first.total_model_calls == second.total_model_calls


@pytest.mark.unit
class TestEnsembleVoting:
    def test_split_vote_keeps_at_default_quorum(self) -> None:
        # 1 keep / 1 drop → ratio 0.5 >= default quorum 0.5 → kept.
        council = ValidatorCouncil(
            [_FakeModel("keep", _KEEP), _FakeModel("drop", _DROP)],
            config=CouncilConfig(model_ids=("keep", "drop")),
        )
        result = _run(council.review([_rf("a")]))
        assert result.kept_count == 1
        assert result.finding_verdicts[0].keep_ratio == 0.5

    def test_split_vote_dropped_at_strict_quorum(self) -> None:
        council = ValidatorCouncil(
            [_FakeModel("keep", _KEEP), _FakeModel("drop", _DROP)],
            config=CouncilConfig(model_ids=("keep", "drop"), keep_quorum=1.0),
        )
        result = _run(council.review([_rf("a")]))
        assert result.suppressed_count == 1


@pytest.mark.unit
class TestBoundedSpend:
    def test_calls_never_exceed_ceiling_when_no_consensus(self) -> None:
        # Two models permanently disagree → no consensus → all passes run.
        council = ValidatorCouncil(
            [_FakeModel("keep", _KEEP), _FakeModel("drop", _DROP)],
            config=CouncilConfig(model_ids=("keep", "drop"), max_passes=3),
        )
        result = _run(council.review([_rf("a"), _rf("b")]))
        # ceiling = max_passes(3) × models(2) × findings(2) = 12
        assert result.max_possible_calls == 12
        assert result.total_model_calls == 12
        assert result.total_model_calls <= result.max_possible_calls
        assert all(v.passes_used == 3 for v in result.finding_verdicts)

    def test_consensus_stops_early_under_ceiling(self) -> None:
        council = ValidatorCouncil(
            [_FakeModel("m1", _KEEP), _FakeModel("m2", _KEEP)],
            config=CouncilConfig(model_ids=("m1", "m2"), max_passes=4),
        )
        result = _run(council.review([_rf("a")]))
        # Unanimous keep on pass 0 → 2 calls, well under the 8-call ceiling.
        assert result.total_model_calls == 2
        assert result.max_possible_calls == 8

    def test_max_passes_ceiling_is_enforced_by_config(self) -> None:
        with pytest.raises(ValueError):
            CouncilConfig(max_passes=MAX_PASSES_CEILING + 1)
        with pytest.raises(ValueError):
            CouncilConfig(max_passes=0)


@pytest.mark.unit
class TestCouncilConfig:
    def test_model_ids_not_hard_coded_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "STARBOARD_REVIEW_COUNCIL_MODELS",
            "system.ai.claude-opus-4-8[1m], claude-fable-5",
        )
        monkeypatch.setenv("STARBOARD_REVIEW_COUNCIL_MAX_PASSES", "3")
        monkeypatch.setenv("STARBOARD_REVIEW_COUNCIL_SEED", "7")
        config = CouncilConfig.from_env()
        assert config.model_ids == (
            "system.ai.claude-opus-4-8[1m]",
            "claude-fable-5",
        )
        assert config.ensemble_size == 2
        assert config.max_passes == 3
        assert config.seed == 7

    def test_from_env_falls_back_to_default_model(self, monkeypatch) -> None:
        monkeypatch.delenv("STARBOARD_REVIEW_COUNCIL_MODELS", raising=False)
        monkeypatch.delenv("STARBOARD_REVIEW_COUNCIL_MODEL", raising=False)
        config = CouncilConfig.from_env(default_model="my-gateway-model")
        assert config.model_ids == ("my-gateway-model",)

    def test_env_max_passes_clamped_to_ceiling(self, monkeypatch) -> None:
        monkeypatch.setenv("STARBOARD_REVIEW_COUNCIL_MAX_PASSES", "999")
        config = CouncilConfig.from_env(default_model="m")
        assert config.max_passes == MAX_PASSES_CEILING

    def test_single_model_string_coerced(self) -> None:
        config = CouncilConfig(model_ids="only-one")
        assert config.model_ids == ("only-one",)

    def test_requires_at_least_one_model(self) -> None:
        with pytest.raises(ValueError):
            CouncilConfig(model_ids=())
