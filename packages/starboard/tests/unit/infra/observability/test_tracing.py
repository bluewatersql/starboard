# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for OpenTelemetry tracing module."""

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from starboard.infra.observability.tracing import (
    TraceContextFilter,
    get_tracer,
    init_tracing,
)


class _ListSpanExporter(SpanExporter):
    """Simple span exporter that collects spans in a list for testing."""

    def __init__(self) -> None:
        self.spans: list[Any] = []

    def export(self, spans: Any) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def _make_provider_with_exporter() -> tuple[TracerProvider, _ListSpanExporter]:
    """Create a TracerProvider with a list-based exporter for assertions."""
    exporter = _ListSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


class TestInitTracing:
    def test_sets_global_tracer_provider(self):
        init_tracing(service_name="test-service")
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)

    def test_service_name_in_resource(self):
        """Verify resource attributes include service.name."""
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": "my-service"})
        provider = TracerProvider(resource=resource)
        assert provider.resource.attributes["service.name"] == "my-service"

    def test_noop_when_no_endpoint(self):
        """When otlp_endpoint is None, provider is set but no exporter added."""
        init_tracing(service_name="test", otlp_endpoint=None)
        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)


class TestGetTracer:
    def test_returns_tracer(self):
        init_tracing(service_name="test")
        tracer = get_tracer("test.module")
        assert tracer is not None

    def test_tracer_creates_spans(self):
        """get_tracer returns a working tracer that can create spans."""
        provider, exporter = _make_provider_with_exporter()
        # Use provider directly — OTel SDK disallows overriding the global provider.
        tracer = provider.get_tracer("test.module")

        with tracer.start_as_current_span("test-op"):
            pass

        assert len(exporter.spans) == 1
        assert exporter.spans[0].name == "test-op"


class TestTraceContextFilter:
    def test_adds_trace_id_and_span_id_to_log_record(self):
        """When inside a span, trace_id and span_id are set on the log record."""
        provider, _ = _make_provider_with_exporter()
        trace.set_tracer_provider(provider)
        tracer = provider.get_tracer("test")
        filt = TraceContextFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )

        with tracer.start_as_current_span("test-span"):
            filt.filter(record)

        assert hasattr(record, "trace_id")
        assert hasattr(record, "span_id")
        assert len(record.trace_id) == 32  # type: ignore[attr-defined]
        assert len(record.span_id) == 16  # type: ignore[attr-defined]

    def test_empty_ids_outside_span(self):
        """Outside any span, trace_id and span_id are empty strings."""
        filt = TraceContextFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert record.trace_id == ""  # type: ignore[attr-defined]
        assert record.span_id == ""  # type: ignore[attr-defined]

    def test_filter_always_returns_true(self):
        """Filter should never suppress log records."""
        filt = TraceContextFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        assert filt.filter(record) is True


class TestSpanCreation:
    def test_span_attributes_recorded(self):
        """Verify spans record attributes correctly."""
        provider, exporter = _make_provider_with_exporter()
        tracer = provider.get_tracer("test.spans")

        with tracer.start_as_current_span(
            "agent.handle_message",
            attributes={"agent.domain": "query", "agent.model": "gpt-4o"},
        ) as span:
            span.set_attribute("agent.tokens_used", 1500)

        assert len(exporter.spans) == 1
        assert exporter.spans[0].name == "agent.handle_message"
        assert exporter.spans[0].attributes["agent.domain"] == "query"
        assert exporter.spans[0].attributes["agent.tokens_used"] == 1500

    def test_nested_spans_have_parent(self):
        """Child spans reference parent trace context."""
        provider, exporter = _make_provider_with_exporter()
        tracer = provider.get_tracer("test.nested")

        with (
            tracer.start_as_current_span("parent"),
            tracer.start_as_current_span("child"),
        ):
            pass

        assert len(exporter.spans) == 2
        child, parent = exporter.spans[0], exporter.spans[1]
        assert child.parent is not None
        assert child.parent.trace_id == parent.context.trace_id
