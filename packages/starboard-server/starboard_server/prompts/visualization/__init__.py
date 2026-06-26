# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Visualization prompts for LLM-driven chart recommendation.

This module contains versioned prompt templates for the VisualizationService.
Prompts are designed to work with query catalog metadata and data profiles
to generate appropriate chart recommendations.

Prompt Versioning:
    - v1: Initial implementation with few-shot examples and metadata integration

Usage:
    >>> from starboard_server.prompts.visualization import v1
    >>> messages = v1.build_visualization_prompt(query_metadata, data_profile)
"""

from .v1 import PROMPT_VERSION

__all__ = ["PROMPT_VERSION"]
