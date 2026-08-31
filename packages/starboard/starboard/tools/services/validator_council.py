# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Validator council — bounded multi-pass self-critique gate (Phase-3 D1c / D-3.2).

The validator council is the **model-calling** stage of the Workload Review
finding-quality pipeline. After the pure kernel severity gate
(:mod:`starboard_core.domain.rules.gate`) drops sub-threshold noise, the council
critiques each surviving candidate finding before it surfaces:

* **multi-pass self-critique** — each finding is critiqued for up to
  ``max_passes`` passes; a pass that reaches consensus stops early, so spend is
  **bounded** (``max_passes × models × findings`` is the hard ceiling);
* **optional model-ensemble** — when more than one model id is configured the
  passes are voted across the ensemble; with a single model it degrades cleanly
  to single-model self-critique;
* **deterministic under a fixed seed** — each pass derives its seed from
  ``config.seed`` so a deterministic client yields identical results run-to-run.

**Bounded spend (PHASE_3 §1 guardrail):** ``max_passes`` is a fixed ceiling and
:pyattr:`CouncilResult.max_possible_calls` exposes the worst-case call count for
assertions. **Model ids are configuration, never hard-coded** (G5): they are
resolved from :class:`CouncilConfig` (env / caller), so any AI-gateway or
model-catalog id is allowed.

This module lives in the ``starboard`` server tier — it may call models. The
kernel stays model-free (the severity gate + Action-Rate delta are pure). Tests
inject a deterministic fake :class:`ModelClient`, so the council never hits a
live model in unit tests.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starboard_core.domain.models.review import ReviewFinding

from starboard.infra.observability.logging import get_logger
from starboard.infra.reliability.retry import is_permanent_error

if TYPE_CHECKING:
    from starboard.adapters.llm.base import BaseLLMClient

logger = get_logger(__name__)

# Fallback model id used only when nothing is configured via env/caller. This is
# a DEFAULT, not a hard-coded requirement — any configured gateway/catalog id
# (e.g. ``system.ai.claude-opus-4-8[1m]``, ``claude-fable-5``) overrides it.
DEFAULT_COUNCIL_MODEL = "databricks-claude-sonnet-4-5"

# Env vars the council reads (comma-separated MODELS wins over single MODEL).
_ENV_MODELS = "STARBOARD_REVIEW_COUNCIL_MODELS"
_ENV_MODEL = "STARBOARD_REVIEW_COUNCIL_MODEL"
_ENV_MAX_PASSES = "STARBOARD_REVIEW_COUNCIL_MAX_PASSES"
_ENV_SEED = "STARBOARD_REVIEW_COUNCIL_SEED"

# Hard upper bound on ``max_passes`` regardless of configuration — a backstop so
# a mis-set env var can never turn the council into unbounded model spend.
MAX_PASSES_CEILING = 5


class Verdict(StrEnum):
    """A single model's verdict on whether a finding should surface."""

    KEEP = "keep"
    DROP = "drop"


class CritiqueRequest(BaseModel):
    """The paraphrased finding payload handed to a model for critique.

    Deliberately carries only the finding's own summary/rationale/observed-state
    plus its severity and score — **no evidence rows, no internal namespaces** —
    so the council never ships customer data or internal identifiers to a model.
    """

    model_config = ConfigDict(frozen=True)

    finding_id: str
    summary: str
    rationale: str
    current_state: str
    severity: str
    score: float

    @classmethod
    def from_finding(cls, finding: ReviewFinding) -> CritiqueRequest:
        """Build a critique request from a review finding (no evidence rows)."""
        f = finding.finding
        return cls(
            finding_id=f.id,
            summary=f.summary,
            rationale=f.rationale,
            current_state=f.current_state,
            severity=f.severity.value,
            score=f.score,
        )


class ModelVerdict(BaseModel):
    """One model's verdict for one finding on one pass."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    pass_index: int = Field(ge=0)


@runtime_checkable
class ModelClient(Protocol):
    """Narrow interface a council model must satisfy (injectable for tests).

    Intentionally decoupled from the heavy :class:`BaseLLMClient` so tests can
    inject a tiny deterministic fake. :class:`CouncilModelClientAdapter` wraps a
    real ``BaseLLMClient`` to satisfy this protocol.
    """

    @property
    def model_id(self) -> str:
        """The model id this client critiques with (for verdict attribution)."""
        ...

    async def critique(
        self, request: CritiqueRequest, *, seed: int
    ) -> tuple[Verdict, float]:
        """Return this model's ``(verdict, confidence)`` for ``request``.

        ``seed`` makes the call reproducible; a deterministic client must return
        the same result for the same ``(request, seed)``.
        """
        ...


class CouncilConfig(BaseModel):
    """Bounded, deterministic configuration for the validator council.

    Args:
        model_ids: The ensemble of model ids to vote across (>= 1). Resolved
            from configuration — never hard-coded (G5).
        max_passes: Hard ceiling on self-critique passes per finding (>= 1,
            <= :data:`MAX_PASSES_CEILING`). Bounds model spend.
        seed: Base seed; pass ``i`` uses ``seed + i`` for reproducibility.
        keep_quorum: Fraction of KEEP votes in the deciding pass required to
            keep a finding (``0 < q <= 1``; default majority, ties keep).
    """

    model_config = ConfigDict(frozen=True)

    model_ids: tuple[str, ...] = (DEFAULT_COUNCIL_MODEL,)
    max_passes: int = Field(default=2, ge=1, le=MAX_PASSES_CEILING)
    seed: int = 0
    keep_quorum: float = Field(default=0.5, gt=0.0, le=1.0)

    @field_validator("model_ids", mode="before")
    @classmethod
    def _coerce_model_ids(cls, v: object) -> object:
        """Accept a single id or comma-separated string as well as a sequence."""
        if isinstance(v, str):
            return tuple(m.strip() for m in v.split(",") if m.strip())
        return v

    @model_validator(mode="after")
    def _require_at_least_one_model(self) -> CouncilConfig:
        if not self.model_ids:
            raise ValueError("CouncilConfig requires at least one model id")
        return self

    @property
    def ensemble_size(self) -> int:
        """Number of models voting in the ensemble."""
        return len(self.model_ids)

    @classmethod
    def from_env(cls, *, default_model: str | None = None) -> CouncilConfig:
        """Build a config from environment variables with safe fallbacks.

        Precedence for the model ensemble: ``STARBOARD_REVIEW_COUNCIL_MODELS``
        (comma-separated) → ``STARBOARD_REVIEW_COUNCIL_MODEL`` → ``default_model``
        → :data:`DEFAULT_COUNCIL_MODEL`. ``max_passes`` / ``seed`` come from their
        env vars when set and parseable, else the class defaults.
        """
        models_raw = os.environ.get(_ENV_MODELS) or os.environ.get(_ENV_MODEL)
        if models_raw:
            model_ids: tuple[str, ...] = tuple(
                m.strip() for m in models_raw.split(",") if m.strip()
            )
        else:
            model_ids = (default_model or DEFAULT_COUNCIL_MODEL,)

        overrides: dict[str, object] = {"model_ids": model_ids}
        max_passes = _parse_int(os.environ.get(_ENV_MAX_PASSES))
        if max_passes is not None:
            overrides["max_passes"] = min(max(max_passes, 1), MAX_PASSES_CEILING)
        seed = _parse_int(os.environ.get(_ENV_SEED))
        if seed is not None:
            overrides["seed"] = seed
        return cls(**overrides)


class FindingVerdict(BaseModel):
    """The council's decision for a single finding, with its verdict trail."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    kept: bool
    keep_ratio: float
    passes_used: int
    verdicts: tuple[ModelVerdict, ...] = ()


class CouncilResult(BaseModel):
    """The council's partition of candidate findings plus its spend accounting."""

    model_config = ConfigDict(frozen=True)

    kept: tuple[ReviewFinding, ...] = ()
    suppressed: tuple[ReviewFinding, ...] = ()
    finding_verdicts: tuple[FindingVerdict, ...] = ()
    total_model_calls: int = 0
    max_passes: int = 0
    ensemble_size: int = 0
    candidate_count: int = 0
    disabled_model_ids: tuple[str, ...] = ()

    @property
    def max_possible_calls(self) -> int:
        """Worst-case model-call ceiling (``max_passes × models × findings``)."""
        return self.max_passes * self.ensemble_size * self.candidate_count

    @property
    def kept_count(self) -> int:
        """Number of findings the council kept."""
        return len(self.kept)

    @property
    def suppressed_count(self) -> int:
        """Number of findings the council suppressed."""
        return len(self.suppressed)


class ValidatorCouncil:
    """Bounded multi-pass self-critique / ensemble gate over candidate findings.

    Args:
        model_clients: One :class:`ModelClient` per configured model id (>= 1).
            Inject a deterministic fake in tests.
        config: The bounded, deterministic :class:`CouncilConfig`.
    """

    def __init__(
        self, model_clients: Sequence[ModelClient], *, config: CouncilConfig
    ) -> None:
        if not model_clients:
            raise ValueError("ValidatorCouncil requires at least one model client")
        self._clients = tuple(model_clients)
        self._config = config

    async def _decide_finding(
        self, finding: ReviewFinding
    ) -> tuple[FindingVerdict, int]:
        """Run bounded multi-pass critique for one finding.

        Returns the finding's verdict and the number of model calls it consumed.
        Stops early once a pass reaches unanimous consensus.
        """
        request = CritiqueRequest.from_finding(finding)
        all_verdicts: list[ModelVerdict] = []
        calls = 0
        last_keep_ratio = 0.0
        passes_used = 0

        for pass_index in range(self._config.max_passes):
            passes_used = pass_index + 1
            seed = self._config.seed + pass_index
            pass_verdicts: list[ModelVerdict] = []
            for client in self._clients:
                verdict, confidence = await client.critique(request, seed=seed)
                calls += 1
                pass_verdicts.append(
                    ModelVerdict(
                        model_id=client.model_id,
                        verdict=verdict,
                        confidence=_clamp01(confidence),
                        pass_index=pass_index,
                    )
                )
            all_verdicts.extend(pass_verdicts)

            keeps = sum(1 for v in pass_verdicts if v.verdict is Verdict.KEEP)
            last_keep_ratio = keeps / len(pass_verdicts)

            # Consensus (unanimous keep or unanimous drop) ends critique early.
            if keeps == 0 or keeps == len(pass_verdicts):
                break

        kept = last_keep_ratio >= self._config.keep_quorum
        return (
            FindingVerdict(
                finding_id=finding.finding.id,
                kept=kept,
                keep_ratio=last_keep_ratio,
                passes_used=passes_used,
                verdicts=tuple(all_verdicts),
            ),
            calls,
        )

    async def review(
        self,
        findings: Sequence[ReviewFinding],
        *,
        progress: Callable[[str], None] | None = None,
    ) -> CouncilResult:
        """Critique every candidate finding and partition kept vs. suppressed.

        Deterministic and bounded: input order is preserved and the total model
        calls never exceed :pyattr:`CouncilResult.max_possible_calls`.

        ``progress``, when given, is called with a short human-readable status
        string as each finding is validated (so a long council pass is not silent).
        """
        kept: list[ReviewFinding] = []
        suppressed: list[ReviewFinding] = []
        verdicts: list[FindingVerdict] = []
        total_calls = 0

        total = len(findings)
        if progress is not None and total:
            progress(
                f"validating {total} findings "
                f"({self._config.ensemble_size} models, ≤{self._config.max_passes} passes)"
            )
        for index, finding in enumerate(findings, 1):
            verdict, calls = await self._decide_finding(finding)
            total_calls += calls
            verdicts.append(verdict)
            (kept if verdict.kept else suppressed).append(finding)
            if progress is not None:
                progress(f"validating findings… {index}/{total}")

        disabled_model_ids = tuple(
            client.model_id
            for client in self._clients
            if getattr(client, "is_disabled", False)
        )
        result = CouncilResult(
            kept=tuple(kept),
            suppressed=tuple(suppressed),
            finding_verdicts=tuple(verdicts),
            total_model_calls=total_calls,
            max_passes=self._config.max_passes,
            ensemble_size=self._config.ensemble_size,
            candidate_count=len(findings),
            disabled_model_ids=disabled_model_ids,
        )
        logger.info(
            "validator_council_complete",
            candidates=result.candidate_count,
            kept=result.kept_count,
            suppressed=result.suppressed_count,
            model_calls=result.total_model_calls,
            max_possible_calls=result.max_possible_calls,
            ensemble_size=result.ensemble_size,
            max_passes=result.max_passes,
            disabled_model_ids=list(disabled_model_ids),
        )
        return result


class CouncilModelClientAdapter:
    """Adapts a real :class:`BaseLLMClient` to the council's :class:`ModelClient`.

    One adapter binds one model id. The critique prompt is model-agnostic and
    ships only the paraphrased :class:`CritiqueRequest` (no evidence rows / no
    internal identifiers). A model/parse failure degrades **safely** to
    ``(KEEP, 0.0)`` so an infra hiccup never silently hides a real finding.
    """

    def __init__(self, llm_client: BaseLLMClient, *, model_id: str) -> None:
        self._llm = llm_client
        self._model_id = model_id
        self._disabled = False

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def is_disabled(self) -> bool:
        """True once a permanent error retired this model for the run."""
        return self._disabled

    async def critique(
        self, request: CritiqueRequest, *, seed: int  # noqa: ARG002 - protocol arg; determinism is via temperature=0
    ) -> tuple[Verdict, float]:
        # A model retired by an earlier permanent failure short-circuits: no more
        # network calls for the rest of the run. Degrades to KEEP so a dead model
        # never silently hides a finding.
        if self._disabled:
            return (Verdict.KEEP, 0.0)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a reviewer validating a workload-review finding "
                    "before it is shown to a user. Decide whether the finding is "
                    "a real, actionable issue worth surfacing. Respond as JSON "
                    '{"verdict": "keep"|"drop", "confidence": 0.0-1.0}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Finding: {request.summary}\n"
                    f"Severity: {request.severity} (priority score {request.score:.1f})\n"
                    f"Why it matters: {request.rationale}\n"
                    f"Observed state: {request.current_state}\n\n"
                    "Is this finding real and worth surfacing?"
                ),
            },
        ]
        try:
            raw = await self._llm.json_response(
                messages,
                model=self._model_id,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001 - degrade safely, never hide a finding
            if is_permanent_error(exc):
                # A nonexistent endpoint / denied auth will never recover — retire
                # this model for the whole run instead of re-failing per finding.
                self._disabled = True
                logger.warning(
                    "council_model_disabled",
                    model_id=self._model_id,
                    reason="permanent_error",
                    error=str(exc),
                )
            else:
                logger.warning(
                    "council_model_call_failed",
                    model_id=self._model_id,
                    error=str(exc),
                )
            return (Verdict.KEEP, 0.0)
        return _parse_verdict(raw)


def build_council(
    llm_client: BaseLLMClient, config: CouncilConfig
) -> ValidatorCouncil:
    """Build a :class:`ValidatorCouncil` binding one adapter per configured model.

    The same underlying ``llm_client`` serves every model id (routing by the
    ``model`` argument on each call), so a single gateway client backs the whole
    ensemble.
    """
    clients = [
        CouncilModelClientAdapter(llm_client, model_id=model_id)
        for model_id in config.model_ids
    ]
    return ValidatorCouncil(clients, config=config)


def _parse_verdict(raw: dict[str, object]) -> tuple[Verdict, float]:
    """Parse a model's JSON response into ``(verdict, confidence)`` defensively."""
    verdict_raw = str(raw.get("verdict", "keep")).strip().lower()
    verdict = Verdict.DROP if verdict_raw == "drop" else Verdict.KEEP
    confidence = _clamp01(_coerce_float(raw.get("confidence"), default=0.5))
    return (verdict, confidence)


def _coerce_float(value: object, *, default: float) -> float:
    """Coerce a JSON scalar to float, falling back to ``default``."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _clamp01(value: float) -> float:
    """Clamp a confidence value into the ``[0.0, 1.0]`` range."""
    return max(0.0, min(1.0, value))


def _parse_int(value: str | None) -> int | None:
    """Parse an int from an env string, returning None when absent/invalid."""
    if value is None:
        return None
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


__all__ = [
    "DEFAULT_COUNCIL_MODEL",
    "MAX_PASSES_CEILING",
    "CouncilConfig",
    "CouncilModelClientAdapter",
    "CouncilResult",
    "CritiqueRequest",
    "FindingVerdict",
    "ModelClient",
    "ModelVerdict",
    "ValidatorCouncil",
    "Verdict",
    "build_council",
]
