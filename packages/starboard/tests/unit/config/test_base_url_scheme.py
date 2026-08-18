# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for llm_base_url / embedding_base_url scheme normalization.

Validates that schemeless URLs get https:// prepended, existing schemes are
preserved, and empty strings pass through unchanged.
"""

from __future__ import annotations

import pytest

from starboard.infra.core.config import EnvConfig


class TestEnsureUrlScheme:
    """Tests for _ensure_url_scheme field validator on llm_base_url and embedding_base_url."""

    # --- llm_base_url ---

    def test_llm_base_url_schemeless_gets_https(self):
        cfg = EnvConfig(llm_base_url="foo.databricks.com/serving-endpoints")
        assert cfg.llm_base_url == "https://foo.databricks.com/serving-endpoints"

    def test_llm_base_url_http_preserved(self):
        cfg = EnvConfig(llm_base_url="http://foo.databricks.com/serving-endpoints")
        assert cfg.llm_base_url == "http://foo.databricks.com/serving-endpoints"

    def test_llm_base_url_https_preserved(self):
        cfg = EnvConfig(llm_base_url="https://foo.databricks.com/serving-endpoints")
        assert cfg.llm_base_url == "https://foo.databricks.com/serving-endpoints"

    def test_llm_base_url_empty_stays_empty(self):
        cfg = EnvConfig(llm_base_url="")
        assert cfg.llm_base_url == ""

    # --- embedding_base_url ---

    def test_embedding_base_url_schemeless_gets_https(self):
        cfg = EnvConfig(embedding_base_url="e2-demo-field-eng.cloud.databricks.com/serving-endpoints")
        assert cfg.embedding_base_url == "https://e2-demo-field-eng.cloud.databricks.com/serving-endpoints"

    def test_embedding_base_url_http_preserved(self):
        cfg = EnvConfig(embedding_base_url="http://e2-demo-field-eng.cloud.databricks.com/serving-endpoints")
        assert cfg.embedding_base_url == "http://e2-demo-field-eng.cloud.databricks.com/serving-endpoints"

    def test_embedding_base_url_https_preserved(self):
        cfg = EnvConfig(embedding_base_url="https://e2-demo-field-eng.cloud.databricks.com/serving-endpoints")
        assert cfg.embedding_base_url == "https://e2-demo-field-eng.cloud.databricks.com/serving-endpoints"

    def test_embedding_base_url_empty_stays_empty(self):
        cfg = EnvConfig(embedding_base_url="")
        assert cfg.embedding_base_url == ""
