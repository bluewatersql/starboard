"""Architecture fitness test — GUIDELINE-010: Dependency hygiene.

For each package in the monorepo, every top-level import used in the source
code should correspond to a declared dependency in ``pyproject.toml``, and
every declared dependency should be used somewhere in the source.

The test performs a best-effort mapping:

1. Parses ``[project].dependencies`` from each package's ``pyproject.toml``
   using the ``tomllib`` standard-library module (Python 3.11+).
2. Extracts the distribution name from each dependency specifier and maps it
   to a likely import name (e.g. ``python-multipart`` → ``multipart``,
   ``databricks-sdk`` → ``databricks``).
3. Collects all top-level imports (``import X`` / ``from X import``) from the
   package's source tree.
4. Reports (a) imports with no matching declared dependency and (b) declared
   dependencies with no matching import.

STATUS: Expected to FAIL because the codebase has unused declared dependencies
and/or imports whose mapping is missing.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

# Packages that are part of this workspace — skip undeclared-import checks for them
_WORKSPACE_PACKAGES = {
    "starboard_core",
    "starboard_server",
    "starboard_cli",
    "starboard_sdk",
    "starboard_log_parser",
}

# Known stdlib top-level modules — these need no declared dependency
_STDLIB_MODULES = {
    "abc",
    "ast",
    "asyncio",
    "base64",
    "builtins",
    "collections",
    "concurrent",
    "contextlib",
    "copy",
    "dataclasses",
    "datetime",
    "decimal",
    "difflib",
    "email",
    "enum",
    "fnmatch",
    "functools",
    "gc",
    "glob",
    "gzip",
    "hashlib",
    "hmac",
    "html",
    "http",
    "importlib",
    "inspect",
    "io",
    "itertools",
    "json",
    "logging",
    "math",
    "mimetypes",
    "os",
    "pathlib",
    "pickle",
    "platform",
    "pprint",
    "queue",
    "random",
    "re",
    "shutil",
    "signal",
    "socket",
    "sqlite3",
    "ssl",
    "stat",
    "string",
    "struct",
    "subprocess",
    "sys",
    "tempfile",
    "textwrap",
    "threading",
    "time",
    "traceback",
    "types",
    "typing",
    "unittest",
    "urllib",
    "uuid",
    "warnings",
    "weakref",
    "xml",
    "zipfile",
    "__future__",
    "tomllib",
    "tomlib",
    "argparse",
    "atexit",
    "contextvars",
    "statistics",
    "unicodedata",
    "zoneinfo",
}

# Manual overrides: dist-name -> import-name when the mapping is non-obvious
_DIST_TO_IMPORT: dict[str, str] = {
    "python-multipart": "multipart",
    "databricks-sdk": "databricks",
    "databricks-sql-connector": "databricks",
    "openai": "openai",
    "tiktoken": "tiktoken",
    "pyarrow": "pyarrow",
    "sqlglot": "sqlglot",
    "sqlparse": "sqlparse",
    "rapidfuzz": "rapidfuzz",
    "pydantic": "pydantic",
    "pydantic-settings": "pydantic_settings",
    "structlog": "structlog",
    "uvicorn": "uvicorn",
    "fastapi": "fastapi",
    "websockets": "websockets",
    "aiosqlite": "aiosqlite",
    "aiohttp": "aiohttp",
    "httpx": "httpx",
    "requests": "requests",
    "redis": "redis",
    "asyncpg": "asyncpg",
    "psycopg2-binary": "psycopg2",
    "psycopg": "psycopg",
    "numpy": "numpy",
    "pandas": "pandas",
    "polars": "polars",
    "altair": "altair",
    "tenacity": "tenacity",
    "cachetools": "cachetools",
    "python-jose": "jose",
    "cryptography": "cryptography",
    "passlib": "passlib",
    "bcrypt": "bcrypt",
    "click": "click",
    "rich": "rich",
    "typer": "typer",
    "pytest": "pytest",
    "pytest-asyncio": "pytest_asyncio",
    "respx": "respx",
    "freezegun": "freezegun",
    "factory-boy": "factory",
    "faker": "faker",
    "mypy": "mypy",
    "ruff": "ruff",
    "sqlite-vec": "sqlite_vec",
    "sentence-transformers": "sentence_transformers",
    "opentelemetry-api": "opentelemetry",
    "opentelemetry-sdk": "opentelemetry",
    "vl-convert-python": "vl_convert",
    "python-dotenv": "dotenv",
    "pyyaml": "yaml",
}

# Dependencies that are used indirectly (not via Python import)
_INDIRECT_DEPENDENCIES = {
    "asyncpg",  # Used via SQLAlchemy async engine
    "multipart",  # Required by FastAPI for form parsing
    "pgvector",  # Used via SQL extension, not Python import
    "sqlite_vec",  # Loaded as SQLite extension, not imported
    "rich",  # Used by CLI (server declares for downstream consumers)
    "dotenv",  # Used by CLI (server declares for downstream consumers)
}

# Transitive dependencies that are technically undeclared but come from declared deps
_KNOWN_TRANSITIVES = {
    "starlette",  # Transitive via fastapi
}

# Dependencies declared in optional extras, actively used
_OPTIONAL_DEPENDENCIES = {
    "opentelemetry",  # In [observability] extras, actively used
}


def _dist_to_import_name(dist: str) -> str:
    """Convert a distribution name to its likely top-level import name."""
    if dist in _DIST_TO_IMPORT:
        return _DIST_TO_IMPORT[dist]
    # Strip version specifiers
    base = re.split(r"[>=<!;\[@ ]", dist)[0].strip().lower()
    # Replace hyphens with underscores (common convention)
    return base.replace("-", "_")


def _parse_dependencies(pyproject_path: Path) -> list[str]:
    """Return list of declared dependency distribution names."""
    if tomllib is None:
        return []
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    deps: list[str] = data.get("project", {}).get("dependencies", [])
    names: list[str] = []
    for dep in deps:
        # e.g. "fastapi>=0.104.0,<1.0.0" -> "fastapi"
        name = re.split(r"[>=<!;\[@ ]", dep)[0].strip()
        if name:
            names.append(name.lower())
    return names


def _collect_top_level_imports(source_dir: Path) -> set[str]:
    """Return set of top-level module names imported in *source_dir*."""
    imports: set[str] = set()
    for py_file in source_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.split(".")[0])
    return imports


def _check_package(
    package_name: str, package_dir: Path, source_subdir: str, project_root: Path
) -> tuple[list[str], list[str]]:
    """Return (undeclared_imports, unused_deps) for a package."""
    pyproject = package_dir / "pyproject.toml"
    source_dir = package_dir / source_subdir
    if not pyproject.exists() or not source_dir.exists():
        return [], []

    declared_dists = _parse_dependencies(pyproject)
    declared_imports = {_dist_to_import_name(d) for d in declared_dists}

    actual_imports = _collect_top_level_imports(source_dir)
    # Remove stdlib, workspace packages, and private/relative imports
    third_party = {
        m
        for m in actual_imports
        if m not in _STDLIB_MODULES
        and m not in _WORKSPACE_PACKAGES
        and not m.startswith("_")
    }

    undeclared = sorted(
        third_party
        - declared_imports
        - _WORKSPACE_PACKAGES
        - _KNOWN_TRANSITIVES
        - _OPTIONAL_DEPENDENCIES
    )
    unused = sorted(
        declared_imports - third_party - _WORKSPACE_PACKAGES - _INDIRECT_DEPENDENCIES
    )
    return undeclared, unused


@pytest.mark.unit
def test_server_package_dependency_hygiene(project_root: Path) -> None:
    """starboard-server imports must all be declared; declared deps must be used."""
    package_dir = project_root / "packages" / "starboard-server"
    undeclared, unused = _check_package(
        "starboard_server", package_dir, "starboard_server", project_root
    )

    messages: list[str] = []
    if undeclared:
        messages.append(
            "  Undeclared imports (used but not in pyproject.toml):\n"
            + "\n".join(f"    - {m}" for m in undeclared)
        )
    if unused:
        messages.append(
            "  Unused dependencies (declared but not imported):\n"
            + "\n".join(f"    - {m}" for m in unused)
        )

    assert not messages, (
        "GUIDELINE-010: Dependency hygiene violations in starboard-server:\n"
        + "\n".join(messages)
    )


@pytest.mark.unit
def test_cli_package_dependency_hygiene(project_root: Path) -> None:
    """starboard-cli imports must all be declared; declared deps must be used."""
    package_dir = project_root / "packages" / "starboard-cli"
    undeclared, unused = _check_package(
        "starboard_cli", package_dir, "starboard_cli", project_root
    )

    messages: list[str] = []
    if undeclared:
        messages.append(
            "  Undeclared imports:\n" + "\n".join(f"    - {m}" for m in undeclared)
        )
    if unused:
        messages.append(
            "  Unused dependencies:\n" + "\n".join(f"    - {m}" for m in unused)
        )

    assert not messages, (
        "GUIDELINE-010: Dependency hygiene violations in starboard-cli:\n"
        + "\n".join(messages)
    )


@pytest.mark.unit
def test_sdk_package_dependency_hygiene(project_root: Path) -> None:
    """starboard-sdk imports must all be declared; declared deps must be used."""
    package_dir = project_root / "packages" / "starboard-sdk"
    undeclared, unused = _check_package(
        "starboard_sdk", package_dir, "starboard_sdk", project_root
    )

    messages: list[str] = []
    if undeclared:
        messages.append(
            "  Undeclared imports:\n" + "\n".join(f"    - {m}" for m in undeclared)
        )
    if unused:
        messages.append(
            "  Unused dependencies:\n" + "\n".join(f"    - {m}" for m in unused)
        )

    assert not messages, (
        "GUIDELINE-010: Dependency hygiene violations in starboard-sdk:\n"
        + "\n".join(messages)
    )
