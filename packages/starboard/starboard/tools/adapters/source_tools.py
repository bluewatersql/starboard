# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Async reasoning interface for source code tools.

This module provides the LLM-facing interface for source code operations:
- Extracting source code from Databricks job tasks
- Analyzing code quality with LLM
- Getting task definitions

Architecture:
    SourceTools (adapter) → SourceTransformer (domain) + Databricks API
"""

from __future__ import annotations

import asyncio
import posixpath
from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from databricks.sdk.errors import DatabricksError
from starboard_core.domain.source.import_following import (
    extract_imports,
    resolve_candidates,
)
from starboard_core.domain.source.ranking import rank_and_trim_artifacts
from starboard_core.domain.source.run_following import (
    extract_run_targets,
    resolve_run_path,
)
from starboard_core.domain.transformers.job_transformers import transform_task_sources

from starboard.exceptions import AdapterError, ToolError
from starboard.infra.observability.events import EventEmitter
from starboard.infra.observability.logging import get_logger
from starboard.tools.adapters.base import BaseToolAdapter
from starboard.tools.domain.source import SourceTransformer
from starboard.tools.domain.source.models import CodeQualityIssue
from starboard.tools.domain.utils import pack_dict

if TYPE_CHECKING:
    from starboard.adapters.databricks import AsyncDatabricksClient
    from starboard.adapters.llm.base import BaseLLMClient

logger = get_logger(__name__)

# =============================================================================
# %run-following bounds (BFS walk)
# =============================================================================

_MAX_DEPTH: int = 5
_MAX_FILES: int = 40
_MAX_BYTES: int = 1_048_576  # 1 MiB cumulative code
_MAX_USER_DIRS_PER_BASE: int = 50  # user/group dirs scanned per Repos base in git_source search
_MAX_ANALYSIS_BYTES: int = 262_144  # 256 KiB LLM prompt budget for code artifacts

# =============================================================================
# LLM Prompts and Schemas
# =============================================================================

CODE_PASS_SYSTEM_PROMPT = """You are a senior Databricks & Spark performance and optimization expert.

MISSION: Audit code for performance issues and provide precise, safe, incremental optimizations.

FOCUS AREAS:
1. Databricks-native features:
   - Photon vectorization, AQE, Dynamic Partition Pruning
   - Liquid Clustering, Predictive I/O
   - SQL Warehouse & Unity Catalog integration
   - Intelligent caching and shuffle minimization

2. Anti-patterns to flag:
   - Data collection: collect(), toPandas() on large datasets
   - Aggregations: wide groupBy without stats, missing broadcast hints
   - Joins: non-broadcastable joins, Cartesian products
   - UDFs: excessive Python UDFs (prefer native Spark)
   - Operations: nested explode, file-at-a-time loops
   - Partitioning: misuse of repartition/coalesce
   - I/O: tiny file writes (<128MB), caching without reuse
   - Correctness: nondeterministic order reliance

PRIORITIZATION:
If you find >10 issues:
1. Score each by: (performance_impact × confidence) - risk_score
2. Select top 5-10 highest-scoring issues
3. Ensure mix of quick wins (low effort, high impact) and strategic fixes

SAFETY REQUIREMENTS:
- Maintain correctness (no semantic changes unless explicitly safe)
- Provide before/after code snippets
- Document risks and rollback steps

OUTPUT:
Return JSON with "hotspots" array (5-10 items max) and optional "notes" array.
If code is fully optimized, return empty hotspots array with explanatory note."""

CODE_PASS_SCHEMA = {
    "type": "object",
    "properties": {
        "hotspots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "artifact": {"type": "string"},
                    "line_range": {"type": "string"},
                    "issue": {"type": "string"},
                    "signal": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                    "risk": {"type": "string"},
                    "fix": {
                        "type": "object",
                        "properties": {
                            "strategy": {"type": "string"},
                            "snippet_before": {"type": "string"},
                            "snippet_after": {"type": "string"},
                        },
                        "required": ["strategy", "snippet_before", "snippet_after"],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "artifact",
                    "line_range",
                    "issue",
                    "signal",
                    "evidence",
                    "risk",
                    "fix",
                ],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hotspots", "notes"],
    "additionalProperties": False,
}


# =============================================================================
# SourceTools
# =============================================================================


class AnalysisMode(StrEnum):
    """Analysis strategy for code quality.

    Use ``BATCH`` (default) to analyze all code in a single LLM call, or
    ``INDIVIDUAL`` to analyze each artifact separately in parallel.
    """

    BATCH = "batch"
    """Analyze all code in single LLM call."""

    INDIVIDUAL = "individual"
    """Analyze each artifact separately in parallel."""


class SourceTools(BaseToolAdapter):
    """Async reasoning interface for source code operations.

    Clean interface optimized for LLM reasoning. Combines the adapter
    and service layers for direct access to source code operations.

    Example:
        >>> tools = SourceTools(api, llm_client, events=events)
        >>> result = await tools.get_source_code(job_id="12345")
    """

    def __init__(
        self,
        api: AsyncDatabricksClient,
        llm_client: BaseLLMClient | None = None,
        *,
        events: EventEmitter | None = None,
    ):
        """Initialize source tools.

        Args:
            api: Async Databricks client for source code fetching
            llm_client: Optional LLM client for code analysis
            events: Optional event emitter for status updates
        """
        super().__init__(events=events)
        self.databricks_api = api
        self.llm_client = llm_client

    # =========================================================================
    # Public Methods (LLM-facing interface)
    # =========================================================================

    async def get_source_code(
        self,
        job_id: str,
        task_key: str | None = None,
    ) -> dict[str, Any]:
        """Get source code for job tasks.

        Args:
            job_id: Databricks job ID
            task_key: Optional specific task key to filter

        Returns:
            Dict with task sources and metadata

        Example:
            >>> result = await tools.get_source_code(
            ...     job_id="12345",
            ...     task_key="ingest_data"
            ... )
            >>> # Returns:
            >>> # {
            >>> #   "task_sources": {
            >>> #     "ingest_data": {
            >>> #       "type": "notebook",
            >>> #       "path": "/path/to/notebook",
            >>> #       "source": "# code here..."
            >>> #     }
            >>> #   },
            >>> #   "has_source_code": true,
            >>> #   "task_count": 1
            >>> # }
        """
        result = await self._inspect_source_code(job_id, task_key)

        # Extract the relevant data for response
        task_sources = result.get("task_sources", {})
        has_source_code = result.get("has_source_code", False)

        return {
            "task_sources": task_sources,
            "has_source_code": has_source_code,
            "task_count": len(task_sources),
        }

    async def analyze_code_quality(
        self,
        source_code: str | None = None,
        job_id: str | None = None,
        task_key: str | None = None,
        language: str | None = None,  # noqa: ARG002
        mode: AnalysisMode = AnalysisMode.BATCH,
        hot_paths: Sequence[str] | None = None,
        runtime_context: str | None = None,
    ) -> dict[str, Any]:
        """Analyze source code for quality issues using LLM.

        Supports two input modes:
        1. Direct source_code analysis (adhoc code)
        2. Job ID to fetch and analyze all task sources

        Args:
            source_code: Optional adhoc source code to analyze
            job_id: Optional job ID to fetch sources from
            task_key: Optional specific task key to filter (requires job_id)
            language: Optional language hint (auto-detected if not provided)
            mode: Analysis strategy (BATCH or INDIVIDUAL). Default: BATCH.
            hot_paths: Optional runtime-signal paths to rank first in the
                context budget (e.g. hot stage file paths from run history).
            runtime_context: Optional runtime metrics string rendered into
                the ``RUNTIME CONTEXT`` block of the analysis prompt.

        Returns:
            Dict with quality issues and notes

        Example:
            >>> # Adhoc code analysis
            >>> result = await tools.analyze_code_quality(
            ...     source_code="SELECT * FROM large_table"
            ... )
            >>> # Returns:
            >>> # {
            ...   "issues": [
            ...     {
            ...       "context": "adhoc",
            ...       "severity": "high",
            ...       "issue": "Full table scan",
            ...       "description": "Query performs full scan without filters",
            ...       "recommendation": "Add WHERE clause to filter data"
            ...     }
            ...   ],
            ...   "notes": ["Code analyzed successfully"],
            ...   "issue_count": 1
            ... }

            >>> # Job source analysis
            >>> result = await tools.analyze_code_quality(job_id="12345")
        """
        task_sources = None

        # If job_id provided, fetch sources first
        if job_id:
            inspect_result = await self._inspect_source_code(job_id, task_key)
            task_sources = inspect_result.get("task_sources")

        # Analyze code
        result = await self._analyze_code_quality(
            source_code=source_code,
            task_sources=task_sources,
            task_key=task_key,
            mode=mode,
            hot_paths=hot_paths,
            runtime_context=runtime_context,
        )

        # Extract data from result
        issues = result.get("code_quality_issues", [])
        notes = result.get("code_quality_notes", [])

        return {
            "issues": issues,
            "notes": notes,
            "issue_count": len(issues),
        }

    async def get_task_definitions(
        self,
        job_id: str,
        task_key: str | None = None,
    ) -> dict[str, Any]:
        """Fetch task definitions from job configuration.

        Args:
            job_id: Databricks job ID
            task_key: Optional specific task key to filter

        Returns:
            Dict with task definitions

        Example:
            >>> result = await tools.get_task_definitions(job_id="12345")
            >>> # Returns:
            >>> # {
            >>> #   "tasks": [
            >>> #     {
            >>> #       "task_key": "ingest_data",
            >>> #       "notebook_task": {"notebook_path": "/path"},
            >>> #       ...
            >>> #     }
            >>> #   ],
            >>> #   "task_count": 1
            >>> # }
        """
        tasks = await self._get_task_definitions_from_job(job_id, task_key)

        return {
            "tasks": tasks,
            "task_count": len(tasks),
        }

    # =========================================================================
    # Internal Implementation Methods
    # =========================================================================

    def _emit_info(self, source: str, message: str) -> None:
        """Emit info event."""
        self.events.emit_info(source=source, message=message)

    # =========================================================================
    # Source-graph walk helpers (Phase 3)
    # =========================================================================

    @staticmethod
    def _resolution_roots(path: str) -> list[str]:
        """Compute ordered import-resolution roots for a workspace file.

        Returns ``[dirname(path)]`` plus:

        - If *path* is inside a Repos tree
          (``/Repos/<user>/<repo>/…`` or ``/Workspace/Repos/<user>/<repo>/…``),
          the repo root ``/Repos/<user>/<repo>`` (or its Workspace equivalent).
        - If *path* is inside a DAB bundle sync tree
          (``…/.bundle/<bundle>/<target>/files/…``), the ``…/files`` directory
          (Phase 5).

        Deduplicates; dirname first.

        Args:
            path: Absolute workspace path of a Python file.

        Returns:
            Ordered list of root paths to probe during import resolution.
        """
        dir_path = posixpath.dirname(path)
        roots: list[str] = [dir_path]

        for prefix in ("/Workspace/Repos/", "/Repos/"):
            if path.startswith(prefix):
                rest = path[len(prefix):]
                parts = rest.split("/")
                # Need at least <user>/<repo>/<file> to identify a repo root.
                if len(parts) >= 3:
                    repo_root = posixpath.normpath(
                        prefix.rstrip("/") + "/" + parts[0] + "/" + parts[1]
                    )
                    if repo_root != dir_path:
                        roots.append(repo_root)
                break

        # Phase 5: DAB bundle sync root detection.
        # Layout: …/.bundle/<bundle_name>/<target>/files/<project-relative path>
        # The bundle root (sys.path equivalent) is the …/files directory.
        parts = path.split("/")
        try:
            bundle_idx = parts.index(".bundle")
            # Find the first "files" segment that appears after .bundle.
            files_idx = next(
                (i for i in range(bundle_idx + 1, len(parts)) if parts[i] == "files"),
                None,
            )
            if files_idx is not None:
                bundle_root = "/".join(parts[: files_idx + 1])
                if bundle_root and bundle_root not in roots:
                    roots.append(bundle_root)
        except ValueError:
            pass  # no .bundle segment — not a bundle path

        return roots

    async def _walk_source_graph(
        self,
        entry_path: str,
        entry_source: str,
        *,
        follow_runs: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """BFS walk from an entry file, following ``%run`` and/or ``import``.

        Args:
            entry_path:   Absolute workspace path of the entry file.
            entry_source: Source text of the entry file.
            follow_runs:  When ``True`` also follow ``%run`` directives (for
                          notebooks).  ``import`` following is always active.

        Returns:
            A ``(resolved_files, resolution)`` tuple where:

            - *resolved_files*: list of ``{path, code, reason, depth}`` dicts,
              entry file first.
            - *resolution*: ``{roots, truncated, limits, dropped}`` metadata.
        """
        resolved_files: list[dict[str, Any]] = [
            {"path": entry_path, "code": entry_source, "reason": "entry", "depth": 0}
        ]
        visited: set[str] = {entry_path}
        total_bytes: int = len(entry_source.encode())
        truncated: bool = False

        # Collect all roots seen across every file in the walk
        all_roots: list[str] = []
        for r in self._resolution_roots(entry_path):
            if r not in all_roots:
                all_roots.append(r)

        # Dropped unresolved import refs (deduped by key)
        dropped: list[dict[str, str]] = []
        dropped_keys: set[str] = set()

        # Per-directory listing cache: dir_path → set of FILE basenames
        dir_cache: dict[str, set[str]] = {}

        # Queue items: (path, source, depth)
        queue: list[tuple[str, str, int]] = [(entry_path, entry_source, 0)]

        while queue:
            current_path, current_source, current_depth = queue.pop(0)
            current_roots = self._resolution_roots(current_path)

            # ----------------------------------------------------------------
            # (a) %run following (notebooks only)
            # ----------------------------------------------------------------
            if follow_runs:
                for target in extract_run_targets(current_source):
                    resolved = resolve_run_path(current_path, target)
                    if resolved in visited:
                        continue
                    visited.add(resolved)

                    if current_depth >= _MAX_DEPTH:
                        truncated = True
                        continue
                    if len(resolved_files) >= _MAX_FILES:
                        truncated = True
                        continue

                    try:
                        child_src = (
                            await self.databricks_api.workspace.get_notebook_content(
                                resolved
                            )
                        )
                    except (ToolError, AdapterError, ValueError) as exc:
                        logger.warning(f"Failed to fetch %run target {resolved}: {exc}")
                        continue

                    if not child_src:
                        logger.warning(f"Empty content for %run target {resolved}")
                        continue

                    child_bytes = len(child_src.encode())
                    if total_bytes + child_bytes > _MAX_BYTES:
                        truncated = True
                        continue

                    total_bytes += child_bytes
                    child_depth = current_depth + 1
                    resolved_files.append(
                        {
                            "path": resolved,
                            "code": child_src,
                            "reason": "run",
                            "depth": child_depth,
                        }
                    )
                    queue.append((resolved, child_src, child_depth))
                    for r in self._resolution_roots(resolved):
                        if r not in all_roots:
                            all_roots.append(r)

            # ----------------------------------------------------------------
            # (b) import following (always active)
            # ----------------------------------------------------------------
            for ref in extract_imports(current_source):
                candidates = resolve_candidates(ref, current_path, current_roots)
                if not candidates:
                    continue

                # Find the first existing candidate using the dir-listing cache
                resolved_import: str | None = None
                for candidate in candidates:
                    parent_dir = posixpath.dirname(candidate)
                    basename = posixpath.basename(candidate)

                    if parent_dir not in dir_cache:
                        try:
                            listing = (
                                await self.databricks_api.workspace.list_workspace(
                                    parent_dir
                                )
                            )
                            dir_cache[parent_dir] = {
                                posixpath.basename(item["path"])
                                for item in listing
                                if item.get("object_type") == "FILE"
                            }
                        except Exception:  # noqa: BLE001 — skip on any list failure
                            dir_cache[parent_dir] = set()

                    if basename in dir_cache.get(parent_dir, set()):
                        resolved_import = candidate
                        break

                if resolved_import is None:
                    # No workspace file found — record as unresolved (first-party miss)
                    drop_key = ref.module if ref.module else ".".join(ref.names)
                    if drop_key and drop_key not in dropped_keys:
                        dropped.append({"module": drop_key, "reason": "unresolved"})
                        dropped_keys.add(drop_key)
                    continue

                if resolved_import in visited:
                    continue
                visited.add(resolved_import)

                if current_depth >= _MAX_DEPTH:
                    truncated = True
                    continue
                if len(resolved_files) >= _MAX_FILES:
                    truncated = True
                    continue

                try:
                    import_src = (
                        await self.databricks_api.workspace.export_workspace_file(
                            resolved_import
                        )
                    )
                except (ToolError, AdapterError, ValueError) as exc:
                    logger.warning(
                        f"Failed to fetch import {resolved_import}: {exc}"
                    )
                    continue

                if not import_src:
                    logger.warning(f"Empty content for import {resolved_import}")
                    continue

                import_bytes = len(import_src.encode())
                if total_bytes + import_bytes > _MAX_BYTES:
                    truncated = True
                    continue

                total_bytes += import_bytes
                child_depth = current_depth + 1
                resolved_files.append(
                    {
                        "path": resolved_import,
                        "code": import_src,
                        "reason": "import",
                        "depth": child_depth,
                    }
                )
                queue.append((resolved_import, import_src, child_depth))
                for r in self._resolution_roots(resolved_import):
                    if r not in all_roots:
                        all_roots.append(r)

        resolution: dict[str, Any] = {
            "roots": all_roots,
            "truncated": truncated,
            "limits": {
                "max_depth": _MAX_DEPTH,
                "max_files": _MAX_FILES,
                "max_bytes": _MAX_BYTES,
            },
            "dropped": dropped,
        }
        return resolved_files, resolution

    async def _get_task_definitions_from_job(
        self, job_id: str, task_key: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch task definitions from job configuration.

        Args:
            job_id: Databricks job ID
            task_key: Optional specific task key to filter

        Returns:
            List of task definition dictionaries
        """
        logger.debug("Fetching task definitions for job_id={job_id}")

        try:
            job_id_int = int(job_id)
            job_config = await self.databricks_api.jobs.get_job(job_id_int)
        except (ValueError, TypeError):
            logger.error("Invalid job_id format: {job_id}, error: {e}")
            return []
        except (ToolError, AdapterError, DatabricksError):
            logger.error("Failed to fetch job config for job_id={job_id}: {e}")
            return []

        if not job_config:
            logger.warning("Could not fetch job config for job_id={job_id}")
            return []

        # Extract task definitions from job settings
        job_settings = job_config.get("settings", {})
        tasks = job_settings.get("tasks", [])

        # Filter to specific task if requested
        if task_key:
            filtered = [t for t in tasks if t.get("task_key") == task_key]
            if not filtered:
                logger.warning("Task key '{task_key}' not found in job {job_id}")
            return filtered

        return tasks

    async def _extract_notebook_source(
        self, task: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Extract source code from notebook task with transitive %run / import following.

        Fetches the entry notebook then calls :meth:`_walk_source_graph` with
        ``follow_runs=True``.  The returned ``resolved_files`` may include
        entries with ``reason`` of ``"entry"``, ``"run"``, or ``"import"``.
        The ``resolution`` dict gains a ``"dropped"`` key listing unresolved
        imports.

        If the entry notebook cannot be fetched, returns ``None`` (unchanged
        from the pre-Phase-2 behaviour).
        """
        notebook_path = task["notebook_task"].get("notebook_path")
        if not notebook_path:
            return None

        try:
            entry_source = await self.databricks_api.workspace.get_notebook_content(
                notebook_path
            )
        except (ToolError, AdapterError, ValueError) as exc:
            logger.warning(f"Failed to fetch notebook {notebook_path}: {exc}")
            return None

        if not entry_source:
            logger.warning(f"Notebook {notebook_path} returned empty content")
            return None

        resolved_files, resolution = await self._walk_source_graph(
            notebook_path, entry_source, follow_runs=True
        )

        return {
            "type": "notebook",
            "path": notebook_path,
            "source": entry_source,
            "resolved_files": resolved_files,
            "resolution": resolution,
        }

    # Remote/cloud storage schemes that cannot be fetched at analysis time.
    _REMOTE_SCHEMES = (
        "s3://",
        "s3a://",
        "gs://",
        "abfss://",
        "wasbs://",
        "http://",
        "https://",
    )

    async def _extract_python_source(self, task: dict[str, Any]) -> dict[str, Any] | None:
        """Extract source code from spark_python_task.

        Routes by path scheme:
        - ``dbfs:/`` paths use :meth:`read_dbfs_file` (Phase-1 behaviour, no walk).
        - Remote cloud paths (s3://, gs://, abfss://, etc.) degrade gracefully.
        - All other paths (workspace, /Repos, etc.) use :meth:`export_workspace_file`
          then call :meth:`_walk_source_graph` to follow transitive imports.

        Returns ``None`` only when ``python_file`` is absent; always returns a
        dict otherwise (with the placeholder source on any fetch failure).
        """
        python_file = task["spark_python_task"].get("python_file")
        if not python_file:
            return None

        placeholder = {
            "type": "python_file",
            "path": python_file,
            "source": f"# Python file: {python_file}\n# Source not available",
        }

        # Remote/cloud schemes cannot be fetched; degrade gracefully.
        if any(python_file.startswith(scheme) for scheme in self._REMOTE_SCHEMES):
            logger.warning(f"Cannot fetch remote Python file: {python_file}")
            return placeholder

        try:
            if python_file.startswith("dbfs:/"):
                # DBFS: fetch content only — no workspace import resolution possible.
                content = await self.databricks_api.workspace.read_dbfs_file(
                    python_file
                )
                if content:
                    return {
                        "type": "python_file",
                        "path": python_file,
                        "source": content,
                    }
                logger.warning(f"Python file {python_file} returned empty content")
            else:
                # Workspace / Repos: fetch then walk for transitive imports.
                content = await self.databricks_api.workspace.export_workspace_file(
                    python_file
                )
                if content:
                    resolved_files, resolution = await self._walk_source_graph(
                        python_file, content, follow_runs=False
                    )
                    return {
                        "type": "python_file",
                        "path": python_file,
                        "source": content,
                        "resolved_files": resolved_files,
                        "resolution": resolution,
                    }
                logger.warning(f"Python file {python_file} returned empty content")
        except (ToolError, AdapterError, ValueError) as e:
            logger.warning(f"Failed to fetch Python file {python_file}: {e}")

        return placeholder

    def _extract_sql_source(self, task: dict[str, Any]) -> dict[str, Any] | None:
        """Extract inline SQL from SQL task."""
        query = task["sql_task"].get("query", {}).get("query")
        if not query:
            return None

        return {
            "type": "sql",
            "source": query,
        }

    # =========================================================================
    # Source-graph helpers — Phase 4 (git_source)
    # =========================================================================

    @staticmethod
    def _derive_repo_name(git_url: str) -> str | None:
        """Derive a repository name from a git remote URL.

        Handles HTTPS (``https://host/org/repo.git``) and SSH
        (``git@host:org/repo.git``) forms.  Takes the last non-empty segment
        after normalising ``":"`` to ``"/"`` and strips a trailing ``.git``.

        Args:
            git_url: Git remote URL.

        Returns:
            Repository name string, or ``None`` if unparseable.
        """
        if not git_url:
            return None
        # Normalise ":" to "/" so both URL schemes split uniformly.
        segments = [s for s in git_url.replace(":", "/").split("/") if s]
        if not segments:
            return None
        name = segments[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name if name else None

    async def _find_git_checkout_file(
        self,
        repo_name: str,
        relative_path: str,
    ) -> str | None:
        """Locate an existing workspace checkout of a git repository file.

        Scans ``/Workspace/Repos`` then ``/Repos`` for user/group directories
        (capped at ``_MAX_USER_DIRS_PER_BASE`` entries per base).  For each
        candidate ``<user>/<repo_name>/<relative_path>``, verifies that the
        file's basename appears in the parent directory listing as a FILE or
        NOTEBOOK object (with ``.py`` suffix ignored for matching).

        Any ``list_workspace`` failure on an individual directory is silently
        skipped.

        Args:
            repo_name: Repository name derived from the git URL.
            relative_path: Relative path of the file within the repository.

        Returns:
            Absolute workspace path if found; ``None`` otherwise.
        """

        def _strip_py(name: str) -> str:
            return name[:-3] if name.endswith(".py") else name

        for base in ("/Workspace/Repos", "/Repos"):
            try:
                user_dirs = await self.databricks_api.workspace.list_workspace(base)
            except Exception:  # noqa: BLE001 — skip inaccessible base
                continue

            for user_dir_entry in user_dirs[:_MAX_USER_DIRS_PER_BASE]:
                if user_dir_entry.get("object_type") != "DIRECTORY":
                    continue
                user_dir = user_dir_entry["path"]
                candidate_file = posixpath.normpath(
                    f"{user_dir}/{repo_name}/{relative_path}"
                )
                parent_dir = posixpath.dirname(candidate_file)
                basename = posixpath.basename(candidate_file)

                try:
                    listing = await self.databricks_api.workspace.list_workspace(
                        parent_dir
                    )
                except Exception:  # noqa: BLE001 — skip inaccessible dirs
                    continue

                listing_basenames: set[str] = {
                    _strip_py(posixpath.basename(item["path"]))
                    for item in listing
                    if item.get("object_type") in ("FILE", "NOTEBOOK")
                }
                if _strip_py(basename) in listing_basenames:
                    return candidate_file

        return None

    async def _extract_git_source(
        self,
        task: dict[str, Any],
        git_source: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract source from a GIT-sourced task via an existing Repos checkout.

        Resolves the task's relative path against an existing
        ``/Workspace/Repos`` or ``/Repos`` checkout, fetches the entry file,
        and walks the source graph exactly like Phases 2–3.

        Never raises and never returns ``None``.  If no checkout is found, a
        graceful-degradation dict is returned (type, path, placeholder source,
        and resolution with ``dropped`` + ``caveats``).

        Args:
            task: Task definition containing ``notebook_task`` or
                ``spark_python_task``.
            git_source: Job-level ``git_source`` dict with ``git_url`` and
                ``git_branch`` / ``git_tag`` / ``git_commit``.

        Returns:
            Source dict with ``type``, ``path``, ``source``,
            ``resolved_files``, and ``resolution`` (including ``caveats``).
        """
        git_url: str = git_source.get("git_url", "")
        if git_source.get("git_branch"):
            ref = f"branch:{git_source['git_branch']}"
        elif git_source.get("git_tag"):
            ref = f"tag:{git_source['git_tag']}"
        elif git_source.get("git_commit"):
            ref = f"commit:{git_source['git_commit']}"
        else:
            ref = "unknown"

        is_notebook = "notebook_task" in task
        if is_notebook:
            relative_path: str = task["notebook_task"].get("notebook_path", "")
            task_type = "notebook"
        else:
            relative_path = task["spark_python_task"].get("python_file", "")
            task_type = "python_file"

        caveat = (
            "git_source read from an existing /Workspace/Repos checkout; "
            f"it may differ from the job's pinned {ref}"
        )

        def _degrade() -> dict[str, Any]:
            return {
                "type": task_type,
                "path": relative_path,
                "source": (
                    "# Source not available (git_source)\n"
                    f"# No workspace checkout found; see {git_url} @ {ref}"
                ),
                "resolution": {
                    "dropped": [
                        {"module": relative_path, "reason": "git_source_no_checkout"}
                    ],
                    "caveats": [caveat],
                },
            }

        repo_name = self._derive_repo_name(git_url) if git_url else None
        if not repo_name:
            return _degrade()

        abs_path = await self._find_git_checkout_file(repo_name, relative_path)
        if abs_path is None:
            return _degrade()

        try:
            if is_notebook:
                source = await self.databricks_api.workspace.get_notebook_content(
                    abs_path
                )
            else:
                source = await self.databricks_api.workspace.export_workspace_file(
                    abs_path
                )
        except (ToolError, AdapterError, ValueError) as exc:
            logger.warning(f"Failed to fetch git checkout file {abs_path}: {exc}")
            source = None

        if not source:
            return _degrade()

        resolved_files, resolution = await self._walk_source_graph(
            abs_path, source, follow_runs=is_notebook
        )
        resolution["caveats"] = [caveat]

        return {
            "type": task_type,
            "path": abs_path,
            "source": source,
            "resolved_files": resolved_files,
            "resolution": resolution,
        }

    async def _extract_task_source(
        self,
        task: dict[str, Any],
        git_source: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Extract source code from a task definition based on task type.

        If *git_source* is provided and the task's notebook/python sub-task
        carries ``source == "GIT"``, delegates to :meth:`_extract_git_source`
        (Phase 4).  Otherwise falls through to the Phase 1–3 paths.
        """
        # Phase 4: GIT-sourced tasks
        if git_source and (
            (
                "notebook_task" in task
                and task["notebook_task"].get("source") == "GIT"
            )
            or (
                "spark_python_task" in task
                and task["spark_python_task"].get("source") == "GIT"
            )
        ):
            return await self._extract_git_source(task, git_source)

        # Phase 1–3: normal workspace paths
        if "notebook_task" in task:
            return await self._extract_notebook_source(task)
        elif "spark_python_task" in task:
            return await self._extract_python_source(task)
        elif "sql_task" in task:
            return self._extract_sql_source(task)

        return None

    async def _inspect_source_code(
        self, job_id: str, task_key: str | None = None
    ) -> dict[str, Any]:
        """Fetch and parse task source code from job definitions."""
        self._emit_info(
            source="inspect_source_code",
            message=f"Inspecting source for job {job_id}",
        )

        # Fetch job config once — extract both tasks and git_source together.
        try:
            job_id_int = int(job_id)
            job_config = await self.databricks_api.jobs.get_job(job_id_int)
        except (ValueError, TypeError):
            logger.error("Invalid job_id format: {job_id}")
            return SourceTransformer.build_empty_source_result()
        except (ToolError, AdapterError, DatabricksError):
            logger.error("Failed to fetch job config for job_id={job_id}")
            return SourceTransformer.build_empty_source_result()

        if not job_config:
            logger.warning("Could not fetch job config for job_id={job_id}")
            return SourceTransformer.build_empty_source_result()

        job_settings = job_config.get("settings", {})
        tasks: list[dict[str, Any]] = job_settings.get("tasks", [])
        git_source: dict[str, Any] | None = job_settings.get("git_source")

        # Phase 5: DAB bundle deployment detection.
        deployment = job_settings.get("deployment")
        is_bundle = isinstance(deployment, dict) and deployment.get("kind") == "BUNDLE"

        # Filter to specific task if requested
        if task_key:
            filtered = [t for t in tasks if t.get("task_key") == task_key]
            if not filtered:
                logger.warning(f"Task key '{task_key}' not found in job {job_id}")
            tasks = filtered

        if not tasks:
            logger.warning("No task definitions found for source inspection")
            return SourceTransformer.build_empty_source_result()

        _BUNDLE_PROVENANCE_NOTE = (
            "bundle-deployed job (deployment.kind=BUNDLE); "
            "resolution roots include the bundle sync tree"
        )

        # Extract source code for each task
        task_sources: dict[str, Any] = {}
        for task in tasks:
            task_key_str = task.get("task_key")
            if not task_key_str:
                continue

            source_info = await self._extract_task_source(task, git_source=git_source)
            if source_info:
                # Phase 5: annotate tasks that carry a resolution dict.
                if is_bundle and isinstance(source_info, dict):
                    resolution = source_info.get("resolution")
                    if isinstance(resolution, dict):
                        caveats: list[str] = resolution.setdefault("caveats", [])
                        if _BUNDLE_PROVENANCE_NOTE not in caveats:
                            caveats.append(_BUNDLE_PROVENANCE_NOTE)
                task_sources[task_key_str] = source_info

        logger.debug(
            f"Inspected source for {len(task_sources)} out of "
            f"{len(tasks)} tasks"
        )

        return SourceTransformer.build_source_result(task_sources)

    async def _analyze_code_quality(
        self,
        source_code: str | None = None,
        task_sources: dict[str, Any] | None = None,
        task_key: str | None = None,
        mode: AnalysisMode = AnalysisMode.BATCH,
        hot_paths: Sequence[str] | None = None,
        runtime_context: str | None = None,
    ) -> dict[str, Any]:
        """Analyze source code for quality issues using LLM."""
        if not self.llm_client:
            logger.error("LLM client required for code quality analysis")
            return SourceTransformer.build_empty_analysis_result()

        # Early return if no source code
        if not source_code and not task_sources:
            logger.warning("No source code found for quality analysis")
            return SourceTransformer.build_empty_analysis_result()

        # Build message with task_key context if available
        context_msg = f"task '{task_key}'" if task_key else "code"
        self._emit_info(
            source="analyze_code_quality",
            message=f"Analyzing {context_msg} quality ({mode.value.upper()} mode)",
        )

        # Transform task sources if provided
        transformed_sources = {}
        if task_sources:
            transformed_sources = transform_task_sources(task_sources)

        # Collect all code artifacts
        code_artifacts: dict[str, dict[str, Any]] = {}

        # Add adhoc source if provided
        if source_code:
            code_artifacts["adhoc"] = {
                "task_type": "adhoc",
                "code": source_code,
            }

        # Add transformed task sources
        for key, source_info in transformed_sources.items():
            if source_info.get("code"):
                code_artifacts[key] = source_info

        # Rank and trim artifacts to analysis budget.
        ranking_inputs = [
            {
                "key": k,
                "code": v.get("code") or "",
                "reason": v.get("reason"),
                "depth": v.get("depth"),
                "path": v.get("file_path"),
            }
            for k, v in code_artifacts.items()
        ]
        kept, dropped = rank_and_trim_artifacts(
            ranking_inputs,
            max_total_bytes=_MAX_ANALYSIS_BYTES,
            hot_paths=hot_paths or (),
        )
        code_artifacts = {art["key"]: code_artifacts[art["key"]] for art in kept}

        trim_notes: list[str] = []
        if dropped:
            trim_notes.append(
                f"Trimmed {len(dropped)} source artifact(s) to fit analysis budget: {dropped}"
            )

        # Analyze based on mode
        if mode == AnalysisMode.BATCH:
            issues, notes = await self._analyze_batch(
                code_artifacts, runtime_context=runtime_context
            )
        else:
            issues, notes = await self._analyze_individual_parallel(
                code_artifacts, runtime_context=runtime_context
            )

        notes = trim_notes + notes
        logger.debug("LLM identified {len(issues)} code quality issues")

        return SourceTransformer.build_analysis_result(issues, notes)

    def _build_analysis_messages(
        self,
        code_artifacts: dict[str, dict[str, Any]],
        runtime_context: str | None = None,
    ) -> list[dict[str, str]]:
        """Build LLM messages for code quality analysis.

        Args:
            code_artifacts: Code artifacts to analyze.
            runtime_context: Optional runtime metrics string rendered into the
                ``RUNTIME CONTEXT`` block of the prompt.

        Returns:
            List of message dicts for the LLM call.
        """
        runtime_block = runtime_context if runtime_context else ""
        user_content = f"""Analyze the following code artifacts for optimization opportunities:

CODE ARTIFACTS:
{pack_dict(code_artifacts)}

RUNTIME CONTEXT (if available):
{runtime_block}

Focus on: performance, anti-patterns, Databricks best practices, correctness

Return optimizations in json format."""

        return [
            {"role": "system", "content": CODE_PASS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    async def _call_llm_for_analysis(
        self,
        code_artifacts: dict[str, dict[str, Any]],
        default_context: str = "unknown",
        runtime_context: str | None = None,
    ) -> tuple[list[CodeQualityIssue], list[str]]:
        """Call LLM to analyze code artifacts and return issues.

        Args:
            code_artifacts: Code artifacts to analyze.
            default_context: Default context label for hotspot transformation.
            runtime_context: Optional runtime metrics string for the prompt.

        Returns:
            Tuple of (issues, notes).
        """
        if self.llm_client is None:
            raise ValueError("LLM client not initialized")

        messages = self._build_analysis_messages(
            code_artifacts, runtime_context=runtime_context
        )

        response = await self.llm_client.json_response(
            phase="synth",
            messages=messages,
            budget=None,
            schema=CODE_PASS_SCHEMA,
        )

        issues = [
            SourceTransformer.transform_hotspot_to_issue(
                hotspot, context=hotspot.get("artifact", default_context)
            )
            for hotspot in response.get("hotspots", [])
        ]

        return issues, response.get("notes", [])

    async def _analyze_batch(
        self,
        code_artifacts: dict[str, dict[str, Any]],
        runtime_context: str | None = None,
    ) -> tuple[list[CodeQualityIssue], list[str]]:
        """Analyze all code snippets in a single LLM call."""
        logger.debug("Batch analyzing {len(code_artifacts)} code artifacts")

        try:
            return await self._call_llm_for_analysis(
                code_artifacts, runtime_context=runtime_context
            )
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Batch code analysis failed: {e}")
            return [], [f"Analysis failed: {str(e)}"]

    async def _analyze_individual_parallel(
        self,
        code_artifacts: dict[str, dict[str, Any]],
        runtime_context: str | None = None,
    ) -> tuple[list[CodeQualityIssue], list[str]]:
        """Analyze each code snippet individually in parallel."""
        logger.debug(
            f"Analyzing {len(code_artifacts)} code artifacts individually in parallel"
        )

        tasks = [
            self._analyze_single(context, source_info, runtime_context=runtime_context)
            for context, source_info in code_artifacts.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_issues: list[CodeQualityIssue] = []
        all_notes: list[str] = []

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                context = list(code_artifacts.keys())[i]
                logger.error("Analysis failed for {context}: {result}")
                all_notes.append(f"Failed to analyze {context}: {str(result)}")
            elif isinstance(result, tuple):
                issues, notes = result
                all_issues.extend(issues)
                all_notes.extend(notes)

        return all_issues, all_notes

    async def _analyze_single(
        self,
        context: str,
        source_info: dict[str, Any],
        runtime_context: str | None = None,
    ) -> tuple[list[CodeQualityIssue], list[str]]:
        """Analyze a single code snippet with LLM."""
        try:
            return await self._call_llm_for_analysis(
                {context: source_info},
                default_context=context,
                runtime_context=runtime_context,
            )
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Single code analysis failed for {context}: {e}")
            return [], [f"Analysis failed for {context}: {str(e)}"]
