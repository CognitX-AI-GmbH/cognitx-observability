# obsx

Plug-and-play observability for Python services. One `init_observability()` call configures OpenTelemetry tracing (Phoenix or OTLP), Prometheus metrics, and auto-instrumentation for FastAPI, httpx, and OpenAI SDK.

## Install

```bash
# Core (Phoenix + Prometheus + OpenAI instrumentation)
pip install obsx

# With Redis + SQLAlchemy instrumentation
pip install obsx[all]

# From git
pip install "obsx @ git+https://github.com/CognitX-AI-GmbH/cognitx-observability.git"
```

## Usage

```python
from obsx import init_observability, metrics_router, shutdown

# Initialize at startup
init_observability(
    service_name="my-service",
    environment="production",
    phoenix_enabled=True,
    phoenix_endpoint="http://phoenix:4317",
    trace_sample_rate=0.5,
)

# Mount Prometheus /metrics endpoint
app = FastAPI()
app.include_router(metrics_router())

# Shutdown gracefully
await shutdown()
```

## Features

| Feature | Default | Optional Extra |
|---------|---------|---------------|
| Prometheus metrics + `/metrics` endpoint | Yes | - |
| Phoenix OTEL tracing (LLM spans) | Yes | - |
| OpenAI SDK instrumentation (OpenInference) | Yes | - |
| FastAPI auto-instrumentation | Yes | - |
| httpx auto-instrumentation | Yes | - |
| Redis instrumentation | No | `pip install .[redis]` |
| SQLAlchemy instrumentation | No | `pip install .[sqlalchemy]` |
| Log-trace correlation | No | `pip install .[logging]` |
| LLM-tuned histogram buckets | Yes | - |
| W3C Trace Context propagation | Yes | - |
| `RequestMetricsMiddleware` | Yes | - |

## Metrics

```python
from obsx import get_meter, create_histogram_llm, create_histogram_tokens

meter = get_meter("my-service")
ttft = create_histogram_llm(meter, "inference.ttft_seconds", "Time to first token")
tokens = create_histogram_tokens(meter, "inference.output_tokens", "Output token count")
```

## Docker Infrastructure

The `docker/` directory contains a ready-to-use observability stack:

```bash
cd docker && docker compose up -d
```

- **Phoenix** - LLM tracing UI (`:6006`)
- **Prometheus** - Metrics scraping (`:9090`)
- **Grafana** - Dashboards (`:3001`)

## License

Apache 2.0
