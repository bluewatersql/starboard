# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Abstract base class for Spark application data loaders.

Defines the interface that concrete loaders must implement to construct
SparkApplication instances from various data sources.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from typing import TypeVar

from starboard_core.log_parser.loaders import BaseDataLoader
from starboard_core.log_parser.parsing_models.application.model import (
    SparkApplication,
)
from starboard_core.log_parser.parsing_models.application.types import (
    SparkApplicationMetadata,
)

# Exported type variables for use in subclass type hints.
# These are separate from the PEP 695 inline type parameters on the class itself.
SparkApplicationLoaderKey = TypeVar("SparkApplicationLoaderKey")
SparkApplicationRawDataType = TypeVar("SparkApplicationRawDataType")
SparkApplicationClass = TypeVar("SparkApplicationClass", bound=SparkApplication)


class AbstractSparkApplicationDataLoader[
    SparkApplicationLoaderKey,
    SparkApplicationRawDataType,
    SparkApplicationClass: SparkApplication,
](
    BaseDataLoader,
    abc.ABC,
):
    """
    Defines the methods that other data loaders should implement in order to appropriately construct
    some SparkApplication. The order in which these methods are called is defined in construct_spark_application.

    This is a generic abstract base class that can work with different:
    - Key types (e.g., file paths, URLs)
    - Raw data types (e.g., dict, ApplicationModel, generators)
    - SparkApplication subclasses

    Example:
        >>> class MyLoader(AbstractSparkApplicationDataLoader[str, dict, SparkApplication]):
        ...     def load_raw_datas(self, keys: list[str]) -> list[dict]:
        ...         return [load_json(key) for key in keys]
        ...     # ... implement other abstract methods ...
    """

    def __init__(
        self,
        spark_application_constructor: (
            Callable[[], SparkApplicationClass] | None
        ) = None,
    ):
        """
        Initialize the loader.

        Args:
            spark_application_constructor: Optional factory function to create
                SparkApplication instances. Defaults to SparkApplication().
        """
        super().__init__()

        self._spark_application_constructor = (
            spark_application_constructor
            if spark_application_constructor is not None
            else lambda: SparkApplication()
        )

    @abc.abstractmethod
    def load_raw_datas(
        self, keys: list[SparkApplicationLoaderKey]
    ) -> list[SparkApplicationRawDataType | Exception]:
        """
        Implementors of this method should return the data that will be the "source-of-truth", i.e. that data from
        which this concrete class will be constructing the SparkApplication. If the underlying data is not able to
        be loaded for some reason, implementors should return an Exception for DataLoader to raise to the caller.

        Args:
            keys: List of identifiers for the data to load (e.g., file paths)

        Returns:
            List of raw data or Exceptions for failed loads
        """

    @abc.abstractmethod
    def init_spark_application(
        self, raw_data: SparkApplicationRawDataType
    ) -> SparkApplicationClass:
        """
        Allows subclasses to provide their own instance of SparkApplication (or some sub-class).

        Args:
            raw_data: The raw data to initialize from

        Returns:
            A new SparkApplication instance
        """
        return self._spark_application_constructor()

    @abc.abstractmethod
    def compute_sql_info(
        self, raw_data: SparkApplicationRawDataType, spark_app: SparkApplicationClass
    ) -> SparkApplicationClass:
        """
        This method is responsible for setting the following fields on spark_app:

            - existsSQL
            - sqlData

        Args:
            raw_data: The raw data to extract SQL info from
            spark_app: The SparkApplication to populate

        Returns:
            The populated SparkApplication
        """

    @abc.abstractmethod
    def compute_executor_info(
        self, raw_data: SparkApplicationRawDataType, spark_app: SparkApplicationClass
    ) -> SparkApplicationClass:
        """
        This method is responsible for setting the following fields on spark_app:

            - existsExecutors
            - executorData

        Args:
            raw_data: The raw data to extract executor info from
            spark_app: The SparkApplication to populate

        Returns:
            The populated SparkApplication
        """

    @abc.abstractmethod
    def compute_all_job_data(
        self, raw_data: SparkApplicationRawDataType, spark_app: SparkApplicationClass
    ) -> SparkApplicationClass:
        """
        This method is responsible for setting the following fields on spark_app:

            - jobData

        Args:
            raw_data: The raw data to extract job data from
            spark_app: The SparkApplication to populate

        Returns:
            The populated SparkApplication
        """

    @abc.abstractmethod
    def compute_all_stage_data(
        self, raw_data: SparkApplicationRawDataType, spark_app: SparkApplicationClass
    ) -> SparkApplicationClass:
        """
        This method is responsible for setting the following fields on spark_app:

            - stageData

        Args:
            raw_data: The raw data to extract stage data from
            spark_app: The SparkApplication to populate

        Returns:
            The populated SparkApplication
        """

    @abc.abstractmethod
    def compute_all_task_data(
        self, raw_data: SparkApplicationRawDataType, spark_app: SparkApplicationClass
    ) -> SparkApplicationClass:
        """
        This method is responsible for setting the following fields on spark_app:

            - taskData

        Args:
            raw_data: The raw data to extract task data from
            spark_app: The SparkApplication to populate

        Returns:
            The populated SparkApplication
        """

    @abc.abstractmethod
    def compute_all_driver_accum_data(
        self, raw_data: SparkApplicationRawDataType, spark_app: SparkApplicationClass
    ) -> SparkApplicationClass:
        """
        This method is responsible for setting the following fields on spark_app:

            - accumData

        Args:
            raw_data: The raw data to extract accumulator data from
            spark_app: The SparkApplication to populate

        Returns:
            The populated SparkApplication
        """

    @abc.abstractmethod
    def compute_all_metadata(
        self, raw_data: SparkApplicationRawDataType, spark_app: SparkApplicationClass
    ) -> SparkApplicationMetadata | None:
        """
        This method is responsible for setting the following fields on spark_app:

            - metadata

        Args:
            raw_data: The raw data to extract metadata from
            spark_app: The SparkApplication to populate

        Returns:
            Application metadata or None
        """

    @abc.abstractmethod
    def compute_recent_events(
        self, raw_data: SparkApplicationRawDataType, spark_app: SparkApplicationClass
    ) -> SparkApplicationClass:
        """
        This method is responsible for updating the "time_since_last_event" value on both:

            - spark_app.stageData
            - spark_app.sqlData

        This value should be a list of timestamps where each timestamp is the most recent Task or SQL event
        to complete before this stage/SQL event started executing.

        Args:
            raw_data: The raw data to compute recent events from
            spark_app: The SparkApplication to populate

        Returns:
            The populated SparkApplication
        """

    def construct_spark_application(
        self,
        key: SparkApplicationLoaderKey,  # noqa: ARG002
        raw_data: SparkApplicationRawDataType,
    ) -> SparkApplicationClass:
        """
        Generic 'recipe' for constructing a SparkApplication from some raw source of data.

        This method orchestrates the entire construction process by calling each
        compute method in the proper order.

        Args:
            key: The key that was used to load this data
            raw_data: The loaded raw data

        Returns:
            A fully constructed SparkApplication
        """
        spark_app = self.init_spark_application(raw_data)
        spark_app = self.compute_sql_info(raw_data, spark_app)
        spark_app = self.compute_executor_info(raw_data, spark_app)
        spark_app = self.compute_all_job_data(raw_data, spark_app)
        spark_app = self.compute_all_task_data(raw_data, spark_app)
        spark_app = self.compute_all_stage_data(raw_data, spark_app)
        spark_app = self.compute_all_driver_accum_data(raw_data, spark_app)

        metadata = self.compute_all_metadata(raw_data, spark_app)
        if metadata is not None:
            spark_app.metadata = metadata

        spark_app = self.compute_recent_events(raw_data, spark_app)
        return spark_app

    def batch_load_fn(self, keys: list[SparkApplicationLoaderKey]):
        """
        Batch load function required by BaseDataLoader.

        Loads raw data for all keys and constructs SparkApplication instances.

        Args:
            keys: List of keys to load

        Returns:
            List of SparkApplications or Exceptions for failed loads
        """
        raw_datas = self.load_raw_datas(keys)
        # Make sure we bubble up any Exceptions from load_raw_datas appropriately
        return [
            (
                self.construct_spark_application(key, data)
                if not isinstance(data, Exception)
                else data
            )
            for (key, data) in zip(keys, raw_datas)
        ]
