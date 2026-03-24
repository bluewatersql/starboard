"""Pytest configuration for starboard-server package.

This conftest registers fixtures from tests/fixtures.py.
It's placed at the package root to avoid import path collisions with root tests/conftest.py.
"""

import importlib.util
import sys
from pathlib import Path

# Load fixtures module dynamically
package_root = Path(__file__).parent
fixtures_path = package_root / "tests" / "fixtures.py"

if fixtures_path.exists():
    spec = importlib.util.spec_from_file_location("server_fixtures", fixtures_path)
    if spec and spec.loader:
        fixtures_module = importlib.util.module_from_spec(spec)
        sys.modules["server_fixtures"] = fixtures_module
        spec.loader.exec_module(fixtures_module)

        # Import fixtures into this namespace so pytest can discover them
        mock_config = fixtures_module.mock_config
        event_emitter = fixtures_module.event_emitter
        mock_event_emitter = fixtures_module.mock_event_emitter
        execution_context = fixtures_module.execution_context
        mock_llm_client = fixtures_module.mock_llm_client
        mock_llm_code_analysis = fixtures_module.mock_llm_code_analysis
        sample_task_sources = fixtures_module.sample_task_sources
        mock_context_provider = fixtures_module.mock_context_provider
        sample_query_profile = fixtures_module.sample_query_profile
        sample_job_config = fixtures_module.sample_job_config
        sample_table_metadata = fixtures_module.sample_table_metadata
        reset_event_emitter = fixtures_module.reset_event_emitter
