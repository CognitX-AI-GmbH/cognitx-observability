"""
Prometheus /metrics endpoint and meter helpers.

Provides a FastAPI router that serves Prometheus text format,
plus convenience functions for creating OTEL instruments.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, Meter, UpDownCounter
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

# Pre-defined bucket sets for common use cases
LATENCY_BUCKETS_DEFAULT = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
LATENCY_BUCKETS_LLM = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0)
TOKEN_COUNT_BUCKETS = (
    1,
    10,
    50,
    100,
    250,
    500,
    1000,
    2000,
    4000,
    8000,
    16000,
    32000,
    64000,
    128000,
)


_cached_router: APIRouter | None = None


def metrics_router(path: str = "/metrics", include_in_schema: bool = False) -> APIRouter:
    """Return a FastAPI router with a GET /metrics endpoint for Prometheus scraping.

    Idempotent: returns the same router instance on repeated calls to avoid
    duplicate route registration.

    Args:
        path: URL path for the metrics endpoint.
        include_in_schema: Whether to include in OpenAPI docs.
    """
    global _cached_router
    if _cached_router is not None:
        return _cached_router

    router = APIRouter(tags=["observability"])

    @router.get(path, include_in_schema=include_in_schema)
    async def prometheus_metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    _cached_router = router
    return router


def get_meter(name: str, version: str = "") -> Meter:
    """Get an OTEL Meter for creating instruments.

    Args:
        name: Meter name, typically the service or module name (e.g. "myapp.analytics").
        version: Optional version string.
    """
    return metrics.get_meter(name, version)


def create_counter(meter: Meter, name: str, description: str = "", unit: str = "") -> Counter:
    """Create a monotonic counter."""
    return meter.create_counter(name, description=description, unit=unit)


def create_histogram(meter: Meter, name: str, description: str = "", unit: str = "") -> Histogram:
    """Create a histogram for recording distributions (latency, sizes, etc.)."""
    return meter.create_histogram(name, description=description, unit=unit)


def create_histogram_llm(
    meter: Meter, name: str, description: str = "", unit: str = "s"
) -> Histogram:
    """Create a histogram for LLM latency metrics.

    The histogram itself uses default OTEL buckets, but when init_observability()
    registers llm_metric_views(), any histogram matching *ttft*, *tpot*, or
    *duration*seconds* automatically gets LLM-tuned buckets (0.1s to 120s).

    Name your metric accordingly (e.g. "inference.ttft_seconds") for automatic
    bucket matching.
    """
    return meter.create_histogram(name, description=description, unit=unit)


def create_histogram_tokens(
    meter: Meter,
    name: str,
    description: str = "",
) -> Histogram:
    """Create a histogram for token count metrics.

    The histogram itself uses default OTEL buckets, but when init_observability()
    registers llm_metric_views(), any histogram matching *tokens* automatically
    gets token-count buckets (1 to 128K).

    Name your metric accordingly (e.g. "inference.output_tokens") for automatic
    bucket matching.
    """
    return meter.create_histogram(name, description=description, unit="tokens")


def create_up_down_counter(
    meter: Meter, name: str, description: str = "", unit: str = ""
) -> UpDownCounter:
    """Create a gauge-like counter that can increase or decrease (active connections, queue depth)."""
    return meter.create_up_down_counter(name, description=description, unit=unit)


def llm_metric_views() -> list[View]:
    """Return OTEL Views that apply LLM-tuned histogram buckets.

    Register these when creating the MeterProvider to override default histogram buckets:

        from obsx._metrics import llm_metric_views
        MeterProvider(views=llm_metric_views(), ...)

    Views match on metric name patterns - any histogram ending in _duration_seconds
    gets LLM buckets, any ending in _tokens gets token-count buckets.
    """
    return [
        View(
            instrument_name="*ttft*",
            aggregation=ExplicitBucketHistogramAggregation(boundaries=list(LATENCY_BUCKETS_LLM)),
        ),
        View(
            instrument_name="*tpot*",
            aggregation=ExplicitBucketHistogramAggregation(
                boundaries=[0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5],
            ),
        ),
        View(
            instrument_name="*duration*seconds*",
            aggregation=ExplicitBucketHistogramAggregation(boundaries=list(LATENCY_BUCKETS_LLM)),
        ),
        View(
            instrument_name="*tokens*",
            aggregation=ExplicitBucketHistogramAggregation(boundaries=list(TOKEN_COUNT_BUCKETS)),
        ),
    ]
