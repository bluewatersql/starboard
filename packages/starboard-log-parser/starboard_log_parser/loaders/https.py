import abc
from pathlib import Path
from urllib.parse import ParseResult, urlparse

import httpx

from starboard_log_parser.loaders import (
    AbstractFileDataLoader,
    ArchiveExtractionThresholds,
    BlobFileReaderMixin,
    FileChunkStreamWrapper,
    LinesFileReaderMixin,
)

# Default timeout for HTTP streaming requests.
# connect: time to establish a TCP connection.
# read:    time between individual data chunks during streaming (5 min for large logs).
# write:   time to send the request body (GET has no body, but keep a bound).
# pool:    time waiting for an idle connection from the pool.
DEFAULT_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)


class AbstractHTTPFileDataLoader(AbstractFileDataLoader, abc.ABC):
    """
    Abstract class that implements the `load_item` method for fetching files over HTTP/S.

    A configurable :class:`httpx.Timeout` is applied to every streaming request so that
    stalled or very slow remote servers do not block the calling thread indefinitely.
    Pass *http_timeout* in the constructor to override the default
    (``connect=10 s``, ``read=300 s``).
    """

    _STREAM_CHUNK_SIZE = 1024 * 1024  # 1MB

    def __init__(
        self,
        extraction_thresholds: ArchiveExtractionThresholds = None,
        http_timeout: httpx.Timeout = DEFAULT_HTTP_TIMEOUT,
    ) -> None:
        """Initialize the loader.

        Args:
            extraction_thresholds: Archive extraction limits passed to the base class.
            http_timeout: Timeout configuration for HTTP streaming requests.
                Defaults to ``DEFAULT_HTTP_TIMEOUT`` (connect=10 s, read=300 s).
        """
        super().__init__(extraction_thresholds=extraction_thresholds)
        self._http_timeout = http_timeout

    def _validate_url(self, url: ParseResult | str) -> ParseResult:
        parsed_url: ParseResult = url if isinstance(url, ParseResult) else urlparse(url)
        if parsed_url.scheme not in {"http", "https"}:
            raise ValueError(
                f"URL scheme '{parsed_url.scheme}' is not one of {', '.join(self.ALLOWED_SCHEMES)}"
            )

    def load_item(self, url):
        self._validate_url(url)
        with httpx.stream("GET", url, follow_redirects=True, timeout=self._http_timeout) as response:
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
