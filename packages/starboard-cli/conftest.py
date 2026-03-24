"""Pytest configuration for starboard-cli package.

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
    spec = importlib.util.spec_from_file_location("cli_fixtures", fixtures_path)
    if spec and spec.loader:
        fixtures_module = importlib.util.module_from_spec(spec)
        sys.modules["cli_fixtures"] = fixtures_module
        spec.loader.exec_module(fixtures_module)

        # Import fixtures into this namespace so pytest can discover them
        temp_config_file = fixtures_module.temp_config_file
