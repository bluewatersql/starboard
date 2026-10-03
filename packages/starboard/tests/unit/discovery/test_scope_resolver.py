"""Unit tests for the shared scope-resolver routing primitive (spec §7)."""

import pytest
from starboard.discovery.scope_resolver import ScopeRequest, resolve_scope


@pytest.mark.parametrize(
    "internal,req,exp_source,exp_prompt",
    [
        (
            True,
            ScopeRequest(text="run a workspace discovery"),
            "internal",
            "target",
        ),
        (
            True,
            ScopeRequest(text="…", workspace_id="1234567890"),
            "internal",
            None,
        ),
        (
            True,
            ScopeRequest(text="…in their workspace", obv_intent=True),
            "external",
            "confirm_obo",
        ),
        (
            False,
            ScopeRequest(text="run a workspace discovery"),
            "external",
            None,
        ),
    ],
)
def test_routing_table(internal, req, exp_source, exp_prompt):
    d = resolve_scope(req, internal_available=internal)
    assert d.source == exp_source
    assert (d.prompt is not None) == (exp_prompt is not None)
    assert d.prompt == exp_prompt
