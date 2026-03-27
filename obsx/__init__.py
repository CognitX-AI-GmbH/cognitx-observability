"""
Observability - Plug-and-play Phoenix OTEL tracing + Prometheus metrics for Python services.

Usage in any service's main.py:

    from obsx import init_observability, metrics_router

    init_observability(
        service_name="my-service",
        environment="production",
        phoenix_enabled=True,
        phoenix_endpoint="http://phoenix:4317",
        trace_sample_rate=0.5,  # 50% sampling in production
    )

    app = FastAPI()
    app.include_router(metrics_router())

Then in application code:

    from obsx import get_meter, get_tracer

    meter = get_meter("analytics")
    runs_total = meter.create_counter("analytics.runs_total")
    runs_total.add(1, {"route": "data", "status": "success"})

    tracer = get_tracer("analytics")
    with tracer.start_as_current_span("plan_analysis"):
        ...

For LLM inference metrics with proper histogram buckets:

    from obsx import create_histogram_llm, create_histogram_tokens

    meter = get_meter("inference")
    ttft = create_histogram_llm(meter, "inference.ttft_seconds", "Time to first token")
    tokens = create_histogram_tokens(meter, "inference.output_tokens", "Output token count")
"""

# Re-export OTEL trace for convenience
from opentelemetry import trace

from ._metrics import (
    LATENCY_BUCKETS_DEFAULT,
    LATENCY_BUCKETS_LLM,
    TOKEN_COUNT_BUCKETS,
    create_counter,
    create_histogram,
    create_histogram_llm,
    create_histogram_tokens,
    create_up_down_counter,
    get_meter,
    llm_metric_views,
    metrics_router,
)
from ._middleware import RequestMetricsMiddleware
from ._setup import init_observability, shutdown

get_tracer = trace.get_tracer

__all__ = [
    "init_observability",
    "shutdown",
    "metrics_router",
    "get_meter",
    "get_tracer",
    "create_counter",
    "create_histogram",
    "create_histogram_llm",
    "create_histogram_tokens",
    "create_up_down_counter",
    "llm_metric_views",
    "RequestMetricsMiddleware",
    "LATENCY_BUCKETS_DEFAULT",
    "LATENCY_BUCKETS_LLM",
    "TOKEN_COUNT_BUCKETS",
]
