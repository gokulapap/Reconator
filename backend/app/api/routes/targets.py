import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import String, cast, func, select, text
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.auth import require_api_key, require_read_api_key
from app.core.config import settings
from app.core.limiter import limiter
from app.db.models import Target, TargetStatus
from app.recon.modules.builtin import register_builtin_modules
from app.recon.modules.registry import registry
from app.recon.orchestration import TaskScheduler
from app.schemas.target import (
    StatsResponse,
    TargetBulkCreate,
    TargetBulkResult,
    TargetCreate,
    TargetDetail,
    TargetList,
    TargetRead,
    _normalise_target,
)

router = APIRouter(
    prefix="/targets",
    tags=["targets"],
    dependencies=[Depends(require_read_api_key)],
)


def _lock_target_identity(db: Session, target_kind: str, value: str) -> None:
    """Serialize active-target checks for one root in PostgreSQL."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": f"{target_kind}:{value}"},
        )


def _active_target(db: Session, target_kind: str, value: str) -> Target | None:
    _lock_target_identity(db, target_kind, value)
    return db.scalar(
        select(Target).where(
            Target.url == value,
            Target.target_kind == target_kind,
            Target.status.in_([TargetStatus.queued, TargetStatus.running]),
        )
    )


def _csv_cell(value: object) -> str:
    text_value = str(value or "").replace("\r", " ").replace("\n", " ")
    return f"'{text_value}" if text_value.startswith(("=", "+", "-", "@")) else text_value


def _validate_scan_request(
    *, authorization_confirmed: bool, selected_modules: list[str] | None
) -> None:
    if settings.require_authorization_confirmation and not authorization_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="explicit authorization confirmation is required before reconnaissance",
        )
    if selected_modules:
        register_builtin_modules()
        known_names = {module.manifest.name for module in registry.all()}
        known_capabilities = {module.manifest.capability for module in registry.all()}
        unknown = sorted(set(selected_modules) - known_names - known_capabilities)
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"unknown modules or capabilities: {', '.join(unknown)}",
            )


@router.post(
    "",
    response_model=TargetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(settings.rate_limit_writes)
def create_target(
    request: Request,
    payload: TargetCreate,
    db: Session = Depends(db_session),
) -> TargetRead:
    _validate_scan_request(
        authorization_confirmed=payload.authorization_confirmed,
        selected_modules=payload.selected_modules,
    )
    existing = _active_target(db, payload.target_kind, payload.url)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"target already {existing.status.value} (id={existing.id})",
        )
    target = Target(
        url=payload.url,
        target_kind=payload.target_kind,
        status=TargetStatus.queued,
        tags=payload.tags,
        selected_modules=payload.selected_modules,
        notes=payload.notes,
        profile=payload.profile,
        scan_config=payload.scan_config,
        authorization_confirmed=payload.authorization_confirmed,
    )
    db.add(target)
    db.flush()
    if settings.recon_engine_enabled:
        TaskScheduler(db).bootstrap(target)
    db.commit()
    db.refresh(target)
    return TargetRead.model_validate(target)


@router.post(
    "/bulk",
    response_model=TargetBulkResult,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit(settings.rate_limit_bulk)
def bulk_create(
    request: Request,
    payload: TargetBulkCreate,
    db: Session = Depends(db_session),
) -> TargetBulkResult:
    _validate_scan_request(
        authorization_confirmed=payload.authorization_confirmed,
        selected_modules=payload.selected_modules,
    )
    created: list[int] = []
    conflicts: list[str] = []
    errors: dict[str, str] = {}

    for raw in payload.urls:
        try:
            url = _normalise_target(raw, payload.target_kind)
        except ValueError as exc:
            errors[raw] = str(exc)
            continue
        existing = _active_target(db, payload.target_kind, url)
        if existing:
            conflicts.append(url)
            continue
        target = Target(
            url=url,
            target_kind=payload.target_kind,
            status=TargetStatus.queued,
            tags=sorted({t.lower() for t in payload.tags}),
            selected_modules=payload.selected_modules,
            profile=payload.profile,
            scan_config=payload.scan_config,
            authorization_confirmed=payload.authorization_confirmed,
        )
        db.add(target)
        db.flush()
        if settings.recon_engine_enabled:
            TaskScheduler(db).bootstrap(target)
        created.append(target.id)
    db.commit()
    return TargetBulkResult(created=created, conflicts=conflicts, errors=errors)


@router.get("", response_model=TargetList)
def list_targets(
    db: Session = Depends(db_session),
    status_filter: TargetStatus | None = Query(None, alias="status"),
    search: str | None = None,
    tag: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> TargetList:
    stmt = select(Target).order_by(Target.created_at.desc())
    count_stmt = select(func.count()).select_from(Target)

    if status_filter:
        stmt = stmt.where(Target.status == status_filter)
        count_stmt = count_stmt.where(Target.status == status_filter)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(func.lower(Target.url).like(like))
        count_stmt = count_stmt.where(func.lower(Target.url).like(like))
    if tag:
        wanted = tag.lower().strip()
        if not wanted or len(wanted) > 32:
            raise HTTPException(status_code=422, detail="invalid tag filter")
        escaped = wanted.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        tag_condition = cast(Target.tags, String).like(f'%"{escaped}"%', escape="\\")
        stmt = stmt.where(tag_condition)
        count_stmt = count_stmt.where(tag_condition)

    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    total = db.scalar(count_stmt) or 0
    return TargetList(
        items=[TargetRead.model_validate(t) for t in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=StatsResponse)
def stats(db: Session = Depends(db_session)) -> StatsResponse:
    rows = db.execute(select(Target.status, func.count()).group_by(Target.status)).all()
    counts = {s.value: 0 for s in TargetStatus}
    for s, c in rows:
        counts[s.value if hasattr(s, "value") else s] = c

    avg_seconds: float | None = None
    durations = db.execute(
        select(Target.started_at, Target.completed_at).where(
            Target.status == TargetStatus.completed,
            Target.started_at.isnot(None),
            Target.completed_at.isnot(None),
        )
    ).all()
    if durations:
        total_seconds = sum((c - s).total_seconds() for s, c in durations if s and c)
        avg_seconds = round(total_seconds / len(durations), 2)

    return StatsResponse(
        queued=counts.get("queued", 0),
        running=counts.get("running", 0),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        cancelled=counts.get("cancelled", 0),
        total=sum(counts.values()),
        avg_duration_seconds=avg_seconds,
    )


@router.get("/export")
def export_targets(
    db: Session = Depends(db_session),
    format: str = Query("csv", pattern="^(csv|json)$"),
    status_filter: TargetStatus | None = Query(None, alias="status"),
) -> Response:
    stmt = select(Target).order_by(Target.created_at.desc())
    if status_filter:
        stmt = stmt.where(Target.status == status_filter)
    rows = db.scalars(stmt).all()

    if format == "json":
        payload = [
            {
                "id": t.id,
                "url": t.url,
                "status": t.status.value,
                "tags": t.tags or [],
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "error": t.error,
            }
            for t in rows
        ]
        return Response(
            content=json.dumps(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="targets.json"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "url", "status", "tags", "created_at", "completed_at", "error"])
    for t in rows:
        writer.writerow(
            [
                t.id,
                _csv_cell(t.url),
                t.status.value,
                _csv_cell("|".join(t.tags or [])),
                t.created_at.isoformat() if t.created_at else "",
                t.completed_at.isoformat() if t.completed_at else "",
                _csv_cell(t.error),
            ]
        )
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="targets.csv"'},
    )


@router.get("/{target_id}", response_model=TargetDetail)
def get_target(target_id: int, db: Session = Depends(db_session)) -> TargetDetail:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    detail = TargetDetail.model_validate(target)
    detail.results = [
        {
            "module": r.module,
            "status": r.status,
            "completed_at": r.completed_at,
            "has_output": bool(r.output),
        }
        for r in target.results
    ]
    return detail


@router.delete(
    "/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
)
def delete_target(target_id: int, db: Session = Depends(db_session)) -> None:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    if target.status == TargetStatus.running:
        if settings.recon_engine_enabled:
            TaskScheduler(db).cancel_pending(target)
        else:
            target.cancel_requested = True
        db.commit()
        return
    db.delete(target)
    db.commit()


@router.post(
    "/{target_id}/cancel",
    response_model=TargetRead,
    dependencies=[Depends(require_api_key)],
)
def cancel_target(target_id: int, db: Session = Depends(db_session)) -> TargetRead:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    if target.status in {TargetStatus.running, TargetStatus.queued}:
        if settings.recon_engine_enabled:
            TaskScheduler(db).cancel_pending(target)
        else:
            target.cancel_requested = True
            target.status = TargetStatus.cancelled
    else:
        raise HTTPException(
            status_code=409,
            detail=f"cannot cancel a {target.status.value} target",
        )
    db.commit()
    db.refresh(target)
    return TargetRead.model_validate(target)


@router.post(
    "/{target_id}/rescan",
    response_model=TargetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def rescan_target(target_id: int, db: Session = Depends(db_session)) -> TargetRead:
    src = db.get(Target, target_id)
    if src is None:
        raise HTTPException(status_code=404, detail="target not found")
    if src.status in {TargetStatus.queued, TargetStatus.running}:
        raise HTTPException(status_code=409, detail="cannot rescan an unfinished target")
    existing = _active_target(db, src.target_kind, src.url)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"target already {existing.status.value} (id={existing.id})",
        )
    new = Target(
        url=src.url,
        target_kind=src.target_kind,
        status=TargetStatus.queued,
        tags=list(src.tags or []),
        selected_modules=list(src.selected_modules) if src.selected_modules else None,
        notes=src.notes,
        profile=src.profile,
        scan_config=dict(src.scan_config or {}),
        authorization_confirmed=src.authorization_confirmed,
        parent_target_id=src.id,
    )
    db.add(new)
    db.flush()
    if settings.recon_engine_enabled:
        TaskScheduler(db).bootstrap(new)
    db.commit()
    db.refresh(new)
    return TargetRead.model_validate(new)
