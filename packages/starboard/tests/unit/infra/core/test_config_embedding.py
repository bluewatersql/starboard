# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for embedding configuration fields on EnvConfig.

Tests cover:
- Default values for embedding_model and embedding_base_url
- from_env() loading from environment variables
- sync_to_env() writing embedding fields
"""

import os
from unittest.mock import patch

from starboard.infra.core.config import EnvConfig


class TestEmbeddingConfigDefaults:
    def test_default_embedding_model(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("EMBEDDING_MODEL", "EMBEDDING_BASE_URL")
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = EnvConfig(_env_file=None)
        assert cfg.embedding_model == "databricks-bge-large-en"

    def test_default_embedding_base_url(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("EMBEDDING_MODEL", "EMBEDDING_BASE_URL")
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = EnvConfig(_env_file=None)
        assert cfg.embedding_base_url == ""


class TestEmbeddingConfigFromEnv:
    def test_loads_embedding_model(self):
        with patch.dict(
            os.environ, {"EMBEDDING_MODEL": "text-embedding-3-small"}, clear=False
        ):
            cfg = EnvConfig.from_env()
        assert cfg.embedding_model == "text-embedding-3-small"

    def test_loads_embedding_base_url(self):
        with patch.dict(
            os.environ,
            {"EMBEDDING_BASE_URL": "https://api.openai.com/v1"},
            clear=False,
        ):
            cfg = EnvConfig.from_env()
        assert cfg.embedding_base_url == "https://api.openai.com/v1"

    def test_empty_embedding_base_url(self):
        env = {k: v for k, v in os.environ.items() if k != "EMBEDDING_BASE_URL"}
        with patch.dict(os.environ, env, clear=True):
            cfg = EnvConfig.from_env()
        assert cfg.embedding_base_url == ""


class TestEmbeddingConfigSyncToEnv:
    def test_sync_embedding_model(self):
        cfg = EnvConfig(embedding_model="text-embedding-3-small")
        with patch.dict(os.environ, {}, clear=False):
            cfg.sync_to_env()
            assert os.environ["EMBEDDING_MODEL"] == "text-embedding-3-small"

    def test_sync_embedding_base_url(self):
        cfg = EnvConfig(embedding_base_url="https://api.openai.com/v1")
        with patch.dict(os.environ, {}, clear=False):
            cfg.sync_to_env()
            assert os.environ["EMBEDDING_BASE_URL"] == "https://api.openai.com/v1"

    def test_sync_empty_embedding_base_url_skipped(self):
        cfg = EnvConfig(embedding_base_url="")
        env_copy = dict(os.environ)
        env_copy.pop("EMBEDDING_BASE_URL", None)
        with patch.dict(os.environ, env_copy, clear=True):
            cfg.sync_to_env()
            assert "EMBEDDING_BASE_URL" not in os.environ
