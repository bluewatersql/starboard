# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Cache infrastructure.

Provides the dependency-free async LRU cache (:mod:`async_lru_cache`). The
similarity-based / TTL semantic-cache implementations were removed in the
native-first simplification (they were only wired through the now-retired
foundation container).
"""
