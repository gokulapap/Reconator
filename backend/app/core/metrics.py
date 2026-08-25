import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

http_requests_total = Counter(
    "reconator_http_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "reconator_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
scans_total = Counter(
    "reconator_scans_total",
    "Recon scans by terminal status",
    ["status"],
)
scan_duration_seconds = Histogram(
    "reconator_scan_duration_seconds",
    "End-to-end scan duration",
)
queue_depth = Gauge(
    "reconator_queue_depth",
    "Number of targets currently in queued state",
)
task_queue_depth = Gauge(
    "reconator_task_queue_depth",
    "Number of recon tasks waiting for execution",
)
active_tasks = Gauge(
    "reconator_active_tasks",
    "Number of leased recon tasks currently executing",
)
target_records = Gauge(
    "reconator_target_records",
    "Durable scan records by current status",
    ["status"],
)
task_records = Gauge(
    "reconator_task_records",
    "Durable recon task records by current status",
    ["status"],
)
tasks_total = Counter(
    "reconator_tasks_total",
    "Recon task terminal outcomes",
    ["module", "status"],
)
task_duration_seconds = Histogram(
    "reconator_task_duration_seconds",
    "Recon module task execution duration",
    ["module"],
)
assets_observed_total = Counter(
    "reconator_assets_observed_total",
    "Canonical asset observations",
    ["new_globally"],
)
relationships_observed_total = Counter(
    "reconator_relationships_observed_total",
    "Asset relationship observations",
)
task_cache_hits_total = Counter(
    "reconator_task_cache_hits_total",
    "Recon tasks satisfied by reusable cached knowledge",
    ["module"],
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed = time.perf_counter() - start
        # Use route template if available so labels stay low-cardinality.
        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path
        http_requests_total.labels(
            method=request.method, path=path, status=str(response.status_code)
        ).inc()
        http_request_duration_seconds.labels(method=request.method, path=path).observe(elapsed)
        return response


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
