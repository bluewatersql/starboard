# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Service catalog loader from YAML configuration.

Loads service catalog entries from YAML files for router initialization.
Part of Router Integration for Phase 9.

Domain Validation:
    Catalog entries are validated against the valid AgentDomain values.
    Invalid domains generate warnings but don't block loading (for forward
    compatibility). Critical mismatch detection helps catch config drift.

Examples:
    >>> entries = load_service_catalog("service_catalog.yaml")
    >>> len(entries)
    6
    >>> entries[0].service_id
    'query_optimizer'
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import yaml
from starboard_server.agents.routing.routing_models import AgentDomain
from starboard_server.domain.models.service_catalog import ServiceCatalogEntry
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

VALID_DOMAINS: frozenset[str] = frozenset(get_args(AgentDomain))


class CatalogLoadError(Exception):
    """Raised when catalog loading or parsing fails.

    Examples:
        >>> raise CatalogLoadError("Catalog file not found")
    """


# Startup-only sync I/O — see ACCEPTABLE.md Exception 5
# This function is called exclusively from MultiAgentConversationManager.__init__()
# during application startup, before the event loop serves requests.
# The loaded data is cached for the lifetime of the process.
def load_service_catalog(yaml_path: str | Path) -> list[ServiceCatalogEntry]:
    """Load service catalog from YAML file.

    Note:
        This uses synchronous I/O because it is called only at startup.
        See ``changes/async/ACCEPTABLE.md`` Exception 5 for justification.

    Args:
        yaml_path: Path to YAML catalog file (string or Path object)

    Returns:
        List of ServiceCatalogEntry objects

    Raises:
        CatalogLoadError: If file not found, invalid YAML, or validation fails

    Examples:
        >>> entries = load_service_catalog("config/service_catalog.yaml")
        >>> len(entries)
        5

        >>> # Works with Path objects too
        >>> from pathlib import Path
        >>> entries = load_service_catalog(Path("config/service_catalog.yaml"))
    """
    catalog_path = Path(yaml_path) if isinstance(yaml_path, str) else yaml_path

    if not catalog_path.exists():
        error_msg = f"Catalog file not found: {catalog_path}"
        logger.error("catalog_load_failed", error=error_msg, path=str(catalog_path))
        raise CatalogLoadError(error_msg)

    # Startup-only sync I/O — see ACCEPTABLE.md Exception 5
    try:
        with open(catalog_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        error_msg = f"Failed to parse YAML: {e}"
        logger.error("catalog_parse_failed", error=error_msg, path=str(catalog_path))
        raise CatalogLoadError(error_msg) from e
    except OSError as e:
        error_msg = f"Failed to read catalog file: {e}"
        logger.error("catalog_read_failed", error=error_msg, path=str(catalog_path))
        raise CatalogLoadError(error_msg) from e

    return _parse_catalog_entries(data, catalog_path)


def _parse_catalog_entries(
    data: dict,
    catalog_path: Path,
) -> list[ServiceCatalogEntry]:
    """Parse and validate catalog entries from raw YAML data.

    Args:
        data: Parsed YAML data dictionary.
        catalog_path: Path to the source file (for logging).

    Returns:
        List of validated ServiceCatalogEntry objects.

    Raises:
        CatalogLoadError: If entry validation fails.
    """
    agents_data = data.get("agents", [])
    if not agents_data:
        logger.warning("catalog_empty", path=str(catalog_path))
        return []

    entries: list[ServiceCatalogEntry] = []
    invalid_domains: list[tuple[str, str]] = []

    for idx, agent_data in enumerate(agents_data):
        try:
            entry = ServiceCatalogEntry.from_dict(agent_data)

            if entry.domain not in VALID_DOMAINS:
                invalid_domains.append((entry.service_id, entry.domain))
                logger.warning(
                    "catalog_entry_invalid_domain",
                    service_id=entry.service_id,
                    domain=entry.domain,
                    valid_domains=list(VALID_DOMAINS),
                    hint="Domain will not be routable. Update to a valid AgentDomain value.",
                )

            entries.append(entry)
        except (ValueError, KeyError, TypeError) as e:
            error_msg = f"Failed to validate entry {idx}: {e}"
            logger.error(
                "catalog_entry_validation_failed",
                error=error_msg,
                entry_index=idx,
                service_id=agent_data.get("service_id", "unknown"),
            )
            raise CatalogLoadError(error_msg) from e

    service_ids = [e.service_id for e in entries]

    if invalid_domains:
        logger.warning(
            "catalog_loaded_with_warnings",
            path=str(catalog_path),
            entry_count=len(entries),
            service_ids=service_ids,
            invalid_domains=[
                {"service_id": sid, "domain": dom} for sid, dom in invalid_domains
            ],
        )
    else:
        logger.debug(
            "catalog_loaded",
            path=str(catalog_path),
            entry_count=len(entries),
            service_ids=service_ids,
        )

    return entries
