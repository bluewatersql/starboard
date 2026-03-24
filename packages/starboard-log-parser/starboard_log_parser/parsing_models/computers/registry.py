"""Computer registry for dependency injection."""

from dataclasses import dataclass

from starboard_log_parser.parsing_models.computers.accum_computer import (
    AccumDataComputer,
)
from starboard_log_parser.parsing_models.computers.executor_computer import (
    ExecutorDataComputer,
)
from starboard_log_parser.parsing_models.computers.job_computer import (
    JobDataComputer,
)
from starboard_log_parser.parsing_models.computers.metadata_computer import (
    MetadataComputer,
)
from starboard_log_parser.parsing_models.computers.sql_computer import (
    SQLDataComputer,
)
from starboard_log_parser.parsing_models.computers.stage_computer import (
    StageDataComputer,
)
from starboard_log_parser.parsing_models.computers.task_computer import (
    TaskDataComputer,
)


@dataclass(frozen=True)
class ComputerRegistry:
    """Registry of all data computers with dependency injection.

    This registry provides a central location for managing all data computers,
    enabling dependency injection and making testing easier.

    All computers are immutable (frozen dataclass) to prevent accidental mutation.

    Example:
        >>> registry = ComputerRegistry.create_default()
        >>> sql_df = registry.sql_computer.compute(app_model)

        >>> # For testing with mocks:
        >>> mock_sql = MockSQLComputer()
        >>> test_registry = ComputerRegistry(
        ...     sql_computer=mock_sql,
        ...     executor_computer=registry.executor_computer,
        ...     # ...
        ... )
    """

    sql_computer: SQLDataComputer
    executor_computer: ExecutorDataComputer
    job_computer: JobDataComputer
    stage_computer: StageDataComputer
    task_computer: TaskDataComputer
    accum_computer: AccumDataComputer
    metadata_computer: MetadataComputer

    @classmethod
    def create_default(cls) -> "ComputerRegistry":
        """Create registry with default implementations.

        Returns:
            ComputerRegistry with all standard computers.
        """
        return cls(
            sql_computer=SQLDataComputer(),
            executor_computer=ExecutorDataComputer(),
            job_computer=JobDataComputer(),
            stage_computer=StageDataComputer(),
            task_computer=TaskDataComputer(),
            accum_computer=AccumDataComputer(),
            metadata_computer=MetadataComputer(),
        )
