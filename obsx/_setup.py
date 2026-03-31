"""
Core setup function for the observability package.

Configures OpenTelemetry MeterProvider (Prometheus) and TracerProvider (Phoenix or OTLP).
Call once at service startup before creating any meters or tracers.
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, TraceIdRatioBased

logger = logging.getLogger("obsx.setup")

_initialized = False


def init_observability(
    service_name: str,
    service_version: str = "1.0.0",
    environment: str = "local",
    phoenix_enabled: bool = False,
    phoenix_endpoint: str | None = None,
    phoenix_project: str | None = None,
    otlp_endpoint: str | None = None,
    otlp_insecure: bool = True,
    enable_fastapi: bool = True,
    enable_httpx: bool = True,
    enable_openai: bool = True,
    enable_redis: bool = False,
    enable_sqlalchemy: bool = False,
    sqlalchemy_engine: Any = None,
    enable_log_correlation: bool = True,
    trace_sample_rate: float = 1.0,
    extra_resource_attrs: dict[str, Any] | None = None,
) -> None:
    """Initialize OpenTelemetry with Prometheus metrics and optional Phoenix/OTLP tracing.

    Must be called once at service startup, before any meters or tracers are created.

    Args:
        service_name: Service identifier (e.g. "my-service").
        service_version: SemVer version string.
        environment: Deployment environment (local, staging, production).
        phoenix_enabled: Enable Phoenix OTEL for LLM tracing.
        phoenix_endpoint: Phoenix OTLP gRPC endpoint (e.g. "http://phoenix:4317").
        phoenix_project: Phoenix project name (defaults to service_name).
        otlp_endpoint: OTLP gRPC endpoint for non-Phoenix trace export.
        otlp_insecure: Use insecure gRPC (no TLS). Set False for production cross-host.
        enable_fastapi: Auto-instrument FastAPI.
        enable_httpx: Auto-instrument httpx.
        enable_openai: Auto-instrument OpenAI SDK with OpenInference semantic spans.
        enable_redis: Auto-instrument Redis client.
        enable_sqlalchemy: Auto-instrument SQLAlchemy. Requires sqlalchemy_engine.
        sqlalchemy_engine: SQLAlchemy engine instance (sync or async).
        enable_log_correlation: Inject trace_id/span_id into log records.
        trace_sample_rate: Fraction of traces to export (0.0-1.0). Use <1.0 in production.
        extra_resource_attrs: Additional OTEL resource attributes.
    """
    global _initialized
    if _initialized:
        logger.warning("init_observability() called more than once - skipping")
        return
    _initialized = True

    project = phoenix_project or service_name

    resource_attrs: dict[str, Any] = {
        "service.name": service_name,
        "service.version": service_version,
        "deployment.environment": environment,
        "openinference.project.name": project,
    }
    if extra_resource_attrs:
        resource_attrs.update(extra_resource_attrs)
    resource = Resource.create(resource_attrs)

    # ── W3C Trace Context Propagation ──
    _setup_propagation()

    # ── Metrics (Prometheus) ── always enabled ──
    from ._metrics import llm_metric_views

    prometheus_reader = PrometheusMetricReader()
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[prometheus_reader],
        views=llm_metric_views(),
    )
    metrics.set_meter_provider(meter_provider)
    logger.info(
        "MeterProvider configured with PrometheusMetricReader + LLM views (service=%s)",
        service_name,
    )

    # ── Trace Sampling ──
    sampler = ALWAYS_ON if trace_sample_rate >= 1.0 else TraceIdRatioBased(trace_sample_rate)

    # ── Tracing ── Phoenix, OTLP, or no-op ──
    if phoenix_enabled:
        _setup_phoenix_tracing(
            service_name=service_name,
            phoenix_endpoint=phoenix_endpoint,
            phoenix_project=project,
        )
    elif otlp_endpoint:
        _setup_otlp_tracing(
            resource=resource,
            otlp_endpoint=otlp_endpoint,
            insecure=otlp_insecure,
            sampler=sampler,
        )
    else:
        tracer_provider = TracerProvider(resource=resource, sampler=sampler)
        trace.set_tracer_provider(tracer_provider)
        logger.info("TracerProvider configured (no exporter - traces are local only)")

    # ── Auto-instrumentation ──
    if enable_fastapi:
        _instrument_fastapi()
    if enable_httpx:
        _instrument_httpx()
    if enable_openai:
        _instrument_openai()
    if enable_redis:
        _instrument_redis()
    if enable_sqlalchemy:
        _instrument_sqlalchemy(sqlalchemy_engine)
    if enable_log_correlation:
        _instrument_logging()


def shutdown() -> None:
    """Flush pending spans and metrics. Call during service shutdown.

    Resets the initialization guard so init_observability() can be called again
    (useful in tests).
    """
    global _initialized
    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, "shutdown"):
        try:
            tracer_provider.shutdown()  # type: ignore[union-attr]
        except Exception:
            logger.exception("Error shutting down TracerProvider")

    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "shutdown"):
        try:
            meter_provider.shutdown()  # type: ignore[union-attr]
        except Exception:
            logger.exception("Error shutting down MeterProvider")

    _initialized = False


# ── Private helpers ──


def _setup_propagation() -> None:
    """Configure W3C Trace Context propagation for cross-service tracing."""
    try:
        from opentelemetry.baggage.propagation import W3CBaggagePropagator
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.propagators.composite import CompositeHTTPPropagator
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        set_global_textmap(
            CompositeHTTPPropagator(
                [
                    TraceContextTextMapPropagator(),
                    W3CBaggagePropagator(),
                ]
            )
        )
        logger.info("W3C Trace Context propagation enabled")
    except ImportError:
        logger.debug("W3C propagation packages not installed - using defaults")


def _setup_phoenix_tracing(
    service_name: str,
    phoenix_endpoint: str | None,
    phoenix_project: str,
) -> None:
    try:
        from phoenix.otel import register

        kwargs: dict[str, Any] = {
            "project_name": phoenix_project,
            "batch": True,
            "set_global_tracer_provider": True,
        }
        if phoenix_endpoint:
            kwargs["endpoint"] = phoenix_endpoint

        register(**kwargs)
        logger.info(
            "TracerProvider configured with Phoenix OTEL (project=%s, endpoint=%s)",
            phoenix_project,
            phoenix_endpoint or "default",
        )
    except ImportError:
        logger.warning(
            "arize-phoenix-otel not installed - falling back to no-op tracer. "
            "Install with: pip install arize-phoenix-otel"
        )
        trace.set_tracer_provider(TracerProvider())
    except Exception:
        logger.exception("Failed to initialize Phoenix OTEL - falling back to no-op tracer")
        trace.set_tracer_provider(TracerProvider())


def _setup_otlp_tracing(
    resource: Resource,
    otlp_endpoint: str,
    insecure: bool = True,
    sampler: Any = ALWAYS_ON,
) -> None:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    tracer_provider = TracerProvider(resource=resource, sampler=sampler)
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=insecure)
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(tracer_provider)
    logger.info(
        "TracerProvider configured with OTLP gRPC exporter (endpoint=%s, insecure=%s)",
        otlp_endpoint,
        insecure,
    )


def _instrument_fastapi() -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor().instrument(
            excluded_urls="health,health-check,healthz,ready,live,metrics,favicon.ico",
        )
        logger.info("FastAPI auto-instrumentation enabled")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-fastapi not installed - skipping")


def _instrument_httpx() -> None:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        logger.info("httpx auto-instrumentation enabled")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-httpx not installed - skipping")


def _instrument_openai() -> None:
    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument()
        logger.info("OpenAI (OpenInference) auto-instrumentation enabled")
    except ImportError:
        logger.debug("openinference-instrumentation-openai not installed - skipping")


def _instrument_redis() -> None:
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        logger.info("Redis auto-instrumentation enabled")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-redis not installed - skipping")


def _instrument_sqlalchemy(engine: Any) -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        if engine is not None:
            # Handle both sync and async engines
            sync_engine = getattr(engine, "sync_engine", engine)
            SQLAlchemyInstrumentor().instrument(engine=sync_engine)
            logger.info("SQLAlchemy auto-instrumentation enabled")
        else:
            SQLAlchemyInstrumentor().instrument()
            logger.info("SQLAlchemy auto-instrumentation enabled (global)")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-sqlalchemy not installed - skipping")
    except Exception:
        logger.debug("SQLAlchemy instrumentation skipped (engine not compatible)")


def _instrument_logging() -> None:
    """Inject trace_id and span_id into Python log records for log-trace correlation."""
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        LoggingInstrumentor().instrument(set_logging_format=True)
        logger.info("Log-trace correlation enabled (trace_id/span_id injected into log records)")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-logging not installed - skipping")
