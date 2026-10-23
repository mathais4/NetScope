"""End-to-end API tests against a real PostgreSQL database.

Skipped unless TEST_DATABASE_URL is set, because they wipe the tables they use:
    docker compose up -d db
    TEST_DATABASE_URL=postgresql://netscope:netscope@localhost:5432/netscope pytest
"""

import asyncio
import os

import pytest

fastapi = pytest.importorskip("fastapi")
asyncpg = pytest.importorskip("asyncpg")

DSN = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    async def reset():
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute(
                "DROP TABLE IF EXISTS check_results, incidents, targets CASCADE"
            )
        finally:
            await conn.close()

    asyncio.run(reset())
    app = create_app(Settings(database_url=DSN, failure_threshold=1, recovery_threshold=1))
    with TestClient(app) as c:
        yield c


CLOSED_PORT = {"name": "closed port", "kind": "tcp", "host": "127.0.0.1", "port": 1,
               "interval_s": 60, "timeout_s": 1, "enabled": False}


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_validation_errors_return_422(client):
    r = client.post("/api/targets", json={"name": "x", "kind": "tcp", "host": "db"})
    assert r.status_code == 422


def test_target_lifecycle(client):
    r = client.post("/api/targets", json=CLOSED_PORT)
    assert r.status_code == 201
    target = r.json()
    tid = target["id"]
    assert target["status"] == "paused"
    assert target["stats_24h"]["uptime_pct"] is None

    assert [t["id"] for t in client.get("/api/targets").json()] == [tid]

    check = client.post(f"/api/targets/{tid}/check").json()
    assert check["ok"] is False and check["error"].startswith("connection refused")

    results = client.get(f"/api/targets/{tid}/results").json()
    assert len(results) == 1 and results[0]["ok"] is False

    detail = client.get(f"/api/targets/{tid}").json()
    assert detail["stats_24h"]["checks"] == 1
    assert detail["stats_24h"]["uptime_pct"] == 0.0
    assert detail["last"]["ok"] is False

    history = client.get(f"/api/targets/{tid}/history?range=1h").json()
    assert history["bucket_s"] == 60 and len(history["buckets"]) == 1

    # failure_threshold=1 in this test app, so one failure opens an incident
    incidents = client.get("/api/incidents?open_only=true").json()
    assert len(incidents) == 1 and incidents[0]["target_id"] == tid

    summary = client.get("/api/summary").json()
    assert summary["targets"] == 1 and summary["open_incidents"] == 1

    r = client.put(f"/api/targets/{tid}", json={**CLOSED_PORT, "name": "renamed"})
    assert r.status_code == 200 and r.json()["name"] == "renamed"

    assert client.delete(f"/api/targets/{tid}").status_code == 204
    assert client.get(f"/api/targets/{tid}").status_code == 404
    assert client.delete(f"/api/targets/{tid}").status_code == 404


def test_bad_history_range(client):
    tid = client.post("/api/targets", json=CLOSED_PORT).json()["id"]
    assert client.get(f"/api/targets/{tid}/history?range=1y").status_code == 422


def test_websocket_says_hello(client):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"type": "hello"}
