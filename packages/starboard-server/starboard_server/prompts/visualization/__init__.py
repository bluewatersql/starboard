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
