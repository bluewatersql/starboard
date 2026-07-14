#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Generate test file templates for untested modules.

Usage:
    python scripts/generate_test_template.py api/chat/conversation_routes.py
    python scripts/generate_test_template.py services/message_processor.py --type integration
    python scripts/generate_test_template.py agents/domain_agent.py --force
"""

import argparse
import ast
import re
from pathlib import Path


class TestTemplateGenerator:
    """Generates test file templates based on source code analysis."""

    def __init__(self, source_file: Path, test_type: str = "unit"):
        """
        Initialize generator.

        Args:
            source_file: Path to source file to generate tests for
            test_type: Type of tests ('unit' or 'integration')
        """
        self.source_file = source_file
        self.test_type = test_type
        self.module_path = self._get_module_path()
        self.test_file_path = self._get_test_file_path()

    def _get_module_path(self) -> str:
        """Get Python module path from file path."""
        # Remove packages/starboard-server/ prefix if present
        path_str = str(self.source_file)
        if "packages/starboard-server/" in path_str:
            path_str = path_str.split("packages/starboard-server/")[1]

        # Convert file path to module path
        module = path_str.replace(".py", "").replace("/", ".")
        return module

    def _get_test_file_path(self) -> Path:
        """Get test file path."""
        # Get relative path from starboard
        path_str = str(self.source_file)
        if "starboard/" in path_str:
            rel_path = path_str.split("starboard/")[1]
        else:
            rel_path = path_str

        # Construct test path
        test_base = Path("tests") / self.test_type
        test_file = test_base / rel_path.replace(".py", "_test.py")

        return test_file

    def analyze_source(self) -> tuple[list[str], list[str], list[str]]:
        """
        Analyze source file to extract testable components.

        Returns:
            Tuple of (classes, functions, async_functions)
        """
        if not self.source_file.exists():
            return [], [], []

        with self.source_file.open() as f:
            try:
                tree = ast.parse(f.read())
            except SyntaxError:
                return [], [], []

        classes = []
        functions = []
        async_functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Skip private classes
                if not node.name.startswith("_"):
                    classes.append(node.name)
            elif isinstance(node, ast.FunctionDef):
                # Only top-level functions
                if not node.name.startswith("_"):
                    functions.append(node.name)
            elif isinstance(node, ast.AsyncFunctionDef):
                if not node.name.startswith("_"):
                    async_functions.append(node.name)

        return classes, functions, async_functions

    def generate_template(self) -> str:
        """Generate test file template."""
        classes, functions, async_functions = self.analyze_source()

        # Build template
        lines = []

        # Header
        lines.append(f'"""Tests for {self.module_path}."""')
        lines.append("")

        # Imports
        lines.append("import pytest")
        if async_functions or self.test_type == "integration":
            lines.append("from unittest.mock import Mock, patch, AsyncMock")
        else:
            lines.append("from unittest.mock import Mock, patch")
        lines.append("")
        lines.append(f"from {self.module_path} import (")

        # Import discovered components
        all_components = classes + functions + async_functions
        if all_components:
            for component in all_components[:5]:  # Limit to first 5
                lines.append(f"    {component},")
            if len(all_components) > 5:
                lines.append("    # ... add more imports as needed")
        else:
            lines.append("    # Add imports here")

        lines.append(")")
        lines.append("")
        lines.append("")

        # Fixtures
        lines.append("# Fixtures")
        lines.append("")

        if classes:
            # Generate fixture for first class
            class_name = classes[0]
            fixture_name = self._to_snake_case(class_name)

            lines.append("@pytest.fixture")
            lines.append(f"def {fixture_name}():")
            lines.append(f'    """Create {class_name} instance for testing."""')
            lines.append(f"    # TODO: Configure {class_name} with test dependencies")
            lines.append(f"    return {class_name}(")
            lines.append("        # Add required parameters")
            lines.append("    )")
            lines.append("")
            lines.append("")

        # Test classes for each source class
        for class_name in classes:
            lines.extend(self._generate_class_tests(class_name))

        # Test functions
        for func_name in functions:
            lines.extend(self._generate_function_test(func_name, is_async=False))

        for func_name in async_functions:
            lines.extend(self._generate_function_test(func_name, is_async=True))

        # If no components found, add placeholder
        if not classes and not functions and not async_functions:
            lines.append("# TODO: Add tests here")
            lines.append("")
            lines.append("def test_placeholder():")
            lines.append('    """Placeholder test - replace with actual tests."""')
            lines.append("    assert True")
            lines.append("")

        return "\n".join(lines)

    def _generate_class_tests(self, class_name: str) -> list[str]:
        """Generate test class for a source class."""
        test_class_name = f"Test{class_name}"
        fixture_name = self._to_snake_case(class_name)

        lines = []
        lines.append(f"class {test_class_name}:")
        lines.append(f'    """Tests for {class_name}."""')
        lines.append("")

        # Initialization test
        lines.append(f"    def test_init(self, {fixture_name}):")
        lines.append(f'        """Test {class_name} initialization."""')
        lines.append(f"        assert {fixture_name} is not None")
        lines.append("        # TODO: Add initialization assertions")
        lines.append("")

        # Happy path test
        if self.test_type == "integration":
            lines.append("    @pytest.mark.asyncio")
            lines.append(f"    async def test_happy_path(self, {fixture_name}):")
        else:
            lines.append(f"    def test_happy_path(self, {fixture_name}):")

        lines.append(f'        """Test {class_name} happy path."""')
        lines.append("        # TODO: Implement happy path test")
        lines.append("        pass")
        lines.append("")

        # Error handling test
        if self.test_type == "integration":
            lines.append("    @pytest.mark.asyncio")
            lines.append(f"    async def test_error_handling(self, {fixture_name}):")
        else:
            lines.append(f"    def test_error_handling(self, {fixture_name}):")

        lines.append(f'        """Test {class_name} error handling."""')
        lines.append("        # TODO: Implement error handling test")
        lines.append("        pass")
        lines.append("")
        lines.append("")

        return lines

    def _generate_function_test(self, func_name: str, is_async: bool) -> list[str]:
        """Generate test for a function."""
        test_name = f"test_{func_name}"

        lines = []

        if is_async or self.test_type == "integration":
            lines.append("@pytest.mark.asyncio")
            lines.append(f"async def {test_name}():")
        else:
            lines.append(f"def {test_name}():")

        lines.append(f'    """Test {func_name} function."""')
        lines.append("    # Arrange")
        lines.append("    # TODO: Setup test data")
        lines.append("")
        lines.append("    # Act")
        if is_async:
            lines.append(f"    result = await {func_name}(...)")
        else:
            lines.append(f"    result = {func_name}(...)")
        lines.append("")
        lines.append("    # Assert")
        lines.append("    # TODO: Add assertions")
        lines.append("    assert result is not None")
        lines.append("")
        lines.append("")

        return lines

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert CamelCase to snake_case."""
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    def create_test_file(self, force: bool = False) -> Path:
        """
        Create test file with template.

        Args:
            force: Overwrite existing file

        Returns:
            Path to created test file
        """
        # Check if already exists
        if self.test_file_path.exists() and not force:
            raise FileExistsError(
                f"Test file already exists: {self.test_file_path}\n"
                "Use --force to overwrite"
            )

        # Create directory
        self.test_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate and write template
        template = self.generate_template()
        with self.test_file_path.open("w") as f:
            f.write(template)

        return self.test_file_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate test file template for a source file"
    )
    parser.add_argument(
        "source_file",
        type=Path,
        help="Source file to generate tests for (relative to starboard/)",
    )
    parser.add_argument(
        "--type",
        choices=["unit", "integration"],
        default="unit",
        help="Test type (default: unit)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing test file",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print template without creating file",
    )

    args = parser.parse_args()

    # Resolve source file path
    source_file = args.source_file

    # Try to find the file if it doesn't exist as-is
    if not source_file.exists():
        # Try in packages/starboard-server/starboard/
        alt_path = Path("packages/starboard-server/starboard") / source_file
        if alt_path.exists():
            source_file = alt_path
        else:
            print(f"Error: Source file not found: {source_file}")
            return 1

    # Generate template
    generator = TestTemplateGenerator(source_file, args.type)

    if args.print_only:
        print(generator.generate_template())
    else:
        try:
            test_file = generator.create_test_file(args.force)
            print(f"✓ Created test file: {test_file}")
            print("\nNext steps:")
            print(f"1. Open {test_file}")
            print("2. Fill in TODO sections")
            print(f"3. Run tests: pytest {test_file} -v")
        except FileExistsError as e:
            print(f"Error: {e}")
            return 1

    return 0


if __name__ == "__main__":
    exit(main())
