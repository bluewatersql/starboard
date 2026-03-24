"""
Authentication infrastructure components.

This module contains infrastructure-level authentication services including
providers, middleware, and service interfaces.
"""

from starboard_server.infra.auth.service import AuthenticationService

__all__ = ["AuthenticationService"]
