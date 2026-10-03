import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="sentinel-test-")
os.environ["SENTINEL_DATABASE_URL"] = os.environ.get("SENTINEL_TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["SENTINEL_STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["SENTINEL_API_KEYS"] = "test-key"
os.environ["SENTINEL_SEED_DEMO"] = "false"  # tests that need the synthetic background cases seed them explicitly
os.environ.pop("SENTINEL_ANTHROPIC_API_KEY", None)
os.environ["SENTINEL_STT_ENGINE"] = "none"  # tests never download models; the STT path is tested with a stub

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.graph.network import graph  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import reset_database  # noqa: E402

H = {"X-API-Key": "test-key"}  # partner key for the real-time risk API
API = "/api/v1"
LOGINS = {
    "victim": ("victim@demo.upisentinel.in", "Victim@2026"), "victim2": ("victim2@demo.upisentinel.in", "Victim@2026"),
    "bank": ("bank@demo.upisentinel.in", "Bank@2026"), "bank2": ("bank2@demo.upisentinel.in", "Bank@2026"),
    "cyber": ("cyber@demo.upisentinel.in", "Cyber@2026"),
}


@pytest.fixture()
def client():
    reset_database()
    with TestClient(app) as c:
        with SessionLocal() as db:
            graph.rebuild(db)
        yield c


@pytest.fixture()
def auth(client):
    out = {}
    for k, (e, p) in LOGINS.items():
        r = client.post(f"{API}/auth/login", json={"login": e, "password": p})
        assert r.status_code == 200, r.text
        out[k] = {"Authorization": "Bearer " + r.json()["token"]}
    return out


@pytest.fixture()
def scenarios(client):
    return {s["id"]: s for s in client.get(f"{API}/demo/risk-scenarios", headers=H).json()}
