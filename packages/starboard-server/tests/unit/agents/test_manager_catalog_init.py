"""Unit tests for MultiAgentConversationManager catalog initialization.

Tests that the manager properly initializes the service catalog tool and
next-step generator on startup.

Part of Router Integration for Phase 9.
"""

from pathlib import Path
from unittest.mock import Mock, patch

from starboard_server.agents.conversation.multi_agent_manager import (
    MultiAgentConversationManager,
)
from starboard_server.services.coordination.next_step_generator import NextStepGenerator
from starboard_server.tools.service_catalog_tool import ServiceCatalogTool


class TestManagerCatalogInitialization:
    """Test catalog initialization in MultiAgentConversationManager."""

    @patch("starboard_server.config.catalog_loader.load_service_catalog")
    def test_manager_initializes_catalog_tool(self, mock_load_catalog):
        """Test that manager loads catalog and initializes tool on startup."""
        # Arrange - mock catalog entries
        from starboard_server.domain.models.service_catalog import (
            ServiceCatalogEntry,
            ServiceStatus,
            ServiceType,
        )

        mock_entries = [
            ServiceCatalogEntry(
                service_id="test_agent_v1",
                service_type=ServiceType.AGENT,
                name="Test Agent",
                domain="test",
                description="Test agent",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
        ]
        mock_load_catalog.return_value = mock_entries

        # Mock dependencies (actual constructor signature)
        mock_agent_factory = Mock()
        mock_intent_router = Mock()
        mock_state_manager = Mock()

        # Act - create manager (catalog should auto-initialize)
        manager = MultiAgentConversationManager(
            agent_factory=mock_agent_factory,
            intent_router=mock_intent_router,
            state_manager=mock_state_manager,
        )

        # Assert - catalog tool and generator initialized
        assert hasattr(manager, "catalog_tool"), (
            "Manager should have catalog_tool attribute"
        )
        assert isinstance(manager.catalog_tool, ServiceCatalogTool)
        assert hasattr(manager, "next_step_generator"), (
            "Manager should have next_step_generator attribute"
        )
        assert isinstance(manager.next_step_generator, NextStepGenerator)

        # Verify load_service_catalog was called
        mock_load_catalog.assert_called_once()
        call_args = mock_load_catalog.call_args[0]
        assert isinstance(call_args[0], Path)
        assert "service_catalog.yaml" in str(call_args[0])

    @patch("starboard_server.config.catalog_loader.load_service_catalog")
    def test_manager_handles_catalog_load_error_gracefully(self, mock_load_catalog):
        """Test that manager handles catalog load failures gracefully."""
        # Arrange - simulate catalog load error
        mock_load_catalog.side_effect = FileNotFoundError("Catalog not found")

        # Mock dependencies
        mock_agent_factory = Mock()
        mock_intent_router = Mock()
        mock_state_manager = Mock()

        # Act - create manager (should not crash)
        manager = MultiAgentConversationManager(
            agent_factory=mock_agent_factory,
            intent_router=mock_intent_router,
            state_manager=mock_state_manager,
        )

        # Assert - catalog tool initialized with empty registry
        assert hasattr(manager, "catalog_tool")
        assert isinstance(manager.catalog_tool, ServiceCatalogTool)
        # Tool should work but have no entries
        assert len(manager.catalog_tool.registry.list_all()) == 0

    @patch("starboard_server.config.catalog_loader.load_service_catalog")
    def test_manager_catalog_completes_initialization(self, mock_load_catalog):
        """Test that manager completes initialization with catalog entries."""
        # Arrange
        from starboard_server.domain.models.service_catalog import (
            ServiceCatalogEntry,
            ServiceStatus,
            ServiceType,
        )

        mock_entries = [
            ServiceCatalogEntry(
                service_id="agent1",
                service_type=ServiceType.AGENT,
                name="Agent 1",
                domain="domain1",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="agent2",
                service_type=ServiceType.AGENT,
                name="Agent 2",
                domain="domain2",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]
        mock_load_catalog.return_value = mock_entries

        # Mock dependencies
        mock_agent_factory = Mock()
        mock_intent_router = Mock()
        mock_state_manager = Mock()

        # Act - should complete without errors
        manager = MultiAgentConversationManager(
            agent_factory=mock_agent_factory,
            intent_router=mock_intent_router,
            state_manager=mock_state_manager,
        )

        # Assert - catalog was loaded
        mock_load_catalog.assert_called_once()
        assert manager.catalog_tool is not None
        assert isinstance(manager.catalog_tool, ServiceCatalogTool)
