# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
import logging
from collections.abc import Iterator
from typing import TypeVar

import orjson

from starboard_log_parser.loaders import (
    BaseDataLoader,
    FileExtractionResult,
)
from starboard_log_parser.loaders.https import (
    HTTPFileBlobDataLoader,
    HTTPFileLinesDataLoader,
)
from starboard_log_parser.loaders.local_file import (
    LocalFileBlobDataLoader,
    LocalFileLinesDataLoader,
)

RawJSONBlobDataLoader = TypeVar(
    "BlobDataLoader",
    LocalFileBlobDataLoader,
    HTTPFileBlobDataLoader,
)

logger = logging.getLogger(__name__)


class JSONBlobDataLoader(BaseDataLoader):
    def __init__(self, blob_data_loader: RawJSONBlobDataLoader):
        super().__init__()
        self.blob_data_loader: RawJSONBlobDataLoader = blob_data_loader

    @staticmethod
    def _parse_as_json(data: FileExtractionResult):
        _, blob = data
        return orjson.loads(next(blob))

    def batch_load_fn(self, keys):
        raw_datas = self.blob_data_loader.load_many(keys)
        # We expect each "blob" here to be well-formed JSON, so parse each of them thusly
        return [self._parse_as_json(next(raw_data)) for raw_data in raw_datas]


RawJSONLinesDataLoader = TypeVar(
    "LinesDataLoader",
    LocalFileLinesDataLoader,
    HTTPFileLinesDataLoader,
)


class JSONLinesDataLoader(BaseDataLoader):
    def __init__(self, lines_data_loader: RawJSONLinesDataLoader):
        super().__init__()
        self.lines_data_loader: RawJSONLinesDataLoader = lines_data_loader

    @staticmethod
    def _yield_json_lines(data: Iterator[FileExtractionResult]) -> Iterator[dict]:
        for filepath, file_stream in data:
            logger.debug(f"Processing: {filepath}")

            lines = iter(file_stream)
            first_line = next(lines)
            try:
                json_line = orjson.loads(first_line)
                yield json_line

                # If we were able to successfully parse the first line as a JSON object, then we should be able
                #  to assume the rest of the lines in the file are well-formed JSON objects
                for line in lines:
                    yield orjson.loads(line)
            except orjson.JSONDecodeError:
                # If the first line is not parseable as a JSON object, try to parse the whole file as a JSON Object
                #  as well, and yield that as a line instead.
                # We do this for a few reasons -
                #  - Sometimes regular JSON files are delivered in archives along with eventlog files (which are JSON
                #     Lines). These JSON files may contain valuable information that we don't want to drop on the floor
                #     (for example, we may receive Databricks pricing information, which we may be able to use!)
                #  - We may not be able to tell without opening the file whether the eventlog provided to us is a "raw"
                #     eventlog (i.e. delivered to us in exactly the way Spark output them), or if it is an
                #     already-parsed log.
                #
                # This means that, in a sense, we treat regular JSON files as a special case of JSON Lines files
                for line in lines:
                    first_line += line

                try:
                    yield orjson.loads(first_line)
                except (orjson.JSONDecodeError, ValueError) as e:
                    # If standard parsing fails, try with a more lenient approach
                    # Replace common invalid JSON values that may exist in legacy parsed logs
                    try:
                        import re

                        # Replace NaN, Infinity, -Infinity with null (more compatible)
                        cleaned_line = re.sub(
                            r"\bNaN\b",
                            "null",
                            (
                                first_line.decode()
                                if isinstance(first_line, bytes)
                                else first_line
                            ),
                        )
                        cleaned_line = re.sub(r"\bInfinity\b", "null", cleaned_line)
                        cleaned_line = re.sub(r"\b-Infinity\b", "null", cleaned_line)
                        yield orjson.loads(
                            cleaned_line.encode()
                            if isinstance(first_line, bytes)
                            else cleaned_line
                        )
                        logger.warning(
                            f"Parsed file {filepath} with NaN/Infinity cleanup"
                        )
                    except Exception as cleanup_err:
                        logger.warning(
                            f"Could not parse file {filepath} as JSON - skipping. "
                            f"Original: {e}, Cleanup attempt: {cleanup_err}"
                        )

    def batch_load_fn(self, keys):
        raw_datas = self.lines_data_loader.load_many(keys)
        return [self._yield_json_lines(data) for data in raw_datas]
