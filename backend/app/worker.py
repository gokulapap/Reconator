import logging
import os
import signal
import socket
import sys
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.models import Target, TargetStatus
from app.db.session import SessionLocal
from app.recon.modules.builtin import register_builtin_modules
from app.recon.modules.registry import registry
from app.recon.orchestration import TaskScheduler
from app.services.scanner import run_scan

log = logging.getLogger(__name__)
_shutdown = False


def _handle_signal(signum, _frame) -> None:
    global _shutdown
    log.info("worker received signal=%s — shutting down after current job", signum)
    _shutdown = True


def _claim_next() -> Target | None:
    with SessionLocal() as db:
        target = db.scalar(
            select(Target)
            .where(Target.status == TargetStatus.queued)
            .order_by(Target.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if target is None:
            return None
        target.status = TargetStatus.running
        db.commit()
        db.refresh(target)
        return target


def _process(target_id: int) -> None:
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            log.warning("target id=%s vanished", target_id)
            return
        try:
            run_scan(db, target)
        except Exception as exc:
            log.exception("scan failed target_id=%s", target_id)
            target.status = TargetStatus.failed
            target.error = repr(exc)[:1000]
            db.commit()


def _claim_task(worker_id: str) -> int | None:
    with SessionLocal() as db:
        task = TaskScheduler(db).claim_next(worker_id)
        return task.id if task else None


def _process_task(task_id: int, worker_id: str) -> None:
    with SessionLocal() as db:
        TaskScheduler(db).execute_claimed(task_id, worker_id)


def _task_worker_loop() -> None:
    register_builtin_modules()
    registry.load_entry_points()
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    concurrency = max(1, settings.max_concurrent_tasks)
    log.info("task worker starting id=%s concurrency=%s", worker_id, concurrency)
    futures: set[Future[None]] = set()
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="recon-task") as executor:
        while not _shutdown:
            completed = {future for future in futures if future.done()}
            for future in completed:
                futures.remove(future)
                try:
                    future.result()
                except Exception:
                    log.exception("task execution thread crashed")

            claimed = False
            while len(futures) < concurrency and not _shutdown:
                try:
                    task_id = _claim_task(worker_id)
                except Exception:
                    log.exception("task claim failed; worker will retry after backoff")
                    break
                if task_id is None:
                    break
                futures.add(executor.submit(_process_task, task_id, worker_id))
                claimed = True

            if not claimed:
                deadline = time.monotonic() + settings.worker_poll_interval_seconds
                while not _shutdown and time.monotonic() < deadline:
                    if any(future.done() for future in futures):
                        break
                    time.sleep(0.25)

        if futures:
            log.info("waiting for %s in-flight task(s)", len(futures))
    log.info("task worker stopped id=%s", worker_id)


def main() -> None:
    configure_logging()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("worker starting poll_interval=%ss", settings.worker_poll_interval_seconds)

    if settings.recon_engine_enabled:
        _task_worker_loop()
        return

    while not _shutdown:
        target = _claim_next()
        if target is None:
            for _ in range(settings.worker_poll_interval_seconds):
                if _shutdown:
                    break
                time.sleep(1)
            continue

        log.info("processing target_id=%s url=%s", target.id, target.url)
        _process(target.id)

    log.info("worker stopped")


if __name__ == "__main__":
    sys.exit(main())
