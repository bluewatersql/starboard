# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Curated Genie-room registry (Phase-3 D8-internal / D-3.5).

The NL-query internal adapter routes questions to **curated Genie rooms** for
higher-fidelity answers than the public native NL->SQL path. This module is the
internal-index-only registry of those rooms (names + ``go/`` shortlinks). Room
ids are resolved at runtime by the concrete Genie backend from the ``go/`` link;
they are intentionally not hard-coded here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GenieRoom:
    """A curated Genie room.

    Attributes:
        key: Stable selector key (matches the ``go/`` link stem).
        name: Human-readable room name.
        go_link: Internal ``go/`` shortlink the backend resolves to a room id.
        description: What data the room covers.
    """

    key: str
    name: str
    go_link: str
    description: str


#: The curated rooms, keyed by selector. Room ids are resolved from ``go_link``
#: at runtime by the backend (kept out of source per governance).
CURATED_ROOMS: dict[str, GenieRoom] = {
    "global_genie": GenieRoom(
        "global_genie", "Global Genie", "go/global_genie",
        "GTM data - accounts, consumption, forecasting",
    ),
    "emerging_genie": GenieRoom(
        "emerging_genie", "Emerging Genie", "go/emerging_genie",
        "Emerging segment data",
    ),
    "cme_genie": GenieRoom(
        "cme_genie", "CME Genie", "go/cme_genie",
        "Commercial / Mid-Enterprise data",
    ),
    "retail_genie": GenieRoom(
        "retail_genie", "Retail Genie", "go/retail_genie",
        "Retail industry vertical",
    ),
    "hls_genie": GenieRoom(
        "hls_genie", "HLS Genie", "go/hls_genie",
        "Healthcare & Life Sciences",
    ),
    "fins_genie": GenieRoom(
        "fins_genie", "FINS Genie", "go/fins_genie",
        "Financial Services",
    ),
    "mfg_genie": GenieRoom(
        "mfg_genie", "MFG Genie", "go/mfg_genie",
        "Manufacturing",
    ),
}

#: Room used when the caller supplies no (recognized) room hint.
DEFAULT_ROOM_KEY = "global_genie"


def select_room(
    extra: Mapping[str, Any] | None,
    *,
    rooms: Mapping[str, GenieRoom] = CURATED_ROOMS,
    default_key: str = DEFAULT_ROOM_KEY,
) -> GenieRoom:
    """Pick a curated room from a ``WorkspaceCtx.extra`` hint.

    Honors an explicit ``genie_room`` key, then a ``segment`` key; falls back to
    the default room when neither names a known room.
    """
    hints = extra or {}
    for field in ("genie_room", "segment"):
        value = hints.get(field)
        if isinstance(value, str) and value in rooms:
            return rooms[value]
    return rooms[default_key]
