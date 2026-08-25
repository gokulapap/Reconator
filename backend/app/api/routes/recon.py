from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.auth import require_api_key, require_read_api_key
from app.db.models import (
    Asset,
    AssetObservation,
    AssetRelationship,
    ReconEvent,
    ReconTask,
    RelationshipObservation,
    ScopeRule,
    Target,
)
from app.recon.orchestration import TaskScheduler
from app.recon.scope import ScopeConfigurationError, normalize_rule_pattern
from app.schemas.recon import (
    AssetIntelligence,
    AssetList,
    AssetObservationRead,
    AssetRead,
    AssetRelationshipContext,
    EventRead,
    GraphResponse,
    KnowledgeStats,
    RelationshipRead,
    ScanComparison,
    ScanKnowledgeSummary,
    ScopeRuleCreate,
    ScopeRuleRead,
    TaskDetail,
    TaskList,
    TaskRead,
)

router = APIRouter(tags=["recon-knowledge"], dependencies=[Depends(require_read_api_key)])


def _target_or_404(db: Session, target_id: int) -> Target:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    return target


def _scan_asset_ids(target_id: int):
    return select(AssetObservation.asset_id).where(AssetObservation.target_id == target_id)


@router.get("/targets/{target_id}/assets", response_model=AssetList)
def list_scan_assets(
    target_id: int,
    db: Session = Depends(db_session),
    kind: str | None = None,
    min_priority: float = Query(0, ge=0),
    search: str | None = Query(default=None, max_length=256),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> AssetList:
    _target_or_404(db, target_id)
    scan_ids = _scan_asset_ids(target_id)
    statement = select(Asset).where(Asset.id.in_(scan_ids), Asset.priority_score >= min_priority)
    count_statement = (
        select(func.count())
        .select_from(Asset)
        .where(Asset.id.in_(scan_ids), Asset.priority_score >= min_priority)
    )
    if kind:
        statement = statement.where(Asset.kind == kind)
        count_statement = count_statement.where(Asset.kind == kind)
    if search:
        pattern = f"%{search.lower()}%"
        statement = statement.where(func.lower(Asset.canonical_value).like(pattern))
        count_statement = count_statement.where(func.lower(Asset.canonical_value).like(pattern))
    statement = statement.order_by(Asset.priority_score.desc(), Asset.last_seen_at.desc(), Asset.id)
    items = list(db.scalars(statement.offset((page - 1) * page_size).limit(page_size)))
    total = int(db.scalar(count_statement) or 0)
    return AssetList(
        items=[AssetRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def _relationship_read(relationship: AssetRelationship) -> RelationshipRead:
    return RelationshipRead(
        id=relationship.id,
        source_asset_id=relationship.source_asset_id,
        target_asset_id=relationship.target_asset_id,
        relationship_type=relationship.relationship_type,
        attributes=relationship.attributes or {},
        confidence=relationship.confidence,
        first_seen_at=relationship.first_seen_at,
        last_seen_at=relationship.last_seen_at,
    )


@router.get(
    "/targets/{target_id}/assets/{asset_id}",
    response_model=AssetIntelligence,
)
def get_scan_asset_intelligence(
    target_id: int,
    asset_id: int,
    db: Session = Depends(db_session),
    observation_limit: int = Query(200, ge=1, le=500),
    relationship_limit: int = Query(200, ge=1, le=500),
) -> AssetIntelligence:
    _target_or_404(db, target_id)
    asset = db.scalar(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.id.in_(_scan_asset_ids(target_id)),
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not observed in this scan")

    observations = list(
        db.scalars(
            select(AssetObservation)
            .where(
                AssetObservation.target_id == target_id,
                AssetObservation.asset_id == asset_id,
            )
            .order_by(
                AssetObservation.last_observed_at.desc(),
                AssetObservation.id.desc(),
            )
            .limit(observation_limit + 1)
        )
    )
    observations_truncated = len(observations) > observation_limit
    observations = observations[:observation_limit]

    observed_relationship_ids = (
        select(RelationshipObservation.relationship_id)
        .where(RelationshipObservation.target_id == target_id)
        .distinct()
    )
    relationships = list(
        db.scalars(
            select(AssetRelationship)
            .where(
                AssetRelationship.id.in_(observed_relationship_ids),
                or_(
                    AssetRelationship.source_asset_id == asset_id,
                    AssetRelationship.target_asset_id == asset_id,
                ),
            )
            .order_by(AssetRelationship.last_seen_at.desc(), AssetRelationship.id)
            .limit(relationship_limit + 1)
        )
    )
    relationships_truncated = len(relationships) > relationship_limit
    relationships = relationships[:relationship_limit]
    contexts: list[AssetRelationshipContext] = []
    for relationship in relationships:
        outgoing = relationship.source_asset_id == asset_id
        related = relationship.target_asset if outgoing else relationship.source_asset
        contexts.append(
            AssetRelationshipContext(
                relationship=_relationship_read(relationship),
                direction="outgoing" if outgoing else "incoming",
                related_asset=AssetRead.model_validate(related),
            )
        )
    return AssetIntelligence(
        asset=AssetRead.model_validate(asset),
        observations=[AssetObservationRead.model_validate(item) for item in observations],
        relationships=contexts,
        observations_truncated=observations_truncated,
        relationships_truncated=relationships_truncated,
    )


@router.get(
    "/targets/{target_id}/knowledge-summary",
    response_model=ScanKnowledgeSummary,
)
def scan_knowledge_summary(
    target_id: int, db: Session = Depends(db_session)
) -> ScanKnowledgeSummary:
    _target_or_404(db, target_id)
    asset_rows = db.execute(
        select(Asset.kind, func.count(func.distinct(Asset.id)))
        .join(AssetObservation, AssetObservation.asset_id == Asset.id)
        .where(AssetObservation.target_id == target_id)
        .group_by(Asset.kind)
    ).all()
    relationship_rows = db.execute(
        select(
            AssetRelationship.relationship_type,
            func.count(func.distinct(AssetRelationship.id)),
        )
        .join(
            RelationshipObservation,
            RelationshipObservation.relationship_id == AssetRelationship.id,
        )
        .where(RelationshipObservation.target_id == target_id)
        .group_by(AssetRelationship.relationship_type)
    ).all()
    task_rows = db.execute(
        select(ReconTask.status, func.count())
        .where(ReconTask.target_id == target_id)
        .group_by(ReconTask.status)
    ).all()
    module_rows = db.execute(
        select(AssetObservation.source_module, func.count())
        .where(AssetObservation.target_id == target_id)
        .group_by(AssetObservation.source_module)
    ).all()
    assets_by_kind = {kind: int(count) for kind, count in asset_rows}
    relationships_by_type = {
        relationship_type: int(count) for relationship_type, count in relationship_rows
    }
    tasks_by_status = {task_status: int(count) for task_status, count in task_rows}
    observations_by_module = {source_module: int(count) for source_module, count in module_rows}
    return ScanKnowledgeSummary(
        assets_total=sum(assets_by_kind.values()),
        relationships_total=sum(relationships_by_type.values()),
        observations_total=sum(observations_by_module.values()),
        tasks_total=sum(tasks_by_status.values()),
        assets_by_kind=assets_by_kind,
        relationships_by_type=relationships_by_type,
        tasks_by_status=tasks_by_status,
        observations_by_module=observations_by_module,
    )


@router.get("/targets/{target_id}/graph", response_model=GraphResponse)
def get_scan_graph(
    target_id: int,
    db: Session = Depends(db_session),
    limit: int = Query(1000, ge=1, le=5000),
) -> GraphResponse:
    _target_or_404(db, target_id)
    node_ids = list(
        db.scalars(
            select(AssetObservation.asset_id)
            .where(AssetObservation.target_id == target_id)
            .distinct()
            .limit(limit + 1)
        )
    )
    truncated = len(node_ids) > limit
    node_ids = node_ids[:limit]
    nodes = list(db.scalars(select(Asset).where(Asset.id.in_(node_ids)))) if node_ids else []
    relationship_ids = select(RelationshipObservation.relationship_id).where(
        RelationshipObservation.target_id == target_id
    )
    edge_limit = min(limit * 5, 20_000)
    edges = []
    if node_ids:
        edges = list(
            db.scalars(
                select(AssetRelationship)
                .where(
                    AssetRelationship.id.in_(relationship_ids),
                    AssetRelationship.source_asset_id.in_(node_ids),
                    AssetRelationship.target_asset_id.in_(node_ids),
                )
                .order_by(AssetRelationship.id)
                .limit(edge_limit + 1)
            )
        )
        if len(edges) > edge_limit:
            truncated = True
            edges = edges[:edge_limit]
    return GraphResponse(
        nodes=[AssetRead.model_validate(item) for item in nodes],
        edges=[_relationship_read(edge) for edge in edges],
        truncated=truncated,
    )


@router.get("/targets/{target_id}/tasks", response_model=TaskList)
def list_scan_tasks(
    target_id: int,
    db: Session = Depends(db_session),
    task_status: str | None = Query(default=None, alias="status"),
    module: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> TaskList:
    _target_or_404(db, target_id)
    statement = select(ReconTask).where(ReconTask.target_id == target_id)
    count_statement = (
        select(func.count()).select_from(ReconTask).where(ReconTask.target_id == target_id)
    )
    if task_status:
        statement = statement.where(ReconTask.status == task_status)
        count_statement = count_statement.where(ReconTask.status == task_status)
    if module:
        statement = statement.where(ReconTask.module_name == module)
        count_statement = count_statement.where(ReconTask.module_name == module)
    items = list(
        db.scalars(
            statement.order_by(ReconTask.created_at, ReconTask.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return TaskList(
        items=[TaskRead.model_validate(item) for item in items],
        total=int(db.scalar(count_statement) or 0),
        page=page,
        page_size=page_size,
    )


@router.get("/targets/{target_id}/tasks/{task_id}", response_model=TaskDetail)
def get_scan_task(target_id: int, task_id: int, db: Session = Depends(db_session)) -> TaskDetail:
    task = db.scalar(
        select(ReconTask).where(ReconTask.id == task_id, ReconTask.target_id == target_id)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskDetail.model_validate(task)


@router.get("/targets/{target_id}/events", response_model=list[EventRead])
def list_scan_events(
    target_id: int,
    db: Session = Depends(db_session),
    after_id: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> list[EventRead]:
    _target_or_404(db, target_id)
    events = list(
        db.scalars(
            select(ReconEvent)
            .where(ReconEvent.target_id == target_id, ReconEvent.id > after_id)
            .order_by(ReconEvent.id)
            .limit(limit)
        )
    )
    return [EventRead.model_validate(event) for event in events]


@router.get("/targets/{target_id}/scope", response_model=list[ScopeRuleRead])
def list_scope_rules(target_id: int, db: Session = Depends(db_session)) -> list[ScopeRuleRead]:
    _target_or_404(db, target_id)
    rules = list(
        db.scalars(
            select(ScopeRule)
            .where(ScopeRule.target_id == target_id)
            .order_by(ScopeRule.priority, ScopeRule.id)
        )
    )
    return [ScopeRuleRead.model_validate(rule) for rule in rules]


@router.post(
    "/targets/{target_id}/scope",
    response_model=ScopeRuleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
def add_scope_rule(
    target_id: int,
    payload: ScopeRuleCreate,
    db: Session = Depends(db_session),
) -> ScopeRuleRead:
    _target_or_404(db, target_id)
    try:
        normalized = normalize_rule_pattern(payload.rule_type, payload.pattern)
    except ScopeConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rule = ScopeRule(
        target_id=target_id,
        action=payload.action,
        rule_type=payload.rule_type,
        asset_kind=payload.asset_kind,
        pattern=payload.pattern,
        normalized_pattern=normalized,
        priority=payload.priority,
        reason=payload.reason,
    )
    try:
        with db.begin_nested():
            db.add(rule)
            db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="scope rule already exists") from exc
    TaskScheduler(db).reconcile_scope(_target_or_404(db, target_id))
    db.commit()
    db.refresh(rule)
    return ScopeRuleRead.model_validate(rule)


@router.delete(
    "/targets/{target_id}/scope/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_api_key)],
)
def delete_scope_rule(target_id: int, rule_id: int, db: Session = Depends(db_session)) -> None:
    rule = db.scalar(
        select(ScopeRule).where(ScopeRule.id == rule_id, ScopeRule.target_id == target_id)
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="scope rule not found")
    include_count = db.scalar(
        select(func.count())
        .select_from(ScopeRule)
        .where(ScopeRule.target_id == target_id, ScopeRule.action == "include")
    )
    if rule.action == "include" and include_count == 1:
        raise HTTPException(status_code=409, detail="a scan must retain an inclusion rule")
    db.delete(rule)
    db.flush()
    TaskScheduler(db).reconcile_scope(_target_or_404(db, target_id))
    db.commit()


@router.get(
    "/targets/{target_id}/compare/{baseline_target_id}",
    response_model=ScanComparison,
)
def compare_scans(
    target_id: int,
    baseline_target_id: int,
    db: Session = Depends(db_session),
    limit: int = Query(500, ge=1, le=5000),
) -> ScanComparison:
    current = _target_or_404(db, target_id)
    baseline = _target_or_404(db, baseline_target_id)
    if (current.target_kind, current.url) != (baseline.target_kind, baseline.url):
        raise HTTPException(status_code=409, detail="scans have different root targets")
    current_ids = (
        select(AssetObservation.asset_id.label("asset_id"))
        .where(AssetObservation.target_id == target_id)
        .distinct()
        .subquery()
    )
    baseline_ids = (
        select(AssetObservation.asset_id.label("asset_id"))
        .where(AssetObservation.target_id == baseline_target_id)
        .distinct()
        .subquery()
    )
    added_ids = (
        select(current_ids.c.asset_id)
        .outerjoin(baseline_ids, baseline_ids.c.asset_id == current_ids.c.asset_id)
        .where(baseline_ids.c.asset_id.is_(None))
    )
    removed_ids = (
        select(baseline_ids.c.asset_id)
        .outerjoin(current_ids, current_ids.c.asset_id == baseline_ids.c.asset_id)
        .where(current_ids.c.asset_id.is_(None))
    )
    intersection = select(current_ids.c.asset_id).join(
        baseline_ids, baseline_ids.c.asset_id == current_ids.c.asset_id
    )

    def latest_observations(scan_id: int, name: str):
        ranked = (
            select(
                AssetObservation.asset_id.label("asset_id"),
                AssetObservation.snapshot.label("snapshot"),
                func.row_number()
                .over(
                    partition_by=AssetObservation.asset_id,
                    order_by=(
                        AssetObservation.last_observed_at.desc(),
                        AssetObservation.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(AssetObservation.target_id == scan_id)
            .subquery(f"{name}_ranked")
        )
        return (
            select(ranked.c.asset_id, ranked.c.snapshot)
            .where(ranked.c.row_number == 1)
            .subquery(name)
        )

    current_latest = latest_observations(target_id, "current_latest")
    baseline_latest = latest_observations(baseline_target_id, "baseline_latest")
    snapshot_type = JSONB if db.get_bind().dialect.name == "postgresql" else Text
    changed_ids = (
        select(current_latest.c.asset_id)
        .join(
            baseline_latest,
            baseline_latest.c.asset_id == current_latest.c.asset_id,
        )
        .where(
            cast(current_latest.c.snapshot, snapshot_type)
            != cast(baseline_latest.c.snapshot, snapshot_type)
        )
    )

    added_count = int(db.scalar(select(func.count()).select_from(added_ids.subquery())) or 0)
    removed_count = int(db.scalar(select(func.count()).select_from(removed_ids.subquery())) or 0)
    changed_count = int(db.scalar(select(func.count()).select_from(changed_ids.subquery())) or 0)
    intersection_count = int(
        db.scalar(select(func.count()).select_from(intersection.subquery())) or 0
    )
    added_page = list(db.scalars(added_ids.order_by(current_ids.c.asset_id).limit(limit)))
    removed_page = list(db.scalars(removed_ids.order_by(baseline_ids.c.asset_id).limit(limit)))
    changed_page = list(db.scalars(changed_ids.order_by(current_latest.c.asset_id).limit(limit)))
    truncated = added_count > limit or removed_count > limit or changed_count > limit
    added = list(db.scalars(select(Asset).where(Asset.id.in_(added_page))))
    removed = list(db.scalars(select(Asset).where(Asset.id.in_(removed_page))))
    changed = list(db.scalars(select(Asset).where(Asset.id.in_(changed_page))))
    return ScanComparison(
        baseline_target_id=baseline_target_id,
        comparison_target_id=target_id,
        added=[AssetRead.model_validate(item) for item in added],
        removed=[AssetRead.model_validate(item) for item in removed],
        changed=[AssetRead.model_validate(item) for item in changed],
        unchanged_count=intersection_count - changed_count,
        truncated=truncated,
    )


@router.get("/knowledge/stats", response_model=KnowledgeStats)
def knowledge_stats(db: Session = Depends(db_session)) -> KnowledgeStats:
    asset_rows = db.execute(select(Asset.kind, func.count()).group_by(Asset.kind)).all()
    task_rows = db.execute(select(ReconTask.status, func.count()).group_by(ReconTask.status)).all()
    return KnowledgeStats(
        assets_total=int(db.scalar(select(func.count()).select_from(Asset)) or 0),
        relationships_total=int(
            db.scalar(select(func.count()).select_from(AssetRelationship)) or 0
        ),
        observations_total=int(db.scalar(select(func.count()).select_from(AssetObservation)) or 0),
        tasks_by_status={status: count for status, count in task_rows},
        assets_by_kind={kind: count for kind, count in asset_rows},
    )
