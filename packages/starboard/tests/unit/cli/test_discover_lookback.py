"""``starboard --discover --lookback-days``: 7 (weekly), 30, 60 or 90 days."""

from __future__ import annotations

import pytest
from starboard.cli.cli import main as cli_main


@pytest.mark.unit
@pytest.mark.parametrize("days", [7, 30, 60, 90])
def test_lookback_days_accepts_the_supported_windows(days: int) -> None:
    ns = cli_main.parse_args(["--discover", "--lookback-days", str(days)])
    assert ns.lookback_days == days


@pytest.mark.unit
def test_lookback_days_defaults_to_30() -> None:
    assert cli_main.parse_args(["--discover"]).lookback_days == 30


@pytest.mark.unit
@pytest.mark.parametrize("days", ["1", "14", "45"])
def test_lookback_days_rejects_other_windows(days: str) -> None:
    with pytest.raises(SystemExit):
        cli_main.parse_args(["--discover", "--lookback-days", days])


@pytest.mark.unit
def test_agent_discovery_tools_offer_the_same_windows() -> None:
    from starboard.agents.tools.schemas.discovery import (
        DISCOVER_ACTIVE_PRODUCTS,
        RUN_WORKSPACE_DISCOVERY,
    )

    for schema in (DISCOVER_ACTIVE_PRODUCTS, RUN_WORKSPACE_DISCOVERY):
        prop = schema["parameters"]["properties"]["lookback_days"]
        assert prop["enum"] == ["7", "30", "60", "90"], schema["name"]
