import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, text

from app.core.auth import require_read_api_key
from app.core.metrics import (
    active_tasks,
    metrics_response,
    queue_depth,
    target_records,
    task_queue_depth,
    task_records,
)
from app.db.models import ReconTask, Target, TargetStatus, TaskStatus
from app.db.session import SessionLocal, engine

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=None)
def ready() -> dict[str, str] | JSONResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return {"status": "ready"}
    except Exception:
        logger.exception("Readiness database check failed")
        return JSONResponse(status_code=503, content={"status": "degraded"})


@router.get(
    "/metrics",
    include_in_schema=False,
    dependencies=[Depends(require_read_api_key)],
)
def metrics():
    try:
        with SessionLocal() as db:
            target_counts = {
                (status.value if hasattr(status, "value") else status): count
                for status, count in db.query(Target.status, func.count()).group_by(Target.status)
            }
            task_counts = dict(db.query(ReconTask.status, func.count()).group_by(ReconTask.status))
            for status in TargetStatus:
                target_records.labels(status=status.value).set(target_counts.get(status.value, 0))
            for status in TaskStatus:
                task_records.labels(status=status.value).set(task_counts.get(status.value, 0))
            queue_depth.set(target_counts.get(TargetStatus.queued.value, 0))
            task_depth = sum(
                task_counts.get(status.value, 0)
                for status in (TaskStatus.queued, TaskStatus.retry_wait, TaskStatus.blocked)
            )
            task_queue_depth.set(task_depth)
            # Worker containers have separate process memory; derive this gauge
            # from the shared queue so the API metrics endpoint is authoritative.
            active_tasks.set(task_counts.get(TaskStatus.running.value, 0))
    except Exception:
        logger.exception("Unable to refresh database-backed metrics")
    return metrics_response()
