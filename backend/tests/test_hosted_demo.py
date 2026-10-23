"""Hosted entry points must serve the UI and reject public writes before DB access."""
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import TargetIn
from app.seed import demo_targets


def test_hosted_dashboard_and_api_share_origin(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<h1>NetScope test dashboard</h1>")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    app = create_app(Settings(database_url="postgresql://unused", public_demo_read_only=True))
    # Deliberately don't enter the context: these routes must not touch the DB.
    client = TestClient(app)
    assert "NetScope test dashboard" in client.get("/").text
    assert client.get("/api/health").json() == {"status": "ok"}
    for method, path in [("POST", "/api/targets"), ("PUT", "/api/targets/1"),
                         ("DELETE", "/api/targets/1"), ("POST", "/api/targets/1/check")]:
        assert client.request(method, path, json={}).status_code == 403


def test_cloud_seed_uses_runtime_port_and_database_host(monkeypatch):
    monkeypatch.setenv("SEED_PROFILE", "cloud")
    monkeypatch.setenv("PORT", "12345")
    targets = demo_targets("postgresql://user:password@private-postgres:5433/netscope")
    for target in targets:
        TargetIn(**target)
    assert targets[0]["url"] == "http://127.0.0.1:12345/api/health"
    assert targets[3]["host"] == "private-postgres"
    assert targets[3]["port"] == 5433
    assert not any(t["kind"] == "ping" for t in targets)
