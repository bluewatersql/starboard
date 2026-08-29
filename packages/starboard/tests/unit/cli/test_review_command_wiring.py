# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the validator-council production wiring in ``starboard review`` (O3).

Verifies that ``_build_validator()`` in :mod:`starboard.cli.cli.review_command`:

* returns ``None`` when ``--validate`` is not passed (opt-in gate; no council
  without the flag, even when ``STARBOARD_REVIEW_COUNCIL_MODELS`` is set);
* builds a :class:`ValidatorCouncil` with exactly N adapters when N model ids
  are configured (``STARBOARD_REVIEW_COUNCIL_MODELS`` comma-separated list); and
* degrades safely to ``None`` — never raising — when ``create_llm_client``
  fails (e.g. offline, bad credentials), so the review proceeds without
  council validation.

No live model is ever called: ``create_llm_client`` is replaced with a fake
that returns a minimal stub. The council structure (adapter count / ensemble
size) is verified via the public :class:`~starboard.tools.services.validator_council.CouncilConfig`
attributes rather than private internals.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from unittest import mock

import pytest
from rich.console import Console
from starboard.tools.services.validator_council import ValidatorCouncil

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _args(*, validate: bool = False) -> argparse.Namespace:
    """Minimal ``argparse.Namespace`` for ``_build_validator``."""
    ns = argparse.Namespace()
    ns.validate = validate
    return ns


def _config(*, llm_model: str = "test-model") -> SimpleNamespace:
    """Minimal config-like object with ``llm_model``."""
    return SimpleNamespace(llm_model=llm_model)


def _err() -> Console:
    return Console(stderr=True)


class _StubLLMClient:
    """Minimal stub satisfying the ``BaseLLMClient`` duck type for wiring tests."""

    async def json_response(self, *args, **kwargs) -> dict:  # noqa: ARG002
        return {"verdict": "keep", "confidence": 0.9}


def _patched_create_llm_client(stub: _StubLLMClient | None = None):
    """Return a ``mock.patch`` context that replaces ``create_llm_client``."""
    if stub is None:
        stub = _StubLLMClient()
    return mock.patch(
        "starboard.adapters.llm.create_llm_client", return_value=stub
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildValidatorFlag:
    """The council is opt-in: ``--validate`` must be set to build it."""

    def test_returns_none_without_validate_flag(self) -> None:
        from starboard.cli.cli.review_command import _build_validator

        result = _build_validator(_args(validate=False), _config(), _err())
        assert result is None

    def test_returns_none_without_flag_even_when_env_var_set(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("STARBOARD_REVIEW_COUNCIL_MODELS", "model-a,model-b")
        from starboard.cli.cli.review_command import _build_validator

        result = _build_validator(_args(validate=False), _config(), _err())
        assert result is None


@pytest.mark.unit
class TestBuildValidatorCouncilFromEnv:
    """When ``--validate`` is set, the council is built from ``STARBOARD_REVIEW_COUNCIL_MODELS``."""

    def test_builds_council_with_two_adapters(self, monkeypatch) -> None:
        monkeypatch.setenv("STARBOARD_REVIEW_COUNCIL_MODELS", "model-x,model-y")
        from starboard.cli.cli.review_command import _build_validator

        with _patched_create_llm_client():
            result = _build_validator(_args(validate=True), _config(), _err())

        assert isinstance(result, ValidatorCouncil)
        assert result._config.ensemble_size == 2
        assert set(result._config.model_ids) == {"model-x", "model-y"}

    def test_builds_council_with_single_adapter(self, monkeypatch) -> None:
        monkeypatch.setenv("STARBOARD_REVIEW_COUNCIL_MODELS", "only-model")
        from starboard.cli.cli.review_command import _build_validator

        with _patched_create_llm_client():
            result = _build_validator(_args(validate=True), _config(), _err())

        assert isinstance(result, ValidatorCouncil)
        assert result._config.ensemble_size == 1
        assert result._config.model_ids == ("only-model",)

    def test_ensemble_size_matches_configured_model_count(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv(
            "STARBOARD_REVIEW_COUNCIL_MODELS", "a, b, c"
        )
        from starboard.cli.cli.review_command import _build_validator

        with _patched_create_llm_client():
            result = _build_validator(_args(validate=True), _config(), _err())

        assert isinstance(result, ValidatorCouncil)
        # Bounded ceiling invariant: max_possible_calls == max_passes × N × findings.
        # With N=3 and default max_passes=2, ceiling for 1 finding is 6.
        assert result._config.ensemble_size == 3

    def test_uses_config_llm_model_as_default_when_env_unset(
        self, monkeypatch
    ) -> None:
        monkeypatch.delenv("STARBOARD_REVIEW_COUNCIL_MODELS", raising=False)
        monkeypatch.delenv("STARBOARD_REVIEW_COUNCIL_MODEL", raising=False)
        from starboard.cli.cli.review_command import _build_validator

        with _patched_create_llm_client():
            result = _build_validator(
                _args(validate=True),
                _config(llm_model="gateway-model-xyz"),
                _err(),
            )

        assert isinstance(result, ValidatorCouncil)
        assert result._config.model_ids == ("gateway-model-xyz",)


@pytest.mark.unit
class TestBuildValidatorDegradation:
    """A failing ``create_llm_client`` degrades to ``None``, never raises."""

    def test_degrades_to_none_when_llm_client_raises(
        self, monkeypatch, capsys
    ) -> None:
        from starboard.cli.cli.review_command import _build_validator

        with mock.patch(
            "starboard.adapters.llm.create_llm_client",
            side_effect=RuntimeError("no credentials"),
        ):
            result = _build_validator(_args(validate=True), _config(), _err())

        assert result is None

    def test_degraded_council_does_not_raise(self, monkeypatch) -> None:
        """A review should proceed even when the council cannot be built."""
        from starboard.cli.cli.review_command import _build_validator

        with mock.patch(
            "starboard.adapters.llm.create_llm_client",
            side_effect=ConnectionError("workspace unreachable"),
        ):
            # Must not raise; the caller checks for None to skip validation.
            result = _build_validator(_args(validate=True), _config(), _err())

        assert result is None


@pytest.mark.unit
class TestMaxPassesCeilingFromEnv:
    """``STARBOARD_REVIEW_COUNCIL_MAX_PASSES`` is forwarded to the council config."""

    def test_max_passes_applied_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("STARBOARD_REVIEW_COUNCIL_MODELS", "m1,m2")
        monkeypatch.setenv("STARBOARD_REVIEW_COUNCIL_MAX_PASSES", "3")
        from starboard.cli.cli.review_command import _build_validator

        with _patched_create_llm_client():
            result = _build_validator(_args(validate=True), _config(), _err())

        assert isinstance(result, ValidatorCouncil)
        # max_possible_calls = max_passes(3) × models(2) × findings.
        # For 1 finding the ceiling is 6.
        assert result._config.max_passes == 3
        assert result._config.ensemble_size == 2
