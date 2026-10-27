# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Public ``LogRetrievalPort`` adapter over the DBFS/Volumes log parser (C5).

Reads delivered cluster/driver log-delivery paths from DBFS or Unity Catalog
Volumes using the existing ``DBFSClient`` protocol (the same one the log parser
loaders use). No new capability — just the port surface.
"""

from __future__ import annotations

from starboard_core.log_parser.loaders.protocols import DBFSClient
from starboard_core.ports.log_retrieval import LogBundle, LogQuery, LogRetrievalPort

_CHUNK = 1024 * 1024  # 1 MiB


class SdkDbfsLogAdapter(LogRetrievalPort):
    """Fetch log content from DBFS/Volumes paths via a :class:`DBFSClient`.

    Args:
        dbfs_client: A ``DBFSClient`` implementation. When omitted, a default
            SDK-backed client is built lazily on first use (requires the
            optional ``databricks`` extra).
    """

    def __init__(self, dbfs_client: DBFSClient | None = None) -> None:
        self._client = dbfs_client

    @property
    def client(self) -> DBFSClient:
        if self._client is None:
            # Lazy SDK import: keeps this module importable without the extra.
            from starboard_core.log_parser.loaders.dbfs import _require_databricks_sdk
            from starboard_core.log_parser.loaders.dbfs_adapter import (
                DatabricksSDKAdapter,
            )

            workspace_client_cls = _require_databricks_sdk()
            self._client = DatabricksSDKAdapter(workspace_client_cls())
        return self._client

    async def fetch(self, ref: LogQuery) -> LogBundle:
        parts: list[str] = []
        read_paths: list[str] = []
        total_bytes = 0

        for path in ref.paths:
            for file_path in self._resolve_files(path):
                data = self._read_all(file_path)
                if not data:
                    continue
                parts.append(data.decode("utf-8", errors="replace"))
                read_paths.append(file_path)
                total_bytes += len(data)

        text = "\n".join(parts)
        line_count = text.count("\n") + 1 if text else 0
        return LogBundle(
            text=text,
            source="sdk-dbfs",
            line_count=line_count,
            paths=tuple(read_paths),
            metadata={"bytes": str(total_bytes), "entity": ref.entity},
        )

    def _resolve_files(self, path: str) -> list[str]:
        """Expand a path/prefix into concrete file paths."""
        try:
            if not self.client.dbfs_path_exists(path):
                return []
            listed = self.client.list_dbfs_files(path, recursive=True)
            files = [
                fi["path"]
                for fi in listed
                if not fi.get("is_dir", False) and fi.get("path")
            ]
            return files or [path]
        except Exception:
            # Non-fatal: an unreadable prefix yields no logs (public path degrades).
            return []

    def _read_all(self, file_path: str) -> bytes:
        buffer = bytearray()
        offset = 0
        while True:
            chunk = self.client.read_dbfs_chunk(file_path, offset, _CHUNK)
            if not chunk:
                break
            buffer.extend(chunk)
            offset += len(chunk)
            if len(chunk) < _CHUNK:
                break
        return bytes(buffer)
