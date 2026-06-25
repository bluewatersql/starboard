# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Diagnostic domain logic for artifact-first troubleshooting.

This module provides the core domain logic for the Diagnostic Agent v2:
- Artifact detection and normalization
- Error pattern matching
- Exit code triage
- Evidence extraction

Design reference: changes/diagnostic_agent/UNIFIED_DESIGN.md
"""

from starboard_server.tools.domain.diagnostic.artifact_detector import ArtifactDetector
from starboard_server.tools.domain.diagnostic.artifact_explorer import (
    ONLINE_STRATEGIES,
    ArtifactExplorer,
    ExplorationResult,
    ExplorationState,
    ExplorationStep,
    ExplorationStrategy,
    ToolCallRequest,
)
from starboard_server.tools.domain.diagnostic.artifact_normalizer import (
    ArtifactNormalizer,
    NormalizationResult,
)
from starboard_server.tools.domain.diagnostic.context_extractor import (
    ContextMode,
    DatabricksContextExtractor,
    ExtractedId,
    IdType,
)
from starboard_server.tools.domain.diagnostic.diagnostic_context_builder import (
    DiagnosticContext,
    DiagnosticContextBuilder,
    ToolResultCache,
)
from starboard_server.tools.domain.diagnostic.evidence_extractor import (
    EvidenceType,
    EvidenceWindowExtractor,
)
from starboard_server.tools.domain.diagnostic.exit_code_triager import (
    ExitCodeTriager,
    HypothesisType,
    TriageResult,
)
from starboard_server.tools.domain.diagnostic.exploration_observability import (
    ExplorationMetrics,
    ExplorationTelemetry,
    StepMetrics,
)
from starboard_server.tools.domain.diagnostic.exploration_tool_adapter import (
    ExplorationToolAdapter,
    create_exploration_tools,
)
from starboard_server.tools.domain.diagnostic.handoff_protocol import (
    HandoffProtocol,
    HandoffResult,
)
from starboard_server.tools.domain.diagnostic.models import (
    Artifact,
    ArtifactSource,
    ArtifactStats,
    ArtifactSummary,
    ArtifactType,
    CodeLanguage,
    ConfidenceFactors,
    DatabricksContext,
    DetectionResult,
    DiagnosticFingerprint,
    ErrorPattern,
    EvidenceChecklist,
    EvidenceWindow,
    ExitCodeDiagnosis,
    ExplorationSummary,
    PatternCategory,
    PatternMatch,
    PatternSignature,
    PrimarySymptom,
    Recommendation,
    TruncationInfo,
)
from starboard_server.tools.domain.diagnostic.root_cause_synthesizer import (
    RootCauseSynthesizer,
    SynthesisResult,
    ToolOutput,
)
from starboard_server.tools.domain.diagnostic.tool_governance import (
    ToolGovernance,
    ToolPriority,
    ToolRequest,
)

__all__ = [
    # Artifact types and enums
    "ArtifactType",
    "CodeLanguage",
    "ArtifactSource",
    "PatternCategory",
    # Core dataclasses
    "Artifact",
    "ArtifactStats",
    "ArtifactSummary",
    "DatabricksContext",
    "DetectionResult",
    "EvidenceWindow",
    "TruncationInfo",
    # Pattern matching
    "ConfidenceFactors",
    "ErrorPattern",
    "EvidenceChecklist",
    "PatternMatch",
    "PatternSignature",
    "Recommendation",
    # Exit code triage
    "ExitCodeDiagnosis",
    # Diagnostic fingerprint (handoff protocol)
    "DiagnosticFingerprint",
    "ExplorationSummary",
    "PrimarySymptom",
    # Detectors and processors
    "ArtifactDetector",
    "ArtifactNormalizer",
    "NormalizationResult",
    # Exit code triage
    "ExitCodeTriager",
    "HypothesisType",
    "TriageResult",
    # Context extraction
    "ContextMode",
    "DatabricksContextExtractor",
    "ExtractedId",
    "IdType",
    # Evidence extraction
    "EvidenceType",
    "EvidenceWindowExtractor",
    # Exploration orchestrator
    "ArtifactExplorer",
    "ExplorationResult",
    "ExplorationState",
    "ExplorationStep",
    "ExplorationStrategy",
    "ONLINE_STRATEGIES",
    "ToolCallRequest",
    # Context builder for prompt injection
    "DiagnosticContext",
    "DiagnosticContextBuilder",
    "ToolResultCache",
    # Tool adapter for LLM step selection
    "ExplorationToolAdapter",
    "create_exploration_tools",
    # Handoff protocol
    "HandoffProtocol",
    "HandoffResult",
    # Root cause synthesis
    "RootCauseSynthesizer",
    "SynthesisResult",
    "ToolOutput",
    # Tool governance
    "ToolGovernance",
    "ToolPriority",
    "ToolRequest",
    # Exploration observability
    "ExplorationMetrics",
    "ExplorationTelemetry",
    "StepMetrics",
]
