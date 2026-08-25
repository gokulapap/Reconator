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
