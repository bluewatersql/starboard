"""Pytest configuration and shared fixtures for starboard-core tests."""

import warnings

import pytest

# Filter warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")


@pytest.fixture
def sample_domain_model():
    """Provide a sample domain model for testing core models."""
    return {
        "id": "test-123",
        "name": "test_model",
        "created_at": "2025-11-15T00:00:00Z",
    }
