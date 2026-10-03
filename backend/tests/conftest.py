import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="sentinel-test-")
os.environ["SENTINEL_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SENTINEL_STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["SENTINEL_API_KEYS"] = "test-key"
os.environ.pop("SENTINEL_ANTHROPIC_API_KEY", None)
os.environ["SENTINEL_STT_ENGINE"] = "none"  # tests never download models; the STT path is tested with a stub

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.graph.network import graph  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import reset_database  # noqa: E402

H = {"X-API-Key": "test-key"}


@pytest.fixture()
def client():
    reset_database()
    with TestClient(app) as c:
        with SessionLocal() as db:
            graph.rebuild(db)
        yield c


@pytest.fixture()
def scenarios(client):
    return {s["id"]: s for s in client.get("/api/v1/demo/risk-scenarios", headers=H).json()}
