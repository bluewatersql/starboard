# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Starboard Server - FastAPI Backend + curated public application API.

This package contains the backend server implementation:
- FastAPI routes and WebSocket endpoints
- Agent implementations and orchestration
- Tool implementations
- Databricks adapters
- LLM adapters
- Infrastructure (logging, config, DI)

Public application API
----------------------
The heavy runtime lives in internal sub-packages (``starboard.infra``,
``starboard.adapters``, ``starboard.tools``, …). First-party experiences such as
the CLI must not reach into those internals directly (package-boundary contract
GUIDELINE-005). Instead, the small set of building blocks the CLI composes is
re-exported here as the package's public API and resolved lazily via :pep:`562`.

The lazy resolution keeps ``import starboard`` free of ``databricks-sdk`` /
``openai`` / adapter weight: nothing behind these symbols is imported at package
init; each is pulled from its implementation module only on first access.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__version__ = "0.1.1"

# Public application API symbol -> implementation module. Resolved lazily by
# ``__getattr__`` so the top-level import performs no heavy work.
_PUBLIC_API: dict[str, str] = {
    "get_logger": "starboard.infra.observability.logging",
    "describe_auth": "starboard.infra.auth.resolver",
    "resolve_workspace_client": "starboard.infra.auth.resolver",
    "WorkspaceTarget": "starboard.infra.auth.resolver",
    "create_llm_client": "starboard.adapters.llm",
    "AnalyticsSqlAdapter": "starboard.adapters.ports.analytics_sql",
    "LLMSQLGenerator": "starboard.tools.domain.analytics_sql.llm_sql_generator",
    "CouncilConfig": "starboard.tools.services.validator_council",
    "build_council": "starboard.tools.services.validator_council",
    "WorkloadReviewService": "starboard.tools.services.workload_review_service",
}

if TYPE_CHECKING:
    # Give type checkers the concrete signatures for the lazily-exported symbols.
    # ``X as X`` marks each as an explicit re-export (the runtime source of truth is
    # ``_PUBLIC_API``; these bindings exist only for static analysis).
    from starboard.adapters.llm import create_llm_client as create_llm_client
    from starboard.adapters.ports.analytics_sql import (
        AnalyticsSqlAdapter as AnalyticsSqlAdapter,
    )
    from starboard.infra.auth.resolver import (
        WorkspaceTarget as WorkspaceTarget,
    )
    from starboard.infra.auth.resolver import (
        describe_auth as describe_auth,
    )
    from starboard.infra.auth.resolver import (
        resolve_workspace_client as resolve_workspace_client,
    )
    from starboard.infra.observability.logging import get_logger as get_logger
    from starboard.tools.domain.analytics_sql.llm_sql_generator import (
        LLMSQLGenerator as LLMSQLGenerator,
    )
    from starboard.tools.services.validator_council import (
        CouncilConfig as CouncilConfig,
    )
    from starboard.tools.services.validator_council import (
        build_council as build_council,
    )
    from starboard.tools.services.workload_review_service import (
        WorkloadReviewService as WorkloadReviewService,
    )


def __getattr__(name: str) -> object:
    """Lazily resolve a public API symbol (PEP 562).

    Deferring the import here (rather than at module scope) is intentional: it
    keeps ``import starboard`` from eagerly pulling the heavy adapter/tool/infra
    modules that back these symbols.
    """
    module_path = _PUBLIC_API.get(name)
    if module_path is None:
        raise AttributeError(f"module 'starboard' has no attribute {name!r}")
    module = importlib.import_module(module_path)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted({*globals(), *_PUBLIC_API})


__all__ = ["__version__", *sorted(_PUBLIC_API)]
