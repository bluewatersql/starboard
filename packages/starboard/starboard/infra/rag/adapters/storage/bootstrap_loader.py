# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Bootstrap data loader for in-memory vector store.

Loads RAG data from package-managed JSON/NPZ files exported from
the production vector store. Provides fallback to hardcoded data
if export files are not available.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from starboard_core.rag.models import (
    RAGCodebookContext,
    RAGNuanceContext,
    RAGTableContext,
)

from starboard.infra.io import read_json
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.infra.rag.adapters.storage.inmemory_vector_store import (
        InMemoryMultiCollectionStore,
    )

logger = get_logger(__name__)

# Package-managed bootstrap data directory
BOOTSTRAP_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "bootstrap"


class BootstrapDataLoader:
    """Load bootstrap data from exported JSON/NPZ files."""

    def __init__(self, data_dir: Path | None = None):
        """Initialize loader.

        Args:
            data_dir: Directory containing bootstrap data (defaults to package location)
        """
        self.data_dir = data_dir or BOOTSTRAP_DATA_DIR

    def is_available(self) -> bool:
        """Check if bootstrap data is available.

        Returns:
            True if manifest.json exists
        """
        return (self.data_dir / "manifest.json").exists()

    async def load_manifest(self) -> dict[str, Any] | None:
        """Load export manifest.

        Returns:
            Manifest dictionary or None if not available
        """
        manifest_file = self.data_dir / "manifest.json"
        if not manifest_file.exists():
            return None

        return await read_json(manifest_file)

    async def load_tables(
        self,
        with_embeddings: bool = True,
    ) -> tuple[list[RAGTableContext], dict[int, np.ndarray] | None]:
        """Load table metadata from bootstrap data.

        Args:
            with_embeddings: Whether to load precomputed embeddings

        Returns:
            Tuple of (tables, embeddings_dict) or (tables, None)
        """
        json_file = self.data_dir / "tables.json"
        if not json_file.exists():
            logger.debug("tables_bootstrap_not_found", file=str(json_file))
            return [], None

        records = await read_json(json_file)

        # Convert to RAGTableContext with original IDs for embedding lookup
        tables = []
        table_id_map = {}  # Map table index to original ID for embedding lookup
        for idx, record in enumerate(records):
            metadata = record.get("metadata", {})

            # Extract table information from metadata
            table = RAGTableContext(
                table_name=metadata.get("table_name"),
                domain=metadata.get("rag_resource_domain"),
                description=record.get("content", ""),
                table_columns=metadata.get("table_columns", ""),
                relationships=metadata.get("relationships", ""),
                use_cases=metadata.get("use_cases", ""),
                relevance_score=1.0,
            )
            tables.append(table)

            # Store mapping of table to original embedding ID
            if "embedding_ref" in record:
                table_id_map[idx] = record["embedding_ref"]

        # Load embeddings if requested and remap by table index
        embeddings = None
        if with_embeddings:
            npz_file = self.data_dir / "tables_embeddings.npz"
            if npz_file.exists():
                raw_embeddings = dict(np.load(npz_file))

                # Remap embeddings by table index for easier lookup
                embeddings = {}
                for idx, embedding_ref in table_id_map.items():
                    if embedding_ref in raw_embeddings:
                        embeddings[idx] = raw_embeddings[embedding_ref]

                logger.debug(
                    "tables_embeddings_loaded",
                    count=len(embeddings),
                    file=str(npz_file),
                )

        logger.info(
            "tables_bootstrap_loaded",
            count=len(tables),
            with_embeddings=embeddings is not None,
        )

        return tables, embeddings

    async def load_nuance(
        self,
        with_embeddings: bool = True,
    ) -> tuple[list[RAGNuanceContext], dict[int, np.ndarray] | None]:
        """Load nuance/best practices from bootstrap data.

        Args:
            with_embeddings: Whether to load precomputed embeddings

        Returns:
            Tuple of (nuance, embeddings_dict) or (nuance, None)
        """
        json_file = self.data_dir / "nuance.json"
        if not json_file.exists():
            logger.debug("nuance_bootstrap_not_found", file=str(json_file))
            return [], None

        records = await read_json(json_file)

        # Convert to RAGNuanceContext with original IDs for embedding lookup
        nuance = []
        nuance_id_map = {}
        for idx, record in enumerate(records):
            metadata = record.get("metadata", {})

            item = RAGNuanceContext(
                topic=metadata.get("doc_type", "general"),
                type=metadata.get("doc_type", "general"),
                content=record.get("content", ""),
                domain=metadata.get("rag_resource_domain", "general"),
                relevance_score=1.0,
            )
            nuance.append(item)

            # Store mapping to original embedding ID
            if "embedding_ref" in record:
                nuance_id_map[idx] = record["embedding_ref"]

        # Load embeddings if requested and remap by index
        embeddings = None
        if with_embeddings:
            npz_file = self.data_dir / "nuance_embeddings.npz"
            if npz_file.exists():
                raw_embeddings = dict(np.load(npz_file))

                # Remap embeddings by index
                embeddings = {}
                for idx, embedding_ref in nuance_id_map.items():
                    if embedding_ref in raw_embeddings:
                        embeddings[idx] = raw_embeddings[embedding_ref]

                logger.debug(
                    "nuance_embeddings_loaded",
                    count=len(embeddings),
                    file=str(npz_file),
                )

        logger.info(
            "nuance_bootstrap_loaded",
            count=len(nuance),
            with_embeddings=embeddings is not None,
        )

        return nuance, embeddings

    async def load_codebook(
        self,
        with_embeddings: bool = True,
    ) -> tuple[list[RAGCodebookContext], dict[int, np.ndarray] | None]:
        """Load codebook entries from bootstrap data.

        Args:
            with_embeddings: Whether to load precomputed embeddings

        Returns:
            Tuple of (codebook, embeddings_dict) or (codebook, None)
        """
        json_file = self.data_dir / "codebook.json"
        if not json_file.exists():
            logger.debug("codebook_bootstrap_not_found", file=str(json_file))
            return [], None

        records = await read_json(json_file)

        # Convert to RAGCodebookContext with original IDs for embedding lookup
        codebook = []
        codebook_id_map = {}
        for idx, record in enumerate(records):
            metadata = record.get("metadata", {})

            entry = RAGCodebookContext(
                code=metadata.get("code_key", record.get("id", "unknown")),
                description=record.get("content", ""),
                sku_family=metadata.get("sku_family", "N/A"),
                warehouse_type=metadata.get("warehouse_type", "ALL"),
                time_validity=metadata.get("time_validity", "Always"),
                involves_tags=metadata.get("involves_tags", False),
                domain=metadata.get("rag_resource_domain", "general"),
                relevance_score=1.0,
            )
            codebook.append(entry)

            # Store mapping to original embedding ID
            if "embedding_ref" in record:
                codebook_id_map[idx] = record["embedding_ref"]

        # Load embeddings if requested and remap by index
        embeddings = None
        if with_embeddings:
            npz_file = self.data_dir / "codebook_embeddings.npz"
            if npz_file.exists():
                raw_embeddings = dict(np.load(npz_file))

                # Remap embeddings by index
                embeddings = {}
                for idx, embedding_ref in codebook_id_map.items():
                    if embedding_ref in raw_embeddings:
                        embeddings[idx] = raw_embeddings[embedding_ref]

                logger.debug(
                    "codebook_embeddings_loaded",
                    count=len(embeddings),
                    file=str(npz_file),
                )

        logger.info(
            "codebook_bootstrap_loaded",
            count=len(codebook),
            with_embeddings=embeddings is not None,
        )

        return codebook, embeddings


async def load_bootstrap_data(
    store: InMemoryMultiCollectionStore,
    use_exported: bool = True,
    use_hardcoded: bool = True,
) -> dict[str, int]:
    """Load bootstrap data into in-memory store.

    Priority:
    1. Package-managed exported data (if use_exported=True and available)
    2. Hardcoded essential data (if use_hardcoded=True)

    Args:
        store: In-memory vector store to populate
        use_exported: Whether to try loading exported data first
        use_hardcoded: Whether to fall back to hardcoded data

    Returns:
        Dictionary with counts of loaded items
    """
    counts = {"tables": 0, "nuance": 0, "codebook": 0}

    # Try loading exported data first
    if use_exported:
        loader = BootstrapDataLoader()

        if loader.is_available():
            manifest = await loader.load_manifest()
            logger.info(
                "using_exported_bootstrap_data",
                export_timestamp=manifest.get("export_timestamp") if manifest else None,
                total_records=manifest.get("total_records") if manifest else None,
            )

            # Load tables
            tables, tables_embeddings = await loader.load_tables(with_embeddings=True)
            if tables:
                await store.add_tables(tables, precomputed_embeddings=tables_embeddings)
                counts["tables"] = len(tables)

            # Load nuance
            nuance, nuance_embeddings = await loader.load_nuance(with_embeddings=True)
            if nuance:
                await store.add_nuance(nuance, precomputed_embeddings=nuance_embeddings)
                counts["nuance"] = len(nuance)

            # Load codebook
            codebook, codebook_embeddings = await loader.load_codebook(
                with_embeddings=True
            )
            if codebook:
                await store.add_codebook(
                    codebook, precomputed_embeddings=codebook_embeddings
                )
                counts["codebook"] = len(codebook)

            # If we loaded anything, we're done
            if sum(counts.values()) > 0:
                logger.info(
                    "bootstrap_data_loaded_from_exports",
                    **counts,
                )
                return counts

            logger.warning(
                "exported_bootstrap_empty",
                fallback="hardcoded" if use_hardcoded else "none",
            )

        else:
            logger.debug(
                "exported_bootstrap_not_available",
                data_dir=str(loader.data_dir),
                fallback="hardcoded" if use_hardcoded else "none",
            )

    # Fall back to hardcoded data
    if use_hardcoded and sum(counts.values()) == 0:
        logger.info("using_hardcoded_bootstrap_data")
        from starboard.infra.rag.adapters.storage.inmemory_bootstrap import (
            InMemoryVectorStoreBootstrap,
        )

        hardcoded_counts = await InMemoryVectorStoreBootstrap.bootstrap(store)
        counts.update(hardcoded_counts)

        logger.info(
            "bootstrap_data_loaded_from_hardcoded",
            extra=counts,
        )

    return counts
