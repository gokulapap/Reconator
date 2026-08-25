import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import scan_duration_seconds, scans_total
from app.db.models import ModuleStatus, ScanResult, Target, TargetStatus
from app.recon.modules.command import run_bounded_command
from app.services.modules import MODULES, ModuleSpec, get_module
from app.services.notifier import notifier

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _run_module(spec: ModuleSpec, url: str, cwd: str) -> tuple[ModuleStatus, str, str]:
    argv = [part.replace("{url}", url) for part in spec.argv]
    log.info("module_start", extra={"module": spec.name, "url": url})
    try:
        returncode, stdout, stderr, stdout_truncated, stderr_truncated = run_bounded_command(
            argv,
            cwd=cwd,
            env={
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                # Legacy tools must not inherit access paths to operator home
                # credentials when this compatibility mode runs outside Docker.
                "HOME": "/tmp",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_COLOR": "1",
                "TARGET": url,
            },
            timeout=spec.timeout,
            max_output_bytes=settings.max_raw_output_bytes,
        )
        output = stdout.decode("utf-8", errors="replace")
        decoded_stderr = stderr.decode("utf-8", errors="replace")
        if decoded_stderr.strip():
            output += f"\n[stderr]\n{decoded_stderr}"
        if stdout_truncated or stderr_truncated:
            output += "\n[reconator] output truncated by safety limit"
        if returncode == 0:
            return ModuleStatus.completed, output, ""
        return ModuleStatus.failed, output, f"exit_code={returncode}"
    except TimeoutError:
        return ModuleStatus.failed, "", f"timeout after {spec.timeout}s"
    except Exception as exc:
        return ModuleStatus.failed, "", repr(exc)


def _read_legacy_output(url: str) -> str | None:
    path = Path(settings.results_dir) / f"{url}-output.txt"
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, errors="replace") as handle:
            return handle.read(settings.max_raw_output_bytes + 1)[: settings.max_raw_output_bytes]
    except (OSError, ValueError):
        return None


def _modules_for(target: Target) -> list[ModuleSpec]:
    if not target.selected_modules:
        return MODULES
    chosen: list[ModuleSpec] = []
    for name in target.selected_modules:
        spec = get_module(name)
        if spec:
            chosen.append(spec)
    return chosen or MODULES


def _refresh_cancel(db: Session, target_id: int) -> bool:
    db.expire_all()
    fresh = db.get(Target, target_id)
    return bool(fresh and fresh.cancel_requested)


def run_scan(db: Session, target: Target) -> None:
    if target.target_kind != "domain":
        raise ValueError("the deprecated legacy worker accepts domain targets only")
    started = time.perf_counter()
    target.status = TargetStatus.running
    target.started_at = _now()
    target.error = None
    db.commit()

    notifier.send(f"Recon started for {target.url}")

    cwd = str(Path(settings.modules_dir).parent)
    Path(settings.results_dir).mkdir(parents=True, exist_ok=True)

    failed_modules: list[str] = []
    cancelled = False

    for spec in _modules_for(target):
        if _refresh_cancel(db, target.id):
            cancelled = True
            break

        result = (
            db.query(ScanResult)
            .filter(ScanResult.target_id == target.id, ScanResult.module == spec.name)
            .one_or_none()
        )
        if result is None:
            result = ScanResult(target_id=target.id, module=spec.name)
            db.add(result)

        result.status = ModuleStatus.running
        result.started_at = _now()
        result.error = None
        db.commit()

        status, output, error = _run_module(spec, target.url, cwd)

        result.status = status
        result.output = output or None
        result.error = error or None
        result.completed_at = _now()
        db.commit()

        if status == ModuleStatus.failed:
            failed_modules.append(spec.name)

    legacy = _read_legacy_output(target.url)
    if legacy:
        summary = (
            db.query(ScanResult)
            .filter(ScanResult.target_id == target.id, ScanResult.module == "summary")
            .one_or_none()
        )
        if summary is None:
            summary = ScanResult(target_id=target.id, module="summary")
            db.add(summary)
        summary.status = ModuleStatus.completed
        summary.output = legacy
        summary.started_at = summary.started_at or _now()
        summary.completed_at = _now()
        db.commit()

    target.completed_at = _now()
    if cancelled:
        target.status = TargetStatus.cancelled
        target.error = "cancelled by user"
    elif failed_modules and len(failed_modules) == len(_modules_for(target)):
        target.status = TargetStatus.failed
        target.error = "all modules failed"
    else:
        target.status = TargetStatus.completed
        if failed_modules:
            target.error = f"partial failure: {', '.join(failed_modules)}"
    db.commit()

    scans_total.labels(status=target.status.value).inc()
    scan_duration_seconds.observe(time.perf_counter() - started)

    if target.status == TargetStatus.completed:
        msg = f"Recon for {target.url} completed"
    elif target.status == TargetStatus.cancelled:
        msg = f"Recon for {target.url} was cancelled"
    else:
        msg = f"Recon for {target.url} failed: {target.error}"
    notifier.send(msg)
