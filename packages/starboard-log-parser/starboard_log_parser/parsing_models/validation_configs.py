# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
import abc
import logging
from typing import Any

from starboard_log_parser.parsing_models.exceptions import (
    ConfigurationException,
)

logger = logging.getLogger(__name__)


class ConfigValidation:
    """
    This is a generic class to handle Spark Configuration Validation. Actions
    that are common to all platform/provider logs will be located here.

    The config validation is lazy in that it will gather all of the invalid configurations and then
    throw a single exception identifying all of the problematic configs.
    """

    def __init__(self, app: Any = None, debug: bool = False) -> None:
        self.app = app
        self.debug = debug  # When 'True' disables exception raises for debugging

        self.config_recs = []  # List to contain required config changes

    @abc.abstractmethod
    def validate(self) -> None:
        pass

    def raise_config_exceptions(self) -> None:
        """
        Raise exceptions if necessary. Configuration checks will also get executred in this method
        int the future.

        Raises:
            ConfigurationException: If invalid configurations exist and debugging is off an
            exception will get thrown.
        """

        if len(self.config_recs) > 0 and (self.debug is False):
            raise ConfigurationException(config_recs=self.config_recs)


class ConfigValidationDatabricks(ConfigValidation):
    """
    Valids the Spark Configurations for Databricks Logs
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def validate(self) -> None:
        super().raise_config_exceptions()


class ConfigValidationEMR(ConfigValidation):
    """
    Valids the Spark Configurations for EMR Logs
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def validate(self) -> None:
        self.config_check_hetero_exec()
        # self.config_check_dynamic_alloc()

        super().raise_config_exceptions()

    def config_check_hetero_exec(self) -> None:
        """
        Checks for heterogeneous executors in the input log

        The heterogeneousExecutors flag is not always in the Spark configs. We detect that this
        config is active by looking for heterogeneity in the executor cores.
        """

        exec_cores = []
        for _, e in self.app.executors.items():
            exec_cores.append(e.cores)

        if not all(e == exec_cores[0] for e in exec_cores):
            logger.debug("Detected heterogeneous executors in input log")
            self.config_recs.append("spark.yarn.heterogeneousExecutors.enabled=false")

    def config_check_dynamic_alloc(self) -> None:
        """
        Check if dynamic allocation is enabled
        """

        key_check = ("spark.dynamicAllocation.enabled", "false")

        configs = self.app.spark_metadata

        if (key_check[0] in configs) and configs[key_check[0]] != key_check[1]:
            logger.debug("Detected dynamic allocation enabled")
            self.config_recs.append(f"{key_check[0]}={key_check[1]}")
