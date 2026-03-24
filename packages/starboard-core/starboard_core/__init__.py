# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""
Starboard Core - Shared domain models, prompts, and types.

This package contains pure domain logic with no I/O dependencies:
- Domain models (DTOs, Pydantic models)
- Prompt templates (versioned)
- Type definitions and protocols
- Shared exceptions
"""

__version__ = "0.1.0"

# Re-export commonly used types for convenience
from starboard_core.domain.models import *  # noqa: F401, F403

__all__ = [
    "__version__",
]
