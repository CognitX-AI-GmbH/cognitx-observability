"""
Optional request-level middleware for services that want additional metric recording
beyond what OTEL's FastAPI auto-instrumentation provides.

OTEL FastAPI instrumentation already records:
  - http.server.duration (histogram)
  - http.server.request.size / response.size

This middleware adds service-level metrics:
  - http.requests_total (counter with method, endpoint, status labels)
  - http.errors_total (counter for 4xx/5xx)
  - http.request_duration_seconds (histogram)
  - http.active_requests (up-down counter / gauge)

It also links X-Request-ID to the active OTEL span for cross-service trace correlation.
"""

from __future__ import annotations

import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from ._metrics import get_meter

_SKIP_PATHS = frozenset(
    {
        "/health-check",
        "/healthz",
        "/ready",
        "/live",
        "/metrics",
        "/favicon.ico",
        "/health/live",
        "/health/ready",
    }
)


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """Middleware that records per-request counters, propagates request IDs,
    and links request context to active OTEL trace spans.

    Args:
        app: ASGI application.
        service_name: Service name for meter scoping.
        known_routes: Optional list of route prefixes for path normalization.
            Prevents Prometheus label cardinality explosion by collapsing
            paths like "/v1/models/gpt-4o" to "/v1/models".
            If not provided, raw request paths are used (fine for low-traffic services).
    """

    def __init__(
        self,
        app,  # type: ignore[no-untyped-def]
        service_name: str = "app",
        known_routes: list[str] | None = None,
    ):
        super().__init__(app)
        self._known_routes = known_routes
        meter = get_meter(f"{service_name}.http")
        self._requests_total = meter.create_counter(
            "http.requests_total",
            description="Total HTTP requests",
        )
        self._errors_total = meter.create_counter(
            "http.errors_total",
            description="Total HTTP error responses (4xx + 5xx)",
        )
        self._duration = meter.create_histogram(
            "http.request_duration_seconds",
            description="HTTP request duration in seconds",
            unit="s",
        )
        self._active = meter.create_up_down_counter(
            "http.active_requests",
            description="Currently in-flight requests",
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # Propagate or generate request ID
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Normalize path to prevent label cardinality explosion
        route = self._normalize_path(request.url.path)

        # Link request ID to active OTEL span (for cross-service correlation)
        try:
            from opentelemetry import trace as _trace

            span = _trace.get_current_span()
            if span.is_recording():
                span.set_attribute("request.id", request_id)
                span.set_attribute("http.route", request.url.path)
        except Exception:
            pass

        route_attrs = {"http.method": request.method, "http.route": route}
        self._active.add(1, route_attrs)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            raise
        finally:
            self._active.add(-1, route_attrs)
            duration = time.perf_counter() - start
            attrs = {**route_attrs, "http.status_code": str(status_code)}
            self._requests_total.add(1, attrs)
            self._duration.record(duration, attrs)
            if status_code >= 400:
                self._errors_total.add(1, attrs)

    def _normalize_path(self, path: str) -> str:
        """Collapse dynamic path segments to known prefixes."""
        if self._known_routes is None:
            return path
        for prefix in self._known_routes:
            if path.startswith(prefix):
                return prefix
        return "other"
