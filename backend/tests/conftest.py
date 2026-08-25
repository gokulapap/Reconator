import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# Configure environment BEFORE importing app modules.
with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as _db_file:
    _db_path = _db_file.name
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["ADMIN_API_KEY"] = "test-key"
os.environ["RATE_LIMIT_WRITES"] = "1000/minute"
os.environ["RATE_LIMIT_BULK"] = "1000/minute"
os.environ["METRICS_ENABLED"] = "false"


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_db():
    from app.db import models  # noqa: F401  (register models)
    from app.db.base import Base
    from app.db.session import engine as real_engine

    Base.metadata.create_all(bind=real_engine)
    yield


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        c.headers.update({"X-API-Key": "test-key"})
        yield c


@pytest.fixture
def unauth_client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        yield session
