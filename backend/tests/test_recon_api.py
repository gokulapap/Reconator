def create_passive(client, domain):
    response = client.post(
        "/api/v1/targets",
        json={
            "url": domain,
            "profile": "passive",
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_asset_task_event_and_scope_apis(client):
    target = create_passive(client, "api-surface.example.com")
    target_id = target["id"]

    assets = client.get(f"/api/v1/targets/{target_id}/assets").json()
    assert assets["total"] == 1
    assert assets["items"][0]["canonical_value"] == "api-surface.example.com"
    asset_id = assets["items"][0]["id"]

    intelligence = client.get(f"/api/v1/targets/{target_id}/assets/{asset_id}").json()
    assert intelligence["asset"]["id"] == asset_id
    assert intelligence["observations"][0]["source_module"] == "core.seed"
    assert intelligence["relationships"] == []

    summary = client.get(f"/api/v1/targets/{target_id}/knowledge-summary").json()
    assert summary["assets_total"] == 1
    assert summary["assets_by_kind"] == {"domain": 1}
    assert summary["observations_by_module"] == {"core.seed": 1}
    assert summary["source_yield"][0] == {
        "source_module": "core.seed",
        "source_name": "user",
        "observations": 1,
        "distinct_assets": 1,
        "exclusive_assets": 1,
        "average_confidence": 1.0,
        "last_observed_at": summary["source_yield"][0]["last_observed_at"],
    }
    assert summary["module_health"][0]["tasks_total"] == 1
    assert summary["module_health"][0]["tasks_by_status"] == {"queued": 1}
    assert summary["module_health"][0]["failure_rate"] == 0

    tasks = client.get(f"/api/v1/targets/{target_id}/tasks").json()
    assert tasks["total"] == 1
    task_id = tasks["items"][0]["id"]
    assert client.get(f"/api/v1/targets/{target_id}/tasks/{task_id}").status_code == 200

    events = client.get(f"/api/v1/targets/{target_id}/events").json()
    assert {event["event_type"] for event in events} >= {"scan.created", "task.queued"}

    scope = client.get(f"/api/v1/targets/{target_id}/scope").json()
    assert scope[0]["rule_type"] == "subdomain"

    add = client.post(
        f"/api/v1/targets/{target_id}/scope",
        json={
            "action": "exclude",
            "rule_type": "subdomain",
            "pattern": "internal.api-surface.example.com",
            "reason": "explicit exclusion fixture",
        },
    )
    assert add.status_code == 201, add.text


def test_source_yield_distinguishes_exclusive_and_corroborated_assets(client, db):
    from app.recon.knowledge import KnowledgeStore
    from app.recon.modules.base import AssetEmission

    target = create_passive(client, "yield.example.com")
    store = KnowledgeStore(db)
    store.observe_asset(
        target_id=target["id"],
        task_id=None,
        module_name="passive.alpha",
        emission=AssetEmission(
            "domain",
            "unique.yield.example.com",
            source_name="alpha-index",
        ),
    )
    for module_name, source_name in (
        ("passive.alpha", "alpha-index"),
        ("passive.beta", "beta-index"),
    ):
        store.observe_asset(
            target_id=target["id"],
            task_id=None,
            module_name=module_name,
            emission=AssetEmission(
                "domain",
                "shared.yield.example.com",
                confidence=0.8,
                source_name=source_name,
            ),
        )
    db.commit()

    summary = client.get(f"/api/v1/targets/{target['id']}/knowledge-summary").json()
    sources = {
        (item["source_module"], item["source_name"]): item for item in summary["source_yield"]
    }
    assert sources[("passive.alpha", "alpha-index")]["distinct_assets"] == 2
    assert sources[("passive.alpha", "alpha-index")]["exclusive_assets"] == 1
    assert sources[("passive.beta", "beta-index")]["distinct_assets"] == 1
    assert sources[("passive.beta", "beta-index")]["exclusive_assets"] == 0


def test_knowledge_summary_reports_exact_quality_health_and_zero_yield(client, db):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db.models import ReconTask

    target = create_passive(client, "quality-summary.example.com")
    completed_at = datetime.now(timezone.utc)
    first_task = db.scalar(select(ReconTask).where(ReconTask.target_id == target["id"]))
    first_task.module_name = "quality.zero-yield"
    first_task.capability = "domain.quality_probe"
    first_task.status = "completed"
    first_task.started_at = completed_at - timedelta(seconds=10)
    first_task.completed_at = completed_at
    first_task.output_summary = {
        "pagination_truncated": True,
        "raw_output_truncated": True,
        "validation_error_count": 4,
    }
    db.add(
        ReconTask(
            target_id=target["id"],
            module_name="quality.zero-yield",
            capability="domain.quality_probe",
            status="failed",
            idempotency_key="quality-failed-task",
            cache_key="quality-failed-cache",
            available_at=completed_at,
            started_at=completed_at - timedelta(seconds=20),
            completed_at=completed_at,
            error_code="provider_timeout",
            output_summary={"validation_error_count": 0},
        )
    )
    db.commit()

    response = client.get(f"/api/v1/targets/{target['id']}/knowledge-summary")
    assert response.status_code == 200, response.text
    summary = response.json()

    assert summary["completeness"] == {
        "tasks_inspected": 2,
        "tasks_total": 2,
        "truncated_tasks": 1,
        "discovery_truncated_tasks": 1,
        "evidence_truncated_tasks": 1,
        "validation_rejections": 4,
    }
    zero_yield = next(
        item
        for item in summary["source_yield"]
        if item["source_module"] == "quality.zero-yield"
    )
    assert zero_yield == {
        "source_module": "quality.zero-yield",
        "source_name": None,
        "observations": 0,
        "distinct_assets": 0,
        "exclusive_assets": 0,
        "average_confidence": 0,
        "last_observed_at": None,
    }
    health = next(
        item
        for item in summary["module_health"]
        if item["module_name"] == "quality.zero-yield"
    )
    assert health["error_codes"] == {"provider_timeout": 1}
    assert health["duration_sample_size"] == 2
    assert health["duration_total"] == 2
    assert health["average_duration_seconds"] == 15
    assert health["p95_duration_seconds"] == 20


def test_scan_comparison_endpoint(client, db):
    from app.db.models import Target, TargetStatus

    first = create_passive(client, "compare.example.com")
    source = db.get(Target, first["id"])
    source.status = TargetStatus.completed
    db.commit()
    second_response = client.post(f"/api/v1/targets/{first['id']}/rescan")
    assert second_response.status_code == 201
    second = second_response.json()
    comparison = client.get(f"/api/v1/targets/{second['id']}/compare/{first['id']}")
    assert comparison.status_code == 200, comparison.text
    body = comparison.json()
    assert body["unchanged_count"] >= 1
    assert body["added"] == []
    assert body["removed"] == []
