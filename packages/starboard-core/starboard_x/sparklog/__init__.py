# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x.sparklog`` — dep-light Spark event-log parsing CLI.

Wraps the kernel's log-parser factory
(``starboard_core.log_parser.create_spark_application``), which already routes a
path to the right loader (DBFS / UC Volumes / S3 / HTTP) and lazily imports the
cloud SDK only when a remote path is actually loaded. ``python -m
starboard_x.sparklog parse`` reuses that seam untouched: HTTP parsing runs on the
base install; ``s3`` / ``dbfs`` sources are gated behind their extras with an
actionable install error. A customer file is passed as ``parse --input
drive:<id>|FILE`` and parsed in memory
(``starboard_core.log_parser.create_spark_application_from_content``).

Ships behind the ``[sparklog]`` extra; cloud loaders behind
``[sparklog-aws|azure|gcp]`` (and ``[databricks]`` for ``dbfs``).
"""

__all__: list[str] = []
