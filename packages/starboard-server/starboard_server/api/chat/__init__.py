# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Chat API package.

Provides REST endpoints for conversation management organized by functional domain:
- conversation_routes - Conversation CRUD operations
- message_routes - Message handling and interruptible reasoning
- config_routes - Configuration and health endpoints
- export_routes - Conversation export in markdown/JSON
- auth_routes - Authentication and user information

All routes are combined into a single router with the /api/chat prefix.
"""

from fastapi import APIRouter

from starboard_server.api.chat import (
    config_routes,
    conversation_routes,
    export_routes,
    message_routes,
)

# Create main router with prefix
router = APIRouter(prefix="/api/chat", tags=["chat"])

# Include all sub-routers
router.include_router(conversation_routes.router)
router.include_router(message_routes.router)
router.include_router(config_routes.router)
router.include_router(export_routes.router)

__all__ = ["router"]
