from fastapi.responses import JSONResponse

from app.api.routes import health
from app.core import auth


def test_readiness_failure_returns_503_without_database_details(monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("postgresql://secret@database/reconator")

    monkeypatch.setattr(health, "engine", BrokenEngine())

    response = health.ready()

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert response.body == b'{"status":"degraded"}'


def test_metrics_requires_key_when_read_protection_is_enabled(unauth_client, monkeypatch):
    monkeypatch.setattr(auth.settings, "protect_read_endpoints", True)

    response = unauth_client.get("/api/v1/metrics")

    assert response.status_code == 401


def test_metrics_exposes_database_backed_task_state(client):
    response = client.get("/api/v1/metrics")

    assert response.status_code == 200
    assert "reconator_task_records" in response.text
    assert 'status="queued"' in response.text
