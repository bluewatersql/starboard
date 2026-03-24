from __future__ import annotations

from abc import ABC
from collections.abc import Generator
from pathlib import Path
from urllib.parse import ParseResult, urlparse

from starboard_log_parser.loaders import (
    AbstractFileDataLoader,
    BlobFileReaderMixin,
    LinesFileReaderMixin,
)


class AbstractLocalFileDataLoader(AbstractFileDataLoader, ABC):
    """
    Abstract class for loading files that are on a local disk. This assumes that all we need
    is a path to the top-level file/directory from which we can extract data.
    """

    def load_item(
        self, filepath: str | ParseResult
    ) -> Generator[tuple[str, list[str]], None, None]:
        parsed_url: ParseResult = (
            filepath if isinstance(filepath, ParseResult) else urlparse(filepath)
        )
        path: Path = Path(parsed_url.path)

        yield from self.extract(path)


class LocalFileBlobDataLoader(BlobFileReaderMixin, AbstractLocalFileDataLoader):
    """
    Simple file loader that returns the full file as a blob of data.
    """


class LocalFileLinesDataLoader(LinesFileReaderMixin, AbstractLocalFileDataLoader):
    """
    Simple file loader that returns the full file as a stream of lines (delimited by `\n`).
    """
