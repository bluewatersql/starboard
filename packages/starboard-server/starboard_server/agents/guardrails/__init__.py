"""Guardrails for agent input processing."""

from starboard_server.agents.guardrails.injection_detector import (
    InjectionScanResult,
    scan_for_injection,
)

__all__ = ["InjectionScanResult", "scan_for_injection"]
