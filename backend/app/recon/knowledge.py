from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    Asset,
    AssetObservation,
    AssetRelationship,
    ReconEvent,
    RelationshipObservation,
)
from app.recon.modules.base import (
    AssetEmission,
    ModuleExecutionError,
    ModuleResult,
    RelationshipEmission,
)
from app.recon.normalization import (
    NormalizationError,
    NormalizedAsset,
    normalize_asset,
    stable_digest,
)
from app.recon.prioritization import prioritizer

_RELATIONSHIP_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
log = logging.getLogger(__name__)


def _validate_json_payload(value: Any, label: str, *, max_bytes: int | None = None) -> None:
    limit = max_bytes or settings.max_emission_metadata_bytes
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            check_circular=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if len(encoded) > limit:
        raise ValueError(f"{label} exceeds {limit} bytes")


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ObservedAsset:
    asset: Asset
    normalized: NormalizedAsset
    new_globally: bool
    new_to_scan: bool
    changed: bool


@dataclass(slots=True)
class PersistedResult:
    assets: list[ObservedAsset]
    relationship_ids: list[int]
    validation_errors: list[str]


class KnowledgeStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_or_create_asset(self, normalized: NormalizedAsset) -> tuple[Asset, bool, bool]:
        asset = self.db.scalar(
            select(Asset).where(
                Asset.kind == normalized.kind,
                Asset.identity_hash == normalized.identity_hash,
            )
        )
        now = utcnow()
        if asset is None:
            score, signals = prioritizer.score(normalized, is_new=True)
            asset = Asset(
                kind=normalized.kind,
                value=normalized.value,
                canonical_value=normalized.canonical_value,
                identity_hash=normalized.identity_hash,
                attributes={
                    **normalized.attributes,
                    "priority_signals": [asdict(signal) for signal in signals],
                },
                priority_score=score,
                first_seen_at=now,
                last_seen_at=now,
                last_changed_at=now,
                active=True,
            )
            try:
                with self.db.begin_nested():
                    self.db.add(asset)
                    self.db.flush()
                return asset, True, True
            except IntegrityError:
                asset = self.db.scalar(
                    select(Asset).where(
                        Asset.kind == normalized.kind,
                        Asset.identity_hash == normalized.identity_hash,
                    )
                )
                if asset is None:
                    raise

        merged = {**(asset.attributes or {}), **normalized.attributes}
        changed = merged != (asset.attributes or {})
        if changed:
            refreshed = NormalizedAsset(
                normalized.kind,
                normalized.value,
                normalized.canonical_value,
                normalized.identity_hash,
                merged,
            )
            score, signals = prioritizer.score(refreshed, is_new=False)
            merged["priority_signals"] = [asdict(signal) for signal in signals]
            asset.attributes = merged
            asset.priority_score = max(asset.priority_score, score)
            asset.last_changed_at = now
        asset.last_seen_at = now
        asset.active = True
        return asset, False, changed

    def observe_asset(
        self,
        *,
        target_id: int,
        task_id: int | None,
        module_name: str,
        emission: AssetEmission,
    ) -> ObservedAsset:
        if not isinstance(emission.confidence, int | float) or not 0 <= emission.confidence <= 1:
            raise ValueError("asset confidence must be between 0 and 1")
        if not isinstance(emission.attributes, dict) or not isinstance(emission.evidence, dict):
            raise ValueError("asset attributes and evidence must be objects")
        _validate_json_payload(emission.attributes, "asset attributes")
        _validate_json_payload(emission.evidence, "asset evidence")
        normalized = normalize_asset(emission.kind, emission.value, emission.attributes)
        asset, new_globally, changed = self._get_or_create_asset(normalized)
        provenance_key = stable_digest(
            task_id,
            module_name,
            normalized.kind,
            normalized.canonical_value,
            emission.source_name,
            emission.evidence,
        )
        observation = self.db.scalar(
            select(AssetObservation).where(
                AssetObservation.target_id == target_id,
                AssetObservation.provenance_key == provenance_key,
            )
        )
        new_to_scan = not self.db.scalar(
            select(AssetObservation.id).where(
                AssetObservation.target_id == target_id,
                AssetObservation.asset_id == asset.id,
            )
        )
        now = utcnow()
        if observation:
            observation.last_observed_at = now
            observation.observation_count += 1
            observation.snapshot = {
                "canonical_value": normalized.canonical_value,
                "attributes": normalized.attributes,
            }
        else:
            self.db.add(
                AssetObservation(
                    target_id=target_id,
                    asset_id=asset.id,
                    task_id=task_id,
                    source_module=module_name,
                    source_name=emission.source_name,
                    provenance_key=provenance_key,
                    confidence=emission.confidence,
                    evidence=emission.evidence,
                    snapshot={
                        "canonical_value": normalized.canonical_value,
                        "attributes": normalized.attributes,
                    },
                    first_observed_at=now,
                    last_observed_at=now,
                    observation_count=1,
                )
            )
        self.db.flush()
        return ObservedAsset(asset, normalized, new_globally, new_to_scan, changed)

    def observe_relationship(
        self,
        *,
        target_id: int,
        task_id: int | None,
        module_name: str,
        emission: RelationshipEmission,
    ) -> AssetRelationship:
        if not _RELATIONSHIP_TYPE.fullmatch(emission.relationship_type):
            raise ValueError("relationship type must be lower_snake_case")
        if not isinstance(emission.confidence, int | float) or not 0 <= emission.confidence <= 1:
            raise ValueError("relationship confidence must be between 0 and 1")
        if not isinstance(emission.attributes, dict) or not isinstance(emission.evidence, dict):
            raise ValueError("relationship attributes and evidence must be objects")
        _validate_json_payload(emission.attributes, "relationship attributes")
        _validate_json_payload(emission.evidence, "relationship evidence")
        source_normalized = normalize_asset(emission.source.kind, emission.source.value)
        target_normalized = normalize_asset(emission.target.kind, emission.target.value)
        source, _, _ = self._get_or_create_asset(source_normalized)
        target, _, _ = self._get_or_create_asset(target_normalized)
        if source.id == target.id:
            raise ValueError("self-referential relationships are not stored")
        relationship = self.db.scalar(
            select(AssetRelationship).where(
                AssetRelationship.source_asset_id == source.id,
                AssetRelationship.target_asset_id == target.id,
                AssetRelationship.relationship_type == emission.relationship_type,
            )
        )
        now = utcnow()
        if relationship is None:
            relationship = AssetRelationship(
                source_asset_id=source.id,
                target_asset_id=target.id,
                relationship_type=emission.relationship_type,
                attributes=emission.attributes,
                confidence=emission.confidence,
                first_seen_at=now,
                last_seen_at=now,
            )
            try:
                with self.db.begin_nested():
                    self.db.add(relationship)
                    self.db.flush()
            except IntegrityError:
                relationship = self.db.scalar(
                    select(AssetRelationship).where(
                        AssetRelationship.source_asset_id == source.id,
                        AssetRelationship.target_asset_id == target.id,
                        AssetRelationship.relationship_type == emission.relationship_type,
                    )
                )
                if relationship is None:
                    raise
        else:
            relationship.last_seen_at = now
            relationship.attributes = {
                **(relationship.attributes or {}),
                **emission.attributes,
            }
            relationship.confidence = max(relationship.confidence, emission.confidence)

        provenance_key = stable_digest(
            task_id,
            module_name,
            source_normalized.identity_hash,
            emission.relationship_type,
            target_normalized.identity_hash,
            emission.evidence,
        )
        existing_observation = self.db.scalar(
            select(RelationshipObservation.id).where(
                RelationshipObservation.target_id == target_id,
                RelationshipObservation.provenance_key == provenance_key,
            )
        )
        if not existing_observation:
            self.db.add(
                RelationshipObservation(
                    target_id=target_id,
                    relationship_id=relationship.id,
                    task_id=task_id,
                    source_module=module_name,
                    provenance_key=provenance_key,
                    evidence=emission.evidence,
                    observed_at=now,
                )
            )
        self.db.flush()
        return relationship

    def persist_result(
        self,
        *,
        target_id: int,
        task_id: int | None,
        module_name: str,
        result: ModuleResult,
    ) -> PersistedResult:
        if not isinstance(result, ModuleResult):
            raise ModuleExecutionError(
                "module returned an invalid result type",
                retryable=False,
                code="invalid_output",
            )
        if not isinstance(result.assets, list) or not isinstance(result.relationships, list):
            raise ModuleExecutionError(
                "module assets and relationships must be lists",
                retryable=False,
                code="invalid_output",
            )
        if len(result.assets) > settings.max_asset_emissions_per_task:
            raise ModuleExecutionError(
                "module asset emission limit exceeded",
                retryable=False,
                code="output_limit",
            )
        if len(result.relationships) > settings.max_relationship_emissions_per_task:
            raise ModuleExecutionError(
                "module relationship emission limit exceeded",
                retryable=False,
                code="output_limit",
            )
        if not isinstance(result.metadata, dict):
            raise ModuleExecutionError(
                "module metadata must be an object",
                retryable=False,
                code="invalid_output",
            )
        try:
            _validate_json_payload(result.metadata, "module metadata")
        except ValueError as exc:
            raise ModuleExecutionError(str(exc), retryable=False, code="invalid_output") from exc
        if result.raw_output is not None and not isinstance(result.raw_output, str):
            raise ModuleExecutionError(
                "module raw output must be text",
                retryable=False,
                code="invalid_output",
            )
        observed: list[ObservedAsset] = []
        validation_errors: list[str] = []
        seen_keys: set[tuple[str, str]] = set()
        for emission in result.assets:
            try:
                item = self.observe_asset(
                    target_id=target_id,
                    task_id=task_id,
                    module_name=module_name,
                    emission=emission,
                )
            except (NormalizationError, ValueError) as exc:
                validation_errors.append(f"asset {emission.kind}: {exc}")
                continue
            key = (item.normalized.kind, item.normalized.identity_hash)
            if key not in seen_keys:
                seen_keys.add(key)
                observed.append(item)
        relationship_ids: list[int] = []
        seen_relationship_ids: set[int] = set()
        for relationship in result.relationships:
            try:
                persisted_relationship = self.observe_relationship(
                    target_id=target_id,
                    task_id=task_id,
                    module_name=module_name,
                    emission=relationship,
                )
            except (NormalizationError, ValueError) as exc:
                validation_errors.append(f"relationship {relationship.relationship_type}: {exc}")
                continue
            if persisted_relationship.id not in seen_relationship_ids:
                seen_relationship_ids.add(persisted_relationship.id)
                relationship_ids.append(persisted_relationship.id)
        if validation_errors:
            log.warning(
                "module result contained invalid emissions task_id=%s module=%s count=%s",
                task_id,
                module_name,
                len(validation_errors),
            )
        return PersistedResult(observed, relationship_ids, validation_errors)

    def record_event(
        self,
        *,
        target_id: int,
        event_type: str,
        message: str,
        task_id: int | None = None,
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> ReconEvent:
        event = ReconEvent(
            target_id=target_id,
            task_id=task_id,
            event_type=event_type,
            level=level,
            message=message,
            data=data or {},
            created_at=utcnow(),
        )
        self.db.add(event)
        self.db.flush()
        return event
