import abc
from pathlib import Path
from urllib.parse import ParseResult, urlparse

import httpx

from starboard_log_parser.loaders import (
    AbstractFileDataLoader,
    BlobFileReaderMixin,
    FileChunkStreamWrapper,
    LinesFileReaderMixin,
)


class AbstractHTTPFileDataLoader(AbstractFileDataLoader, abc.ABC):
    """
    Abstract class that implements the `load_item` method for fetching files over HTTP/S
    """

    _STREAM_CHUNK_SIZE = 1024 * 1024  # 1MB

    def _validate_url(self, url: ParseResult | str) -> ParseResult:
        parsed_url: ParseResult = url if isinstance(url, ParseResult) else urlparse(url)
        if parsed_url.scheme not in {"http", "https"}:
            raise ValueError(
                f"URL scheme '{parsed_url.scheme}' is not one of {', '.join(self.ALLOWED_SCHEMES)}"
            )

    def load_item(self, url):
        self._validate_url(url)
        with httpx.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()

            if not int(response.headers.get("Content-Length", 0)):
                raise AssertionError("Download is empty")

            wrapped = FileChunkStreamWrapper(
                response.iter_bytes(chunk_size=self._STREAM_CHUNK_SIZE)
            )
            yield from self.extract(Path(url), wrapped)


class HTTPFileBlobDataLoader(BlobFileReaderMixin, AbstractHTTPFileDataLoader):
    """
    Simple HTTP loader that returns the full file as a blob of data.
    """


class HTTPFileLinesDataLoader(LinesFileReaderMixin, AbstractHTTPFileDataLoader):
    """
    Simple HTTP loader that returns the file as a stream of lines (delimited by `\n`).
    """
