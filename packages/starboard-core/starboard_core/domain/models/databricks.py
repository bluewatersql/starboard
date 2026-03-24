"""Databricks-related data models."""

import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class LineageDependencyType(Enum):
    JOBS = "JOBINFOS"
    NOTEBOOKS = "NOTEBOOKINFOS"
    DASHBOARDS_V3 = "DASHBOARDV3INFOS"
    DASHBOARD = "DASHBOARDINFOS"
    PIPELINES = "PIPELINEINFOS"
    QUERIES = "QUERYINFOS"
    MODELS = "MODELINFO"
    FILES = "FILEINFO"
    TABLES = "TABLEINFO"


@dataclass
class TaskNode:
    """Represents a task node in an optimization execution graph.

    Attributes:
        id: Unique identifier for the task node.
        label: Display label for the task node.
        resources: List of resource identifiers used by the task.
        desc: Description of the task's purpose and behavior.
        cacheable: Whether the task results can be cached.
        side_effect: Whether the task produces side effects beyond its return value.
    """

    id: str
    label: str
    resources: list[str] = field(default_factory=list)
    desc: str = ""
    cacheable: bool = True
    side_effect: bool = False


@dataclass
class ClusterJobReference:
    """Reference to a job run on a cluster.

    Attributes:
        job_id: Unique identifier for the job.
        run_id: Unique identifier for the specific job run.
        tasks: Mapping of task keys to task identifiers.
    """

    job_id: str
    run_id: str
    tasks: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return asdict(self)


@dataclass
class ClusterReference:
    """Reference to a Databricks cluster.

    Attributes:
        cluster_id: Unique identifier for the cluster.
        runs: Mapping of run identifiers to job references executed on this cluster.
    """

    cluster_id: str
    runs: dict[str, ClusterJobReference] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "cluster_id": self.cluster_id,
            "runs": self.runs,
        }


@dataclass
class TableReference:
    """Reference to a table in the Unity Catalog namespace.

    Attributes:
        raw: Raw table reference string as it appears in source code.
        table: Normalized table name.
        resolved_3part: Fully qualified three-part table name (catalog.schema.table).
        catalog: Catalog name in Unity Catalog.
        schema: Schema name in Unity Catalog.
        type: Table type (table, system_table, view, temp_table, temp_view, cte). Defaults to "table".
        details: Additional table metadata and properties.
        history: Table history information including delta log entries.
    """

    raw: str
    table: str
    resolved_3part: str
    catalog: str | None = None
    schema: str | None = None
    type: str = "table"
    details: dict[str, Any] | None = None
    history: dict[str, Any] | None = None
    is_source: bool = False
    is_destination: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert TableReference to dictionary for JSON serialization."""
        return asdict(self)
