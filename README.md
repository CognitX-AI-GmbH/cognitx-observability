# obsx

Plug-and-play observability for Python services. One function call configures OpenTelemetry tracing, Prometheus metrics, and auto-instrumentation for FastAPI, httpx, OpenAI, Redis, and SQLAlchemy.

Built for LLM-powered applications — includes Phoenix OTEL integration, OpenInference semantic spans, and histogram buckets tuned for inference latencies and token counts.

## Install

```bash
# Core package
pip install obsx

# With all optional instrumentations
pip install "obsx[all]"

# Specific extras
pip install "obsx[redis,sqlalchemy]"

# From GitHub
pip install "obsx @ git+https://github.com/CognitX-AI-GmbH/cognitx-observability.git"
```

## Quick Start

```python
from fastapi import FastAPI
from obsx import init_observability, metrics_router, shutdown

app = FastAPI()

@app.on_event("startup")
async def startup():
    init_observability(
        service_name="my-service",
        phoenix_enabled=True,
        phoenix_endpoint="http://phoenix:4317",
    )

@app.on_event("shutdown")
async def on_shutdown():
    shutdown()

# Expose GET /metrics for Prometheus scraping
app.include_router(metrics_router())
```

That's it. Your service now has:
- Prometheus metrics on `/metrics`
- Distributed traces exported to Phoenix
- Auto-instrumented FastAPI routes, httpx calls, and OpenAI SDK calls

## Configuration Reference

### `init_observability()`

Call once at service startup, before creating any meters or tracers.

```python
init_observability(
    # ── Required ──
    service_name="my-service",

    # ── Service metadata ──
    service_version="1.0.0",          # SemVer, shows in trace metadata
    environment="production",          # local | staging | production

    # ── Tracing backend (pick one) ──
    phoenix_enabled=True,              # Use Phoenix for LLM trace visualization
    phoenix_endpoint="http://phoenix:4317",  # Phoenix OTLP gRPC endpoint
    phoenix_project="my-project",      # Phoenix project name (defaults to service_name)
    # — OR —
    otlp_endpoint="http://jaeger:4317",  # Generic OTLP gRPC (Jaeger, Tempo, etc.)
    otlp_insecure=True,                  # False for TLS in production

    # ── Auto-instrumentation toggles ──
    enable_fastapi=True,               # Trace all FastAPI routes (default: True)
    enable_httpx=True,                 # Trace all outgoing HTTP calls (default: True)
    enable_openai=True,                # OpenAI SDK semantic spans (default: True)
    enable_redis=False,                # Redis command tracing (requires: pip install obsx[redis])
    enable_sqlalchemy=False,           # SQL query tracing (requires: pip install obsx[sqlalchemy])
    sqlalchemy_engine=engine,          # Pass your SQLAlchemy engine (sync or async)
    enable_log_correlation=True,       # Inject trace_id/span_id into log records

    # ── Sampling ──
    trace_sample_rate=1.0,             # 1.0 = export all traces, 0.1 = 10% sampling

    # ── Custom OTEL resource attributes ──
    extra_resource_attrs={
        "deployment.region": "eu-central-1",
        "k8s.pod.name": os.environ.get("POD_NAME", ""),
    },
)
```

### `shutdown()`

Flushes pending spans and metrics. Call during service shutdown.

```python
shutdown()
```

### `metrics_router()`

Returns a FastAPI `APIRouter` with a `GET /metrics` endpoint that serves Prometheus text format.

```python
from obsx import metrics_router

app.include_router(metrics_router())

# Custom path
app.include_router(metrics_router(path="/observability/metrics"))
```

## Metrics

### Creating Instruments

```python
from obsx import get_meter, create_counter, create_histogram

meter = get_meter("my-service")

# Counter
requests = create_counter(meter, "requests_total", "Total requests processed")
requests.add(1, {"endpoint": "/api/chat", "status": "success"})

# Histogram (default buckets)
latency = create_histogram(meter, "request_duration_seconds", "Request latency", unit="s")
latency.record(0.342, {"endpoint": "/api/chat"})
```

### LLM-Specific Metrics

Pre-configured histogram buckets optimized for LLM workloads:

```python
from obsx import get_meter, create_histogram_llm, create_histogram_tokens

meter = get_meter("inference")

# Time to first token (buckets: 0.1s to 120s)
ttft = create_histogram_llm(meter, "inference.ttft_seconds", "Time to first token")
ttft.record(0.847)

# Token counts (buckets: 1 to 128K)
output_tokens = create_histogram_tokens(meter, "inference.output_tokens", "Output token count")
output_tokens.record(1523)

# Total inference duration (buckets: 0.1s to 120s)
duration = create_histogram_llm(meter, "inference.duration_seconds", "Total inference time")
duration.record(12.4)
```

### Gauge (Up-Down Counter)

```python
from obsx import get_meter, create_up_down_counter

meter = get_meter("my-service")
active = create_up_down_counter(meter, "active_connections", "Currently open connections")
active.add(1)   # connection opened
active.add(-1)  # connection closed
```

### Bucket Constants

Available for custom histogram configurations:

```python
from obsx import LATENCY_BUCKETS_DEFAULT, LATENCY_BUCKETS_LLM, TOKEN_COUNT_BUCKETS

# LATENCY_BUCKETS_DEFAULT = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
# LATENCY_BUCKETS_LLM    = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0)
# TOKEN_COUNT_BUCKETS     = (1, 10, 50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000, 128000)
```

## Tracing

### Manual Spans

```python
from obsx import get_tracer

tracer = get_tracer("my-service")

# Simple span
with tracer.start_as_current_span("process_request") as span:
    span.set_attribute("user.id", user_id)
    span.set_attribute("request.type", "chat")
    result = await process(request)
    span.set_attribute("response.tokens", result.token_count)
```

### Cross-Service Propagation

W3C Trace Context propagation is enabled by default. Traces automatically flow across services when using instrumented HTTP clients (httpx).

```
Service A (FastAPI) → httpx call → Service B (FastAPI)
    └── trace_id: abc123 ──────────── trace_id: abc123 (same trace)
```

### OpenAI SDK Traces

When `enable_openai=True` (default), every `openai.ChatCompletion.create()` call generates a span with:
- Model name
- Token usage (prompt + completion)
- Request/response content
- Latency

These appear as LLM spans in Phoenix UI, enabling prompt debugging and cost tracking.

## Middleware

### `RequestMetricsMiddleware`

Optional middleware that records per-request counters beyond what OTEL's FastAPI auto-instrumentation provides.

```python
from obsx import RequestMetricsMiddleware

app.add_middleware(
    RequestMetricsMiddleware,
    service_name="my-service",
    known_routes=["/api/v1/chat", "/api/v1/models", "/api/v1/embeddings"],
)
```

**Metrics recorded:**

| Metric | Type | Labels |
|--------|------|--------|
| `http.requests_total` | Counter | `http.method`, `http.route`, `http.status_code` |
| `http.errors_total` | Counter | `http.method`, `http.route`, `http.status_code` |
| `http.request_duration_seconds` | Histogram | `http.method`, `http.route`, `http.status_code` |
| `http.active_requests` | UpDownCounter | `http.method`, `http.route` |

**Features:**
- Propagates or generates `X-Request-ID` header
- Links request ID to active OTEL span for cross-service correlation
- Skips `/health-check`, `/healthz`, `/ready`, `/live`, `/metrics`, `/favicon.ico`
- `known_routes` prevents Prometheus label cardinality explosion by collapsing dynamic path segments

### LLM Metric Views

`init_observability()` automatically registers histogram views with LLM-optimized buckets:

| Pattern | Bucket Set |
|---------|-----------|
| `*ttft*` | LLM latency (0.1s - 120s) |
| `*tpot*` | Per-token latency (5ms - 500ms) |
| `*duration*seconds*` | LLM latency (0.1s - 120s) |
| `*tokens*` | Token counts (1 - 128K) |

Any histogram matching these patterns gets the optimized buckets automatically.

## Docker Infrastructure

The `docker/` directory contains a production-ready observability stack:

```bash
cd docker
cp .env.example .env   # Set passwords
docker compose up -d
```

| Service | Port | Purpose |
|---------|------|---------|
| Phoenix | `:6006` | LLM trace visualization UI |
| Phoenix DB | internal | PostgreSQL backend for traces |
| Prometheus | `:9090` | Metrics scraping and storage |
| Grafana | `:3001` | Dashboards and alerting |

### Prometheus Configuration

`docker/prometheus.yml` — scrape config for your services:

```yaml
scrape_configs:
  - job_name: "my-service"
    metrics_path: /metrics
    static_configs:
      - targets: ["host.docker.internal:8000"]
```

### Grafana Dashboards

Pre-built dashboards in `docker/grafana/dashboards/`:
- **Service Overview** — Request rates, error rates, latency percentiles
- **Analytics Deep Dive** — LLM-specific metrics, token usage, inference latency

## Optional Extras

| Extra | Install | What it adds |
|-------|---------|-------------|
| `redis` | `pip install "obsx[redis]"` | Redis command tracing (GET, SET, etc.) |
| `sqlalchemy` | `pip install "obsx[sqlalchemy]"` | SQL query tracing with statement capture |
| `logging` | `pip install "obsx[logging]"` | `trace_id` and `span_id` injected into Python log records |
| `all` | `pip install "obsx[all]"` | Everything above |

All optional instrumentations degrade gracefully — if the package isn't installed, the instrumentation is silently skipped.

## API Reference

### Functions

| Function | Description |
|----------|-------------|
| `init_observability(...)` | Configure OTEL providers and auto-instrumentation |
| `shutdown()` | Flush spans/metrics, call at service shutdown |
| `metrics_router(path="/metrics")` | FastAPI router for Prometheus scraping |
| `get_meter(name)` | Get an OTEL Meter for creating instruments |
| `get_tracer(name)` | Get an OTEL Tracer for creating spans |
| `create_counter(meter, name, ...)` | Create a monotonic counter |
| `create_histogram(meter, name, ...)` | Create a histogram (default buckets) |
| `create_histogram_llm(meter, name, ...)` | Create a histogram (LLM latency buckets) |
| `create_histogram_tokens(meter, name, ...)` | Create a histogram (token count buckets) |
| `create_up_down_counter(meter, name, ...)` | Create a gauge-like up/down counter |
| `llm_metric_views()` | Get OTEL Views for LLM histogram buckets |

### Classes

| Class | Description |
|-------|-------------|
| `RequestMetricsMiddleware` | FastAPI middleware for request counting + duration |

### Constants

| Constant | Value |
|----------|-------|
| `LATENCY_BUCKETS_DEFAULT` | `(0.005, 0.01, 0.025, ..., 10.0)` |
| `LATENCY_BUCKETS_LLM` | `(0.1, 0.25, 0.5, ..., 120.0)` |
| `TOKEN_COUNT_BUCKETS` | `(1, 10, 50, ..., 128000)` |

## License

Apache 2.0
