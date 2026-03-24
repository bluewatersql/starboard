"""Base protocol for data computers.

Data computers extract and compute specific aspects of Spark application data,
such as SQL executions, executor metrics, job information, etc.
"""

from typing import Protocol

import polars as pl

from starboard_log_parser.parsing_models.event_log_parser import (
    ApplicationModel,
)


class DataComputer(Protocol):
    """Protocol for data computers that extract information from ApplicationModel.

    Data computers follow the Single Responsibility Principle: each computer
    is responsible for computing one specific aspect of the Spark application
    (e.g., SQL data, executor data, job data).

    Example:
        >>> computer = SQLDataComputer()
        >>> app_model = ApplicationModel(...)
        >>> sql_df = computer.compute(app_model)
    """

    def compute(self, app_model: ApplicationModel) -> pl.DataFrame | None:
        """Compute DataFrame from ApplicationModel.

        Args:
            app_model: Parsed application model containing event log data.

        Returns:
            DataFrame with computed data, or None if no data available.

        Raises:
            ValueError: If app_model is invalid or missing required data.
        """
        ...
