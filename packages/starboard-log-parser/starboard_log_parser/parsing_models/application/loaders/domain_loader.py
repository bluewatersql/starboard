"""
Loader that produces immutable domain SparkApplication directly.

This loader wraps the existing parsing infrastructure but outputs
immutable domain models instead of mutable parsing models.

This is Phase 2 of the model consolidation effort - building domain
models directly without intermediate mutable models.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import polars as pl

from starboard_log_parser.domain.builders import SparkApplicationBuilder
from starboard_log_parser.domain.models.application import SparkApplication
from starboard_log_parser.loaders.json import JSONLinesDataLoader
from starboard_log_parser.parsing_models.event_log_parser import ApplicationModel
from starboard_log_parser.parsing_models.validation_configs import (
    ConfigValidationDatabricks,
    ConfigValidationEMR,
)
from starboard_log_parser.parsing_models.validation_event_data import (
    EventDataValidation,
)

if TYPE_CHECKING:
    from starboard_log_parser.parsing_models.computers.registry import ComputerRegistry

logger = logging.getLogger(__name__)


class DomainSparkApplicationLoader:
    """
    Loader that builds immutable SparkApplication domain models directly.

    Unlike UnparsedLogSparkApplicationLoader which creates mutable parsing models,
    this loader uses the SparkApplicationBuilder to construct immutable domain
    models without the intermediate mutable state.

    This provides:
    - Cleaner architecture (no mutable intermediate state)
    - Type safety (returns SparkApplication from domain.models)
    - Better testability (builder can be mocked)

    Example:
        >>> loader = DomainSparkApplicationLoader(json_lines_loader)
        >>> app = loader.load("path/to/eventlog.gz")
        >>> print(app.job_data)  # snake_case, immutable
    """

    def __init__(
        self,
        json_lines_loader: JSONLinesDataLoader,
        computer_registry: ComputerRegistry | None = None,
    ):
        """Initialize the loader.

        Args:
            json_lines_loader: Loader for JSON lines data
            computer_registry: Optional ComputerRegistry for dependency injection
        """
        self._json_lines_loader = json_lines_loader

        # Import here to avoid circular dependency
        from starboard_log_parser.parsing_models.computers.registry import (
            ComputerRegistry,
        )

        self._computers = computer_registry or ComputerRegistry.create_default()

    @staticmethod
    def validate_app_model(app_model: ApplicationModel) -> None:
        """Validate the application model using platform-specific validators.

        Args:
            app_model: The ApplicationModel to validate

        Raises:
            ValueError: If the cloud platform is unknown
        """
        if app_model.cloud_platform == "emr":
            val1 = ConfigValidationEMR(app=app_model)
        elif app_model.cloud_platform == "databricks":
            val1 = ConfigValidationDatabricks(app=app_model)
        else:
            raise ValueError(
                f"Unknown cloud_platform {app_model.cloud_platform} provided in app_model"
            )

        val1.validate()

        val2 = EventDataValidation(app=app_model)
        val2.validate()

    def load(self, path: str) -> SparkApplication | None:
        """Load and parse a Spark event log into a domain model.

        Args:
            path: Path to the event log file

        Returns:
            Immutable SparkApplication domain model, or None if not found
        """
        logger.debug(
            "domain_loader_loading",
            extra={"path": path},
        )

        t_start = time.time()

        # Load raw data
        raw_datas = self._json_lines_loader.load_many([path])
        if not raw_datas or raw_datas[0] is None:
            logger.debug(
                "domain_loader_no_data",
                extra={"path": path},
            )
            return None

        # Create ApplicationModel
        app_model = ApplicationModel(log_lines=raw_datas[0])

        # Validate
        try:
            self.validate_app_model(app_model)
        except Exception as e:
            logger.warning(
                "domain_loader_validation_failed",
                extra={"path": path, "error": str(e)},
            )
            # Continue anyway - validation failures are often non-fatal

        # Use builder pattern
        builder = SparkApplicationBuilder()

        # Compute and set SQL data
        sql_df = self._computers.sql_computer.compute(app_model)
        builder.set_sql_data(sql_df)

        # Compute and set executor data
        executor_df = self._computers.executor_computer.compute(app_model)
        builder.set_executor_data(executor_df)

        # Compute and set job data
        job_df = self._computers.job_computer.compute(app_model, sql_data=sql_df)
        builder.set_job_data(job_df if job_df is not None else pl.DataFrame())

        # Compute and set task data
        task_df = self._computers.task_computer.compute(app_model)
        builder.set_task_data(task_df if task_df is not None else pl.DataFrame())

        # Compute and set stage data
        # Stage computer needs task_df and (optionally) SQL mappings.
        # It derives job_id from app_model.jobs; it does NOT accept job_data.
        stage_df = self._computers.stage_computer.compute(
            app_model,
            task_data=task_df if task_df is not None else pl.DataFrame(),
            sql_data=sql_df if sql_df is not None else pl.DataFrame(),
        )
        builder.set_stage_data(stage_df if stage_df is not None else pl.DataFrame())

        # Compute and set accum data
        accum_df = self._computers.accum_computer.compute(app_model, sql_data=sql_df)
        builder.set_accum_data(accum_df if accum_df is not None else pl.DataFrame())

        # Compute and set metadata
        metadata = self._computers.metadata_computer.compute(app_model)
        if metadata is not None:
            app_info = metadata.get("application_info", {})
            builder.set_application_info_from_dict(app_info)
            builder.set_spark_params(metadata.get("spark_params", {}))
        else:
            # Set default application info
            builder.set_application_info(
                name=getattr(app_model, "app_name", ""),
                id=getattr(app_model, "app_id", ""),
                spark_version=getattr(app_model, "spark_version", ""),
                cloud_platform=getattr(app_model, "cloud_platform", ""),
                cloud_provider=getattr(app_model, "cloud_provider", ""),
            )
            builder.set_spark_params({})

        # Build immutable domain model
        app = builder.build()

        t_end = time.time()
        logger.debug(
            "domain_loader_loaded",
            extra={
                "path": path,
                "duration_sec": t_end - t_start,
                "num_jobs": len(app.job_data),
                "num_stages": len(app.stage_data),
                "num_tasks": len(app.task_data),
            },
        )

        return app


__all__ = ["DomainSparkApplicationLoader"]
