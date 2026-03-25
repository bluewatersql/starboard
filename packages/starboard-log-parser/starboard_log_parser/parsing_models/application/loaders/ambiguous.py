"""
Loaders for event logs with ambiguous format (parsed vs unparsed).

These loaders detect whether a file contains pre-parsed JSON or raw event logs
and delegate to the appropriate loader automatically.
"""

from __future__ import annotations

import abc
import logging
from collections.abc import Callable

from starboard_log_parser.exceptions import SparkLogPathNotFoundError
from starboard_log_parser.loaders.json import JSONLinesDataLoader
from starboard_log_parser.parsing_models.application.loaders.base import (
    AbstractSparkApplicationDataLoader,
    SparkApplicationClass,
    SparkApplicationLoaderKey,
)
from starboard_log_parser.parsing_models.application.loaders.parsed import (
    ParsedLogSparkApplicationLoader,
)
from starboard_log_parser.parsing_models.application.loaders.unparsed import (
    UnparsedLogSparkApplicationLoader,
)
from starboard_log_parser.parsing_models.application.model import (
    SparkApplication,
)
from starboard_log_parser.parsing_models.application.types import (
    SparkApplicationMetadata,
)
from starboard_log_parser.parsing_models.event_log_parser import (
    ApplicationModel,
)

logger = logging.getLogger(__name__)


class BaseAmbiguousLogFormatSparkApplicationLoader(
    AbstractSparkApplicationDataLoader[
        SparkApplicationLoaderKey,
        tuple[bool, dict | ApplicationModel],
        SparkApplicationClass,
    ],
    abc.ABC,
):
    """
    Base class for loaders that handle both parsed and unparsed event logs.

    This loader automatically detects the format by looking at the first line:
    - If it's a complete dict with "jobData" → parsed format
    - Otherwise → unparsed event log format

    The raw_data type is a tuple: (is_parsed: bool, data: dict | ApplicationModel)
    """

    def __init__(
        self,
        json_lines_loader: JSONLinesDataLoader,
        spark_application_constructor: (
            Callable[[], SparkApplicationClass] | None
        ) = None,
    ):
        """
        Initialize the loader.

        Args:
            json_lines_loader: Loader for JSON lines data
            spark_application_constructor: Optional custom SparkApplication factory
        """
        super().__init__(spark_application_constructor=spark_application_constructor)

        self._json_lines_loader: JSONLinesDataLoader = json_lines_loader
        # These "sub-loaders" won't actually be loading the raw data, so we don't need to pass them any dataloaders
        #  We just want to use them to construct our SparkApplications based on whether the data handed to us is a
        #  parsed or unparsed eventlog
        self._parsed_app_loader: ParsedLogSparkApplicationLoader = (
            ParsedLogSparkApplicationLoader(
                None, spark_application_constructor=spark_application_constructor
            )
        )
        self._unparsed_app_loader: UnparsedLogSparkApplicationLoader = (
            UnparsedLogSparkApplicationLoader(
                None, spark_application_constructor=spark_application_constructor
            )
        )

    def _construct_from_parsed_representation(
        self, key: SparkApplicationLoaderKey, data: dict
    ) -> SparkApplicationClass:
        """
        Construct SparkApplication from already-parsed JSON.

        Args:
            key: The key used to load this data
            data: Dictionary with parsed application data

        Returns:
            Constructed SparkApplication
        """
        return self._parsed_app_loader.construct_spark_application(key, data)

    def _construct_from_unparsed_representation(
        self, key: SparkApplicationLoaderKey, data: ApplicationModel
    ) -> SparkApplicationClass:
        """
        Construct SparkApplication from raw event log.

        Args:
            key: The key used to load this data
            data: ApplicationModel with raw event log lines

        Returns:
            Constructed SparkApplication
        """
        return self._unparsed_app_loader.construct_spark_application(key, data)

    def _load_raw_datas(
        self, keys: list[SparkApplicationLoaderKey]
    ) -> list[tuple[bool, dict | ApplicationModel | Exception]]:
        """
        Given some eventlog locations, determines the data format of the file (i.e. raw vs already-parsed) and returns
        the appropriate in-memory representation of that file.

        Args:
            keys: List of file paths or URLs to load

        Returns:
            List of tuples: (is_parsed, data_or_exception)
        """
        raw_datas = self._json_lines_loader.load_many(keys)

        ret = []
        for key, raw_data in zip(keys, raw_datas):
            try:
                line = next(raw_data)
            except StopIteration:
                # Empty log file - treat as not found
                logger.debug(f"Empty log file at: {key}")
                ret.append((False, SparkLogPathNotFoundError(log_path=str(key))))
                continue

            # This assumes that for parsed apps, the first "line" from the file will be the fully-formed dictionary
            #  representation of a SparkApplication. This may not be true over time... we should strive to keep this
            #  check "cheap", however
            if SparkApplication.is_parsed_spark_app(line):
                ret.append((True, line))
            else:
                # ApplicationModel expects to receive all the lines, so just wrap the line we already read in a
                #  generator so that we can re-yield it appropriately
                # Bind loop variables as default args to avoid closure issues
                def lines(line=line, raw_data=raw_data):
                    yield line
                    yield from raw_data

                try:
                    app_model = ApplicationModel(log_lines=lines())
                    ret.append((False, app_model))
                except Exception as e:
                    logger.error(
                        f"Encountered an exception loading eventlog located at: {key}",
                        exc_info=e,
                    )
                    ret.append((False, e))

        return ret

    def _construct_base_spark_application(
        self,
        key: SparkApplicationLoaderKey | None,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],
    ) -> SparkApplicationClass | Exception:
        """
        Given an initial piece of raw_data, calls into the appropriate "sub-loader" based on the detected file format,
        i.e. whether the eventlog was delivered to us already-parsed.

        Args:
            key: The key used to load this data
            raw_data: Tuple of (is_parsed, data_or_exception)

        Returns:
            Constructed SparkApplication or Exception if loading failed
        """
        is_parsed, data = raw_data

        # If we weren't able to create a SparkApplication out of one of the "keys" provided to us, we want to bubble
        #  that exception upwards so that BaseDataLoader will raise it to the caller when the load() is called
        if isinstance(data, Exception):
            spark_app = data
        elif is_parsed:
            spark_app = self._construct_from_parsed_representation(key, data)
        else:
            spark_app = self._construct_from_unparsed_representation(key, data)

        return spark_app

    # None of these abstract methods actually need to do anything because we will be calling into the proper
    #  un/parsed SparkApplication loader based on the underlying data, and those loaders have these methods
    #  implemented already. If some class subclasses this one, then these methods will just echo back the
    #  spark_app that we already constructed
    def init_spark_application(
        self, raw_data: tuple[bool, dict | ApplicationModel | Exception]
    ) -> SparkApplicationClass:
        """See comment above for why this is implemented thusly."""
        pass

    def compute_sql_info(
        self,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],  # noqa: ARG002
        spark_app: SparkApplicationClass,
    ) -> SparkApplicationClass:
        """See comment above for why this is implemented thusly."""
        return spark_app

    def compute_executor_info(
        self,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],  # noqa: ARG002
        spark_app: SparkApplicationClass,
    ) -> SparkApplicationClass:
        """See comment above for why this is implemented thusly."""
        return spark_app

    def compute_all_job_data(
        self,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],  # noqa: ARG002
        spark_app: SparkApplicationClass,
    ) -> SparkApplicationClass:
        """See comment above for why this is implemented thusly."""
        return spark_app

    def compute_all_task_data(
        self,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],  # noqa: ARG002
        spark_app: SparkApplicationClass,
    ) -> SparkApplicationClass:
        """See comment above for why this is implemented thusly."""
        return spark_app

    def compute_all_stage_data(
        self,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],  # noqa: ARG002
        spark_app: SparkApplicationClass,
    ) -> SparkApplicationClass:
        """See comment above for why this is implemented thusly."""
        return spark_app

    def compute_all_driver_accum_data(
        self,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],  # noqa: ARG002
        spark_app: SparkApplicationClass,
    ) -> SparkApplicationClass:
        """See comment above for why this is implemented thusly."""
        return spark_app

    def compute_all_metadata(
        self,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],  # noqa: ARG002
        spark_app: SparkApplicationClass,  # noqa: ARG002
    ) -> SparkApplicationMetadata | None:
        """See comment above for why this is implemented thusly."""
        return None

    def compute_recent_events(
        self,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],  # noqa: ARG002
        spark_app: SparkApplicationClass,
    ) -> SparkApplicationClass:
        """See comment above for why this is implemented thusly."""
        return spark_app


class AmbiguousLogFormatSparkApplicationLoader(
    BaseAmbiguousLogFormatSparkApplicationLoader[
        SparkApplicationLoaderKey, SparkApplicationClass
    ]
):
    """
    Much of the time, we may not know whether a file given to us is for a parsed or unparsed eventlog without opening it
    up first. But, we don't want to have to open up a file and just throw it away if it's not what we initially
    expected. This class, then, may be used when this information is ambiguous to us, and it will handle calling into
    the proper "sub-loader" transparently (and without having to re-load anything).

    This is the main entry point for loading Spark applications when you don't know the format.

    Example:
        >>> loader = AmbiguousLogFormatSparkApplicationLoader(json_lines_loader)
        >>> spark_app = loader.load("path/to/eventlog")  # Automatically detects format
        >>> print(spark_app.jobData)
    """

    def load_raw_datas(
        self, keys: list[SparkApplicationLoaderKey]
    ) -> list[tuple[bool, dict | ApplicationModel | Exception]]:
        """
        Load and detect format for multiple event logs.

        Args:
            keys: List of file paths or URLs to load

        Returns:
            List of tuples: (is_parsed, data_or_exception)
        """
        return self._load_raw_datas(keys)

    def construct_spark_application(
        self,
        key: SparkApplicationLoaderKey,
        raw_data: tuple[bool, dict | ApplicationModel | Exception],
    ) -> SparkApplication:
        """
        Construct a SparkApplication from auto-detected format data.

        Args:
            key: The key used to load this data
            raw_data: Tuple of (is_parsed, data_or_exception)

        Returns:
            Constructed SparkApplication
        """
        return self._construct_base_spark_application(key, raw_data)
