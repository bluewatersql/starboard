"""Shared scope-resolver routing primitive (spec §7, integration design).

Pure decision logic used by the discovery/engagement skills + CLI to route a
scope request to an internal (mirror) or external source, without any I/O,
prompting, or SDK access. See ``changes/internal_query_symmetry/8_integration_design.md``
§7 for the routing decision tree this implements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Source = Literal["internal", "external"]


@dataclass(frozen=True)
class ScopeRequest:
    """A request for a workspace-discovery (or similar) scope to resolve."""

    text: str
    workspace_id: str | None = None
    account: str | None = None
    obv_intent: bool = False


@dataclass(frozen=True)
class ScopeDecision:
    """The resolved source/target/prompt for a :class:`ScopeRequest`."""

    source: Source
    target: str | None
    prompt: str | None


def resolve_scope(
    request: ScopeRequest, *, internal_available: bool
) -> ScopeDecision:
    """Resolve a scope request to a source/target/prompt decision.

    Implements the §7 routing decision tree:

    - Internal unavailable -> external, no target, no prompt (host may still
      prompt to pick a workspace only if several are known, which this
      primitive does not decide).
    - Internal available + explicit OBO intent ("...in their workspace")
      -> external, prompt="confirm_obo" (the either/or row).
    - Internal available + a workspace_id already supplied -> internal,
      target=workspace_id, no prompt (target supplied, run directly).
    - Internal available + no target, no OBO intent -> internal, prompt to
      pick a target ("target").
    """
    if not internal_available:
        return ScopeDecision(source="external", target=request.account, prompt=None)

    if request.obv_intent:
        return ScopeDecision(source="external", target=request.account, prompt="confirm_obo")

    if request.workspace_id:
        return ScopeDecision(source="internal", target=request.workspace_id, prompt=None)

    return ScopeDecision(source="internal", target=request.account, prompt="target")
