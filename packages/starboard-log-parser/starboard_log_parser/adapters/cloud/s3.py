"""
AWS S3 storage adapter.

Provides CloudStorageClient implementation for AWS S3 access with support
for multiple authentication methods via CredentialProvider abstraction.

Examples:
    >>> # With static credentials
    >>> from starboard_log_parser.auth.providers import StaticCredentialProvider
    >>> from starboard_log_parser.adapters.cloud.s3 import S3Adapter
    >>>
    >>> provider = StaticCredentialProvider(
    ...     access_key="MY_AWS_ACCESS_KEY_ID",
    ...     secret_key="MY_AWS_SECRET_ACCESS_KEY",
    ...     region="us-west-2",
    ... )
    >>> adapter = S3Adapter(credential_provider=provider)
    >>>
    >>> # Check if file exists
    >>> exists = adapter.path_exists("s3://my-bucket/logs/eventlog.gz")
    >>>
    >>> # List files
    >>> files = adapter.list_files("s3://my-bucket/logs/", pattern="*.json")
    >>>
    >>> # Read chunk (streaming)
    >>> chunk = adapter.read_chunk("s3://my-bucket/logs/app.json", offset=0, length=1024*1024)
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from starboard_log_parser.auth.protocols import CredentialProvider
from starboard_log_parser.exceptions import CloudStorageError
from starboard_log_parser.loaders.protocols import CloudStorageClient

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None  # type: ignore
    # Provide a never-matching sentinel so `except ClientError` clauses remain
    # syntactically valid when botocore is not installed.  S3Adapter.__post_init__
    # raises ImportError before any method is called, so this branch is unreachable
    # at runtime when boto3 is absent.
    class ClientError(Exception):  # type: ignore[no-redef]
        """Stub for botocore.exceptions.ClientError when boto3 is not installed."""

        def __init__(self, *args: object) -> None:
            self.response: dict = {}
            super().__init__(*args)


@dataclass
class S3Adapter(CloudStorageClient):
    """Adapter for AWS S3 storage access.

    Supports multiple authentication methods via CredentialProvider:
    - Static credentials (development/testing)
    - Environment variables (12-factor apps)
    - EC2 instance profiles (production)
    - AssumeRole (cross-account access)
    - Databricks credential vending (future)

    Attributes:
        credential_provider: Provider for AWS credentials

    Examples:
        >>> # With static credentials
        >>> from starboard_log_parser.auth.providers import StaticCredentialProvider
        >>>
        >>> provider = StaticCredentialProvider(
        ...     access_key="MY_AWS_ACCESS_KEY_ID",
        ...     secret_key="MY_AWS_SECRET_ACCESS_KEY",
        ...     region="us-west-2",
        ... )
        >>> adapter = S3Adapter(credential_provider=provider)
        >>> exists = adapter.path_exists("s3://my-bucket/logs/eventlog.gz")
        >>>
        >>> # With environment credentials
        >>> import os
        >>> os.environ["AWS_ACCESS_KEY_ID"] = "MY_AWS_ACCESS_KEY_ID"
        >>> os.environ["AWS_SECRET_ACCESS_KEY"] = "MY_AWS_SECRET_ACCESS_KEY"
        >>> os.environ["AWS_REGION"] = "us-west-2"
        >>>
        >>> from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
        >>> provider = EnvironmentCredentialProvider(cloud="aws")
        >>> adapter = S3Adapter(credential_provider=provider)
    """

    credential_provider: CredentialProvider
    _s3_client: Any = None

    def __post_init__(self) -> None:
        """Verify boto3 is available."""
        if boto3 is None:
            raise ImportError(
                "boto3 is required for S3 access. "
                "Install with: pip install starboard-log-parser[aws] or pip install boto3"
            )

    @property
    def s3_client(self) -> Any:
        """Get or create boto3 S3 client with current credentials.

        Returns:
            Configured boto3 S3 client

        Notes:
            - Creates new client if credentials are refreshed
            - Handles credential expiration automatically
            - Reuses client when credentials are still valid
        """
        creds = self.credential_provider.get_credentials()

        # Check if we need to refresh the client (first time or creds expired)
        if self._s3_client is None or creds.needs_refresh():
            session_kwargs: dict[str, Any] = {
                "aws_access_key_id": creds.access_key,
                "aws_secret_access_key": creds.secret_key,
            }

            if creds.session_token:
                session_kwargs["aws_session_token"] = creds.session_token

            if creds.region:
                session_kwargs["region_name"] = creds.region

            session = boto3.Session(**session_kwargs)
            object.__setattr__(self, "_s3_client", session.client("s3"))
            logger.debug("Created new S3 client with refreshed credentials")

        return self._s3_client

    def _parse_s3_path(self, path: str) -> tuple[str, str]:
        """Parse S3 path into bucket and key.

        Args:
            path: S3 path (e.g., "s3://bucket/key/to/file.json")

        Returns:
            Tuple of (bucket_name, object_key)

        Raises:
            CloudStorageError: If path is invalid or missing bucket

        Examples:
            >>> adapter._parse_s3_path("s3://my-bucket/path/to/file.json")
            ('my-bucket', 'path/to/file.json')
            >>>
            >>> adapter._parse_s3_path("s3://logs/")
            ('logs', '')
        """
        parsed = urlparse(path)

        if parsed.scheme != "s3":
            raise CloudStorageError(
                operation="parse",
                path=path,
                reason="Invalid S3 path - must start with s3://",
            )

        bucket = parsed.netloc
        if not bucket:
            raise CloudStorageError(
                operation="parse",
                path=path,
                reason="Invalid S3 path - missing bucket name",
            )

        # Remove leading slash from key
        key = parsed.path.lstrip("/")

        return bucket, key

    def path_exists(self, path: str) -> bool:
        """Check if S3 path exists.

        Args:
            path: S3 path to check

        Returns:
            True if path exists (file or prefix), False otherwise

        Examples:
            >>> adapter.path_exists("s3://my-bucket/logs/app.json")  # True
            >>> adapter.path_exists("s3://my-bucket/nonexistent/")  # False
            >>> adapter.path_exists("s3://my-bucket/logs/")  # True (prefix)
        """
        bucket, key = self._parse_s3_path(path)

        try:
            # First try as a file
            self.s3_client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            # If not a file, try as a prefix
            try:
                response = self.s3_client.list_objects_v2(
                    Bucket=bucket,
                    Prefix=key,
                    MaxKeys=1,
                )
                return "Contents" in response and len(response["Contents"]) > 0
            except Exception:
                return False

    def list_files(
        self,
        path: str,
        recursive: bool = True,  # noqa: ARG002
        pattern: str | None = None,
    ) -> list[dict[str, Any]]:
        """List files in S3 prefix.

        Args:
            path: S3 prefix to list
            recursive: Whether to list recursively (default: True)
            pattern: Optional glob pattern to filter files (e.g., "*.json")

        Returns:
            List of file info dictionaries with:
                - path: str - Full S3 path
                - size: int - File size in bytes
                - last_modified: str - ISO 8601 timestamp (if available)
                - etag: str - S3 ETag (if available)

        Examples:
            >>> files = adapter.list_files("s3://my-bucket/logs/")
            >>> files[0]
            {'path': 's3://my-bucket/logs/app.json', 'size': 1024, 'last_modified': '2024-01-01T00:00:00Z'}
            >>>
            >>> # With pattern
            >>> files = adapter.list_files("s3://my-bucket/logs/", pattern="*.json")
        """
        bucket, prefix = self._parse_s3_path(path)

        files: list[dict[str, Any]] = []

        try:
            # Try simple list_objects_v2 first (handles up to 1000 objects)
            response = self.s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)

            if "Contents" not in response:
                return []

            for obj in response["Contents"]:
                key = obj["Key"]

                # Skip directories (keys ending with /)
                if key.endswith("/"):
                    continue

                # Apply pattern filter if provided
                if pattern:  # noqa: SIM102
                    if not fnmatch.fnmatch(key, pattern) and not fnmatch.fnmatch(
                        key.split("/")[-1], pattern
                    ):
                        continue

                file_info: dict[str, Any] = {
                    "path": f"s3://{bucket}/{key}",
                    "size": obj["Size"],
                }

                if "LastModified" in obj:
                    file_info["last_modified"] = obj["LastModified"].isoformat()

                if "ETag" in obj:
                    file_info["etag"] = obj["ETag"].strip('"')

                files.append(file_info)

            return files

        except Exception as e:
            logger.warning(f"Failed to list S3 files at {path}: {e}")
            return []

    def read_chunk(
        self,
        path: str,
        offset: int,
        length: int,
    ) -> bytes | None:
        """Read chunk of bytes from S3 object.

        Args:
            path: S3 object path
            offset: Byte offset to start reading
            length: Number of bytes to read

        Returns:
            Chunk data as bytes, or None if file doesn't exist

        Examples:
            >>> # Read first 1MB
            >>> chunk = adapter.read_chunk("s3://my-bucket/logs/app.json", 0, 1024*1024)
            >>>
            >>> # Read next chunk
            >>> chunk2 = adapter.read_chunk("s3://my-bucket/logs/app.json", 1024*1024, 1024*1024)
        """
        bucket, key = self._parse_s3_path(path)

        try:
            # Use HTTP range request (bytes are inclusive)
            range_header = f"bytes={offset}-{offset + length - 1}"

            response = self.s3_client.get_object(
                Bucket=bucket,
                Key=key,
                Range=range_header,
            )

            # Read body and return bytes
            return response["Body"].read()

        except Exception as e:
            logger.debug(f"Failed to read chunk from {path}: {e}")
            return None

    def get_file_size(self, path: str) -> int:
        """Get S3 object size in bytes.

        Args:
            path: S3 object path

        Returns:
            File size in bytes

        Raises:
            CloudStorageError: If file doesn't exist or operation fails

        Examples:
            >>> size = adapter.get_file_size("s3://my-bucket/logs/app.json")
            >>> size  # 1024
        """
        bucket, key = self._parse_s3_path(path)

        try:
            response = self.s3_client.head_object(Bucket=bucket, Key=key)
            return response["ContentLength"]
        except Exception as e:
            raise CloudStorageError(
                operation="get_size",
                path=path,
                reason=str(e),
            ) from e
