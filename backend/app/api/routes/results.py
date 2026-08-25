import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.auth import require_read_api_key
from app.db.models import ScanResult, Target
from app.schemas.target import ScanResultRead

router = APIRouter(
    prefix="/targets/{target_id}/results",
    tags=["results"],
    dependencies=[Depends(require_read_api_key)],
)


def _load(db: Session, target_id: int, module: str) -> ScanResult:
    result = db.scalar(
        select(ScanResult).where(ScanResult.target_id == target_id, ScanResult.module == module)
    )
    if result is None:
        raise HTTPException(status_code=404, detail="result not found")
    return result


@router.get("", response_model=list[ScanResultRead])
def list_results(target_id: int, db: Session = Depends(db_session)) -> list[ScanResultRead]:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    return [ScanResultRead.model_validate(r) for r in target.results]


@router.get("/{module}", response_model=ScanResultRead)
def get_result(target_id: int, module: str, db: Session = Depends(db_session)) -> ScanResultRead:
    return ScanResultRead.model_validate(_load(db, target_id, module))


@router.get("/{module}/download", response_class=PlainTextResponse)
def download_result(target_id: int, module: str, db: Session = Depends(db_session)) -> Response:
    result = _load(db, target_id, module)
    target = db.get(Target, target_id)
    raw_filename = f"{target.url if target else target_id}-{module}.txt"
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", raw_filename)[:180] or "reconator-result.txt"
    return Response(
        content=result.output or "",
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
