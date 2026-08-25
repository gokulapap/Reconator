import pytest

from app.core.config import settings
from app.db.models import Asset, AssetObservation, AssetRelationship, Target
from app.recon.knowledge import KnowledgeStore
from app.recon.modules.base import (
    AssetEmission,
    AssetReference,
    ModuleExecutionError,
    ModuleResult,
    RelationshipEmission,
)


def make_target(db, domain: str) -> Target:
    target = Target(url=domain, authorization_confirmed=True)
    db.add(target)
    db.flush()
    return target


def test_observations_deduplicate_assets_but_preserve_provenance(db):
    target = make_target(db, "knowledge.example.com")
    store = KnowledgeStore(db)
    first = store.observe_asset(
        target_id=target.id,
        task_id=None,
        module_name="source.one",
        emission=AssetEmission("domain", "API.Knowledge.Example.com", evidence={"row": 1}),
    )
    second = store.observe_asset(
        target_id=target.id,
        task_id=None,
        module_name="source.two",
        emission=AssetEmission(
            "domain",
            "api.knowledge.example.com.",
            {"environment": "production"},
            evidence={"row": 2},
        ),
    )
    db.commit()

    assert first.asset.id == second.asset.id
    assert first.new_globally
    assert second.new_to_scan is False
    assert db.query(Asset).filter(Asset.canonical_value == "api.knowledge.example.com").count() == 1
    assert (
        db.query(AssetObservation).filter(AssetObservation.asset_id == first.asset.id).count() == 2
    )
    assert second.asset.attributes["environment"] == "production"


def test_relationships_are_typed_and_deduplicated(db):
    target = make_target(db, "relations.example.com")
    store = KnowledgeStore(db)
    emission = RelationshipEmission(
        AssetReference("domain", "relations.example.com"),
        AssetReference("domain", "api.relations.example.com"),
        "has_subdomain",
        evidence={"source": "fixture"},
    )
    first = store.observe_relationship(
        target_id=target.id, task_id=None, module_name="fixture", emission=emission
    )
    second = store.observe_relationship(
        target_id=target.id, task_id=None, module_name="fixture", emission=emission
    )
    db.commit()
    assert first.id == second.id
    assert db.query(AssetRelationship).count() >= 1


def test_malformed_emissions_are_isolated_from_valid_results(db):
    target = make_target(db, "isolation.example.com")
    persisted = KnowledgeStore(db).persist_result(
        target_id=target.id,
        task_id=None,
        module_name="fixture.untrusted_output",
        result=ModuleResult(
            assets=[
                AssetEmission("domain", "valid.isolation.example.com"),
                AssetEmission("domain", "not a domain"),
            ],
            relationships=[
                RelationshipEmission(
                    AssetReference("domain", "valid.isolation.example.com"),
                    AssetReference("domain", "valid.isolation.example.com"),
                    "self_link",
                )
            ],
        ),
    )
    db.commit()
    assert [item.asset.canonical_value for item in persisted.assets] == [
        "valid.isolation.example.com"
    ]
    assert len(persisted.validation_errors) == 2


def test_non_json_emission_metadata_is_rejected_without_losing_valid_assets(db):
    target = make_target(db, "json-safety.example.com")
    persisted = KnowledgeStore(db).persist_result(
        target_id=target.id,
        task_id=None,
        module_name="fixture.untrusted_output",
        result=ModuleResult(
            assets=[
                AssetEmission("domain", "valid.json-safety.example.com"),
                AssetEmission(
                    "domain",
                    "invalid.json-safety.example.com",
                    attributes={"value": object()},
                ),
            ]
        ),
    )

    assert [item.asset.canonical_value for item in persisted.assets] == [
        "valid.json-safety.example.com"
    ]
    assert len(persisted.validation_errors) == 1


def test_task_emission_count_is_bounded(db, monkeypatch):
    target = make_target(db, "bounded-output.example.com")
    monkeypatch.setattr(settings, "max_asset_emissions_per_task", 1)

    with pytest.raises(ModuleExecutionError) as exc_info:
        KnowledgeStore(db).persist_result(
            target_id=target.id,
            task_id=None,
            module_name="fixture.untrusted_output",
            result=ModuleResult(
                assets=[
                    AssetEmission("domain", "one.bounded-output.example.com"),
                    AssetEmission("domain", "two.bounded-output.example.com"),
                ]
            ),
        )

    assert exc_info.value.code == "output_limit"
    assert exc_info.value.retryable is False
