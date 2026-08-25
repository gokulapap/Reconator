def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_and_list(client):
    r = client.post(
        "/api/v1/targets",
        json={"url": "test1.example.com", "authorization_confirmed": True},
    )
    assert r.status_code == 201, r.text
    target = r.json()
    assert target["url"] == "test1.example.com"
    assert target["status"] == "queued"

    r = client.get("/api/v1/targets")
    assert r.status_code == 200
    assert any(t["url"] == "test1.example.com" for t in r.json()["items"])


def test_invalid_domain(client):
    r = client.post(
        "/api/v1/targets",
        json={"url": "not a domain", "authorization_confirmed": True},
    )
    assert r.status_code == 422


def test_public_suffixes_are_rejected_as_scan_roots(client):
    for target_kind, url in (("domain", "co.uk"), ("url", "https://github.io/")):
        response = client.post(
            "/api/v1/targets",
            json={
                "target_kind": target_kind,
                "url": url,
                "authorization_confirmed": True,
            },
        )
        assert response.status_code == 422, response.text


def test_multiple_root_target_kinds_are_normalized(client):
    cases = [
        ("url", "HTTPS://Example.com:443/app/../api#fragment", "https://example.com/api"),
        ("ip_address", "2001:0db8::1", "2001:db8::1"),
        ("cidr", "192.0.2.9/28", "192.0.2.0/28"),
    ]
    for kind, raw, canonical in cases:
        response = client.post(
            "/api/v1/targets",
            json={
                "target_kind": kind,
                "url": raw,
                "authorization_confirmed": True,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["target_kind"] == kind
        assert response.json()["url"] == canonical


def test_duplicate_queued_conflict(client):
    payload = {"url": "dup.example.com", "authorization_confirmed": True}
    client.post("/api/v1/targets", json=payload)
    r = client.post("/api/v1/targets", json=payload)
    assert r.status_code == 409


def test_auth_required_for_writes(unauth_client):
    r = unauth_client.post(
        "/api/v1/targets",
        json={"url": "auth.example.com", "authorization_confirmed": True},
    )
    assert r.status_code == 401

    # reads should still work
    r = unauth_client.get("/api/v1/targets")
    assert r.status_code == 200


def test_sensitive_reads_can_be_protected(client, unauth_client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "protect_read_endpoints", True)
    assert unauth_client.get("/api/v1/targets").status_code == 401
    assert client.get("/api/v1/targets").status_code == 200


def test_bulk_create(client):
    r = client.post(
        "/api/v1/targets/bulk",
        json={
            "urls": ["bulk-a.example.com", "bulk-b.example.com", "not a domain"],
            "tags": ["scope:test"],
            "authorization_confirmed": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["created"]) == 2
    assert "not a domain" in body["errors"]


def test_bulk_target_values_are_individually_bounded(client):
    response = client.post(
        "/api/v1/targets/bulk",
        json={
            "target_kind": "url",
            "urls": [f"https://example.com/{'a' * 2048}"],
            "authorization_confirmed": True,
        },
    )
    assert response.status_code == 422


def test_cancel_queued(client):
    r = client.post(
        "/api/v1/targets",
        json={"url": "cancel.example.com", "authorization_confirmed": True},
    )
    tid = r.json()["id"]
    r = client.post(f"/api/v1/targets/{tid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_rescan_creates_new_target(client):
    r = client.post(
        "/api/v1/targets",
        json={
            "url": "rescan.example.com",
            "tags": ["x"],
            "authorization_confirmed": True,
        },
    )
    tid = r.json()["id"]
    assert client.post(f"/api/v1/targets/{tid}/cancel").status_code == 200
    r = client.post(f"/api/v1/targets/{tid}/rescan")
    assert r.status_code == 201
    new = r.json()
    assert new["id"] != tid
    assert new["url"] == "rescan.example.com"
    assert new["tags"] == ["x"]


def test_stats(client):
    r = client.get("/api/v1/targets/stats")
    assert r.status_code == 200
    body = r.json()
    for k in ("queued", "running", "completed", "failed", "cancelled", "total"):
        assert k in body


def test_export_csv(client):
    r = client.get("/api/v1/targets/export?format=csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert b"id,url,status" in r.content


def test_modules(client):
    r = client.get("/api/v1/modules")
    assert r.status_code == 200
    items = r.json()
    assert any(m["capability"] == "dns.resolve" for m in items)
    assert all(
        m["capability_policy"]
        in {
            "parallel_sources",
            "preferred_then_fallback",
            "sequential_enrichment",
        }
        for m in items
    )
    assert all(isinstance(m["implementation_priority"], int) for m in items)


def test_authorization_confirmation_required(client):
    r = client.post("/api/v1/targets", json={"url": "ack.example.com"})
    assert r.status_code == 422


def test_oversized_request_body_is_rejected_before_parsing(client):
    response = client.post(
        "/api/v1/targets",
        content=b"x" * 1_000_001,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_system_info(client):
    r = client.get("/api/v1/system/info")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_required"] is True
