# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Schema adaptation for different LLM providers.

Handles JSON schema flattening, strict mode patching, and tool schema
preparation for multi-provider compatibility (OpenAI, Gemini, etc.).
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel

from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


def is_gemini_model(model: str) -> bool:
    """Check if a model is a Google Gemini model.

    Gemini models have specific limitations on JSON Schema support:
    - No support for $defs/$ref -- schemas must be fully inlined.

    Args:
        model: Model identifier

    Returns:
        True if this is a Gemini model
    """
    model_lower = model.lower()
    return "gemini" in model_lower or "google" in model_lower


def is_gpt5_model(model: str) -> bool:
    """Check if a model is a GPT-5 variant.

    GPT-5 models have provider constraints:
    - Only support temperature=1.0

    Args:
        model: Model identifier

    Returns:
        True if this is a GPT-5 model variant
    """
    model_lower = model.lower()
    return "gpt-5" in model_lower or "gpt5" in model_lower


def is_no_temperature_model(model: str) -> bool:
    """Check if a model rejects the temperature parameter entirely.

    Claude Opus 4 and later Anthropic models (claude-opus-4-x, global.anthropic.claude-opus-4-x)
    return a 400 BAD_REQUEST when temperature is included in the request.

    Args:
        model: Model identifier

    Returns:
        True if temperature must be omitted from the API request
    """
    model_lower = model.lower()
    return "claude-opus-4" in model_lower or "claude_opus_4" in model_lower


_NO_STRUCTURED_OUTPUT_PATTERNS = (
    "claude",
    "anthropic",
    "llama",
    "mistral",
    "mixtral",
    "dbrx",
    "command",
    "cohere",
)


def supports_structured_output(model: str) -> bool:
    """Check whether a model supports the ``response_format: json_schema`` API.

    OpenAI GPT-4o/GPT-5 and compatible fine-tunes support it.
    Databricks-hosted external models (Claude, Llama, Mistral, etc.)
    and Gemini do not.

    Args:
        model: Model identifier or Databricks serving endpoint name.

    Returns:
        ``True`` if the model is expected to accept ``response_format``.
    """
    model_lower = model.lower()
    if is_gemini_model(model):
        return False
    return not any(pat in model_lower for pat in _NO_STRUCTURED_OUTPUT_PATTERNS)


def flatten_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten a JSON schema by resolving $ref and inlining $defs.

    Google Gemini models don't support JSON Schema $defs or $ref,
    so we need to flatten these into inline definitions.

    Args:
        schema: JSON schema dictionary (potentially with $defs and $ref)

    Returns:
        Flattened schema with all references resolved
    """
    if "$defs" not in schema:
        return schema

    defs = schema.get("$defs", {})

    def resolve_refs(obj: Any) -> Any:
        """Recursively resolve $ref in nested structures."""
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_path = obj["$ref"]
                if ref_path.startswith("#/$defs/"):
                    def_name = ref_path.split("/")[-1]
                    if def_name in defs:
                        resolved = resolve_refs(defs[def_name].copy())
                        for key, value in obj.items():
                            if key != "$ref":
                                resolved[key] = value
                        return resolved
                return obj
            else:
                return {k: resolve_refs(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [resolve_refs(item) for item in obj]
        else:
            return obj

    flattened = resolve_refs(schema)

    if isinstance(flattened, dict) and "$defs" in flattened:
        flattened = {k: v for k, v in flattened.items() if k != "$defs"}

    return flattened


def make_schema_strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Add ``additionalProperties: false`` to every object in a JSON schema.

    OpenAI structured-output and compatible endpoints reject schemas that
    omit this flag.  Pydantic's ``model_json_schema()`` does not emit it,
    so we patch it here.  Also inlines ``$defs`` references so the schema
    is fully self-contained.
    """

    def _patch(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return node

        if "$ref" in node:
            ref_path = node["$ref"]
            ref_name = ref_path.rsplit("/", 1)[-1]
            if ref_name in defs:
                resolved = _patch(defs[ref_name].copy(), defs)
                extra = {k: v for k, v in node.items() if k not in ("$ref", "default")}
                resolved.update(extra)
                return resolved
            return node

        result = dict(node)

        # OpenAI strict mode does not support "default" values.
        result.pop("default", None)

        if result.get("type") == "object" or "properties" in result:
            result.setdefault("additionalProperties", False)

        if "properties" in result:
            result["properties"] = {
                k: _patch(v, defs) for k, v in result["properties"].items()
            }
            result["required"] = list(result["properties"].keys())

        if "items" in result:
            result["items"] = _patch(result["items"], defs)

        for combo_key in ("anyOf", "oneOf", "allOf"):
            if combo_key in result:
                result[combo_key] = [_patch(v, defs) for v in result[combo_key]]

        return result

    defs = schema.get("$defs", schema.get("definitions", {}))
    patched = _patch(schema, defs)
    patched.pop("$defs", None)
    patched.pop("definitions", None)
    return patched


def prepare_tools_for_model(
    tools: list[dict[str, Any]], model: str
) -> list[dict[str, Any]]:
    """Prepare tool definitions for a specific model.

    Different LLM providers have different requirements for tool schemas:
    - OpenAI/Claude: Support full JSON Schema with $defs and $ref
    - Gemini: Require flattened schemas without $defs or $ref

    Args:
        tools: List of tool definitions in OpenAI format
        model: Target model identifier

    Returns:
        Tool definitions adapted for the target model
    """
    if not is_gemini_model(model):
        return tools

    logger.debug(
        "gemini_schema_flattening",
        model=model,
        tool_count=len(tools),
        tool_names=[t.get("function", {}).get("name", "unknown") for t in tools],
    )
    flattened_tools = []
    for tool in tools:
        tool_copy = tool.copy()
        if "function" in tool_copy and "parameters" in tool_copy["function"]:
            parameters = tool_copy["function"]["parameters"]
            has_refs = "$defs" in parameters or "$ref" in str(parameters)
            flattened = flatten_json_schema(parameters)
            tool_copy["function"]["parameters"] = flattened
            if has_refs:
                logger.debug(
                    "schema_flattened",
                    tool_name=tool_copy["function"].get("name", "unknown"),
                    had_refs=True,
                )
        flattened_tools.append(tool_copy)

    return flattened_tools


def prepare_json_schema(
    schema: dict[str, Any] | type[BaseModel] | None,
    phase: str | None = None,
) -> tuple[dict[str, Any] | None, type[BaseModel] | None, bool]:
    """Prepare JSON schema for API request.

    Args:
        schema: Optional JSON schema dict or Pydantic model for validation
        phase: Phase name for schema naming

    Returns:
        Tuple of (json_schema_def, pydantic_model, is_pydantic)
    """
    is_pydantic = (
        schema is not None
        and isinstance(schema, type)
        and issubclass(schema, BaseModel)
    )

    if is_pydantic:
        pydantic_model = cast(type[BaseModel], schema)
        schema_dict = pydantic_model.model_json_schema()
        schema_dict = make_schema_strict(schema_dict)
        schema_name = pydantic_model.__name__
        json_schema_def: dict[str, Any] = {
            "name": schema_name,
            "schema": schema_dict,
            "strict": True,
        }
        return json_schema_def, pydantic_model, True

    elif schema is not None:
        schema_dict_val = cast(dict[str, Any], schema)
        if "name" in schema_dict_val and "schema" in schema_dict_val:
            if "strict" not in schema_dict_val:
                schema_dict_val = {**schema_dict_val, "strict": True}
            return schema_dict_val, None, False
        else:
            schema_name = phase or "response_schema"
            json_schema_def = {
                "name": schema_name,
                "schema": schema_dict_val,
                "strict": True,
            }
            return json_schema_def, None, False

    return None, None, False
