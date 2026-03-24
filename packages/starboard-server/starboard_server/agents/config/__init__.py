"""
Agent configuration and setup.

Manages agent configuration, model generation, and agent registry.

Note: Configuration is now handled by EnvConfig (infra.core.config) which loads
from environment variables. The old ConfigLoader with config.yaml support has
been removed.
"""

from .agent_config import AgentConfig
from .model_generator import DomainModelConfigGenerator
from .registry import AgentCapability, AgentMetadata, AgentRegistry, AgentStatus

__all__ = [
    "AgentConfig",
    "DomainModelConfigGenerator",
    "AgentRegistry",
    "AgentMetadata",
    "AgentCapability",
    "AgentStatus",
]
