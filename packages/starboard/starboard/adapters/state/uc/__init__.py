# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unity Catalog serialization helpers.

The UC-native conversation / memory / user / feedback *state backend* was
removed in the native-first simplification (state is memory-only). The
``_serde`` helpers remain because the UC-native cluster-observation store
(:mod:`starboard.tools.services.cluster_observation_store`) reuses them over the
shared :class:`starboard.infra.storage.uc_adapter.UCStorageAdapter`. Import the
submodule directly: ``from starboard.adapters.state.uc import _serde``.
"""
