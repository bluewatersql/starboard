"""Base class and utilities for tool adapters.

Provides shared initialization, observability helpers, and schema generation
for all LLM-facing tool adapter classes.
"""

from __future__ import annotations

import inspect
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from starboard_server.infra.observability.events import EventEmitter
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_server.services.context.provider import SharedContextProvider

logger = get_logger(__name__)


class OutputFormat(str, Enum):
    """Output format selector for tool methods that return variable detail levels.

    Use ``OutputFormat.RAW`` to receive unprocessed source data, and
    ``OutputFormat.FORMATTED`` (the default) to receive analysis-ready results.

    Example:
        >>> logs = await tools.get_spark_logs(cluster_id="c-1", fmt=OutputFormat.RAW)
    """

    RAW = "raw"
    """Return unprocessed, raw data directly from the source."""

    FORMATTED = "formatted"
    """Return data transformed and analysis-ready for LLM consumption (default)."""


class BaseToolAdapter:
    """Shared base for all tool adapter classes.

    Provides:
    - Unified ``__init__`` accepting ``provider`` and ``events``.
    - ``from_provider`` classmethod factory.
    - ``_log_obs_context`` for standardized observability logging.

    Subclasses may extend ``__init__`` but should call ``super().__init__``.

    Example:
        >>> class MyTools(BaseToolAdapter):
        ...     pass
        >>> tools = MyTools.from_provider(provider, events=emitter)
    """

    def __init__(
        self,
        provider: SharedContextProvider,
        events: EventEmitter | None = None,
    ) -> None:
        """Initialize tool adapter.

        Args:
            provider: SharedContextProvider for data access.
            events: Optional event emitter for observability.
        """
        self.provider = provider
        self.events = events or EventEmitter()

    @classmethod
    def from_provider(
        cls,
        provider: SharedContextProvider,
        events: EventEmitter | None = None,
    ) -> BaseToolAdapter:
        """Create adapter from SharedContextProvider.

        Factory method for convenient construction.

        Args:
            provider: SharedContextProvider for data access.
            events: Optional event emitter for observability.

        Returns:
            Configured adapter instance.

        Example:
            >>> tools = ClusterTools.from_provider(provider)
        """
        return cls(provider=provider, events=events)

    def _log_obs_context(
        self,
        operation: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log operation with standardized observability context.

        Emits a structured debug log entry that includes the operation name
        and any additional key-value pairs supplied by the caller.

        Args:
            operation: Name of the tool operation being logged (e.g. ``"list_clusters"``).
            extra: Optional mapping of additional context fields to include in
                the log entry (e.g. ``{"cluster_id": "abc", "window_days": 7}``).

        Example:
            >>> self._log_obs_context("list_clusters", {"window_days": 7})
        """
        log_extra: dict[str, Any] = {"operation": operation}
        if extra:
            log_extra.update(extra)
        logger.debug(operation, extra=log_extra)


# =============================================================================
# Tool Schema Auto-Generation
# =============================================================================

# Mapping from Python type annotations to JSON Schema types
_PY_TYPE_TO_JSON: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
    "Any": "object",
}


def _python_type_to_json_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema fragment.

    Args:
        annotation: Python type annotation (from ``inspect.Parameter.annotation``).

    Returns:
        JSON Schema type fragment, e.g. ``{"type": "string"}``.
    """
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}

    # Handle Optional[X] -> X (Union[X, None])
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())

    if origin is type(None):
        return {"type": "null"}

    # Union / Optional
    import types as _types

    if origin is _types.UnionType or (
        origin is not None and hasattr(origin, "__name__") is False
    ):
        # Filter out NoneType from Union args
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _python_type_to_json_schema(non_none[0])

    type_name = getattr(annotation, "__name__", None) or str(annotation)
    json_type = _PY_TYPE_TO_JSON.get(type_name, "string")
    return {"type": json_type}


def tool_schema(
    description: str | None = None,
    required: list[str] | None = None,
    properties_override: dict[str, Any] | None = None,
) -> Callable:
    """Decorator that auto-generates a JSON Schema from a function's signature and docstring.

    Attaches ``.__tool_schema__`` to the decorated function so it can be
    consumed by the tool registry or schema-building utilities without
    maintaining separate hand-crafted schema dicts.

    Args:
        description: Override for the function description. Defaults to the
            first paragraph of the docstring.
        required: List of required parameter names. If omitted the decorator
            infers required params as those without a default value (excluding
            ``self``).
        properties_override: Manual overrides merged on top of the auto-generated
            property definitions (useful for adding ``enum`` constraints).

    Returns:
        The original function with ``.__tool_schema__`` attached.

    Example:
        >>> @tool_schema(description="Get portfolio of warehouses")
        ... async def get_warehouse_portfolio(
        ...     self,
        ...     window_days: int = 7,
        ...     include_inactive: bool = False,
        ... ) -> dict:
        ...     ...
        >>> schema = get_warehouse_portfolio.__tool_schema__
        >>> schema["function"]["name"]
        'get_warehouse_portfolio'
    """

    def decorator(fn: Callable) -> Callable:
        sig = inspect.signature(fn)
        doc = inspect.getdoc(fn) or ""

        # Derive description from first docstring paragraph
        func_description = description
        if func_description is None:
            first_para = doc.split("\n\n")[0].replace("\n", " ").strip()
            func_description = first_para or fn.__name__

        properties: dict[str, Any] = {}
        inferred_required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            prop: dict[str, Any] = _python_type_to_json_schema(param.annotation)

            # Extract per-parameter description from docstring (Args section)
            param_desc = _extract_param_doc(doc, param_name)
            if param_desc:
                prop["description"] = param_desc

            # Apply default if present
            if param.default is not inspect.Parameter.empty:
                prop["default"] = param.default
            else:
                inferred_required.append(param_name)

            properties[param_name] = prop

        # Apply caller overrides
        if properties_override:
            for key, overrides in properties_override.items():
                if key in properties:
                    properties[key].update(overrides)
                else:
                    properties[key] = overrides

        final_required = required if required is not None else inferred_required

        fn.__tool_schema__ = {  # type: ignore[attr-defined]
            "type": "function",
            "function": {
                "name": fn.__name__,
                "description": func_description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": final_required,
                },
            },
        }
        return fn

    return decorator


def _extract_param_doc(docstring: str, param_name: str) -> str | None:
    """Extract the description for a parameter from a Google-style docstring.

    Args:
        docstring: Full docstring text.
        param_name: Parameter name to look up.

    Returns:
        Description string if found, else None.
    """
    lines = docstring.splitlines()
    in_args = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped in ("Args:", "Arguments:"):
            in_args = True
            continue
        if in_args:
            # End of Args section
            if stripped and not stripped.startswith(" ") and stripped.endswith(":"):
                break
            if stripped.startswith(f"{param_name}:") or stripped.startswith(
                f"{param_name} ("
            ):
                # Capture text after the first colon on this line only
                colon_idx = stripped.index(":")
                desc = stripped[colon_idx + 1 :].strip()
                return desc or None
    return None


def collect_tool_schemas(tool_instance: Any) -> list[dict[str, Any]]:
    """Collect all ``__tool_schema__`` entries from a tool adapter instance.

    Args:
        tool_instance: An instance of a tool adapter class.

    Returns:
        List of JSON Schema dicts for all decorated methods.

    Example:
        >>> schemas = collect_tool_schemas(warehouse_tools)
        >>> len(schemas) > 0
        True
    """
    schemas: list[dict[str, Any]] = []
    for name in dir(type(tool_instance)):
        if name.startswith("_"):
            continue
        method = getattr(type(tool_instance), name, None)
        schema = getattr(method, "__tool_schema__", None)
        if schema is not None:
            schemas.append(schema)
    return schemas
