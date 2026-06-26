# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Test that log parser code does not contain print statements.

Following TDD: This test will fail initially, then we'll fix the code.

This test enforces the engineering standard: "No print statements in production code"
"""

import ast
from pathlib import Path


def find_print_statements(file_path: Path) -> list[tuple[int, str]]:
    """
    Find all print() calls in a Python file.

    Args:
        file_path: Path to Python file to check

    Returns:
        List of (line_number, line_content) tuples for each print statement found
    """
    print_statements = []

    try:
        with open(file_path) as f:
            source = f.read()

        tree = ast.parse(source, filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):  # noqa: SIM102
                # Check if it's a call to 'print'
                if isinstance(node.func, ast.Name) and node.func.id == "print":
                    line_num = node.lineno
                    # Get the actual line content
                    lines = source.split("\n")
                    line_content = (
                        lines[line_num - 1].strip() if line_num <= len(lines) else ""
                    )

                    # Skip if it's a commented print
                    if not line_content.startswith("#"):
                        print_statements.append((line_num, line_content))

    except SyntaxError:
        # Skip files with syntax errors
        pass

    return print_statements


def test_no_print_statements_in_log_parser():
    """
    Test that there are no print() statements in log parser code.

    Print statements should be replaced with proper logging using the logging module.

    Expected violations (before fix):
    - task_model.py:89 - print("Shuffle open time: ", shuffle_open_time)
    - task_model.py:95 - print("Shuffle close time: ", shuffle_close_time)
    """
    # Get log parser directory - this is the starboard_log_parser package
    log_parser_dir = Path(__file__).parent.parent.parent / "starboard_log_parser"

    if not log_parser_dir.exists():
        # Log parser not found, skip test
        import pytest

        pytest.skip(f"Log parser directory not found: {log_parser_dir}")

    # Find all Python files
    python_files = list(log_parser_dir.rglob("*.py"))

    # Check each file for print statements
    violations = {}
    for py_file in python_files:
        print_stmts = find_print_statements(py_file)
        if print_stmts:
            relative_path = py_file.relative_to(log_parser_dir)
            violations[str(relative_path)] = print_stmts

    # Format error message
    if violations:
        error_msg = "\n\nFound print() statements in log parser code:\n"
        error_msg += "=" * 80 + "\n"

        for file_path, print_stmts in violations.items():
            error_msg += f"\n{file_path}:\n"
            for line_num, line_content in print_stmts:
                error_msg += f"  Line {line_num}: {line_content}\n"

        error_msg += "\n" + "=" * 80 + "\n"
        error_msg += "\nPrint statements must be replaced with proper logging:\n"
        error_msg += "  import logging\n"
        error_msg += "  logger = logging.getLogger(__name__)\n"
        error_msg += "  logger.debug('message', extra={'key': value})\n"
        error_msg += "\nSee: Repository Engineering Standards - 'No print statements'\n"

        raise AssertionError(error_msg)


def test_example_proper_logging():
    """
    Example of proper logging to replace print statements.

    This test documents the expected pattern.
    """
    # This is how logging should be done:
    import logging

    logger = logging.getLogger(__name__)

    # Instead of: print("Shuffle open time:", shuffle_open_time)
    # Use:
    shuffle_open_time = 1.234
    logger.debug(
        "shuffle_metric_parsed",
        extra={
            "metric_type": "open_time",
            "value_seconds": shuffle_open_time,
        },
    )

    # Test passes to document the pattern
    assert True


if __name__ == "__main__":
    # Allow running this as a script to find violations
    test_no_print_statements_in_log_parser()
    print("\n✅ No print statements found!")
