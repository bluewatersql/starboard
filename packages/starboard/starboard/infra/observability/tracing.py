# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""OpenTelemetry tracing initialization and utilities.

Provides:
- TracerProvider initialization with optional OTLP export
- get_tracer() for creating named tracers
- TraceContextFilter for injecting trace_id/span_id into log records

Usage:
    from starboard.infra.observability.tracing import init_tracing, get_tracer

    # At app startup:
    init_tracing(service_name="starboard-server", otlp_endpoint="http://localhost:4317")

    # In modules:
    tracer = get_tracer("starboard.agents")
    with tracer.start_as_current_span("agent.handle_message") as span:
        span.set_attribute("agent.domain", "query")
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def init_tracing(
    service_name: str = "starboard-server",
    otlp_endpoint: str | None = None,
) -> None:
    """Initialize OpenTelemetry TracerProvider.

    Args:
        service_name: Service name for resource identification.
        otlp_endpoint: OTLP gRPC endpoint (e.g. "http://localhost:4317").
            If None, tracing is enabled but spans are not exported.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)


def get_tracer(name: str) -> trace.Tracer:
    """Get a named tracer from the global TracerProvider.

    Args:
        name: Tracer name, typically module path (e.g. "starboard.agents").

    Returns:
        A Tracer instance for creating spans.
    """
    return trace.get_tracer(name)


class TraceContextFilter(logging.Filter):
    """Logging filter that injects trace_id and span_id into log records.

    Add to a logging handler to include OpenTelemetry context in structured logs:

        handler.addFilter(TraceContextFilter())

    Log format can then include %(trace_id)s and %(span_id)s.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            record.trace_id = format(ctx.trace_id, "032x")  # type: ignore[attr-defined]
            record.span_id = format(ctx.span_id, "016x")  # type: ignore[attr-defined]
        else:
            record.trace_id = ""  # type: ignore[attr-defined]
            record.span_id = ""  # type: ignore[attr-defined]
        return True
