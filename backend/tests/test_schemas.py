import pytest
from pydantic import ValidationError

from app.schemas import TargetIn
from app.stats import uptime_pct


def test_http_target_needs_url():
    with pytest.raises(ValidationError, match="url"):
        TargetIn(name="web", kind="http", host="example.com")


def test_http_target_drops_host_and_port():
    t = TargetIn(name="web", kind="http", url=" https://example.com ", host="x", port=80)
    assert t.url == "https://example.com" and t.host is None and t.port is None


def test_tcp_target_needs_host_and_port():
    with pytest.raises(ValidationError, match="host and a port"):
        TargetIn(name="db", kind="tcp", host="db")


def test_ping_target_ignores_port_and_status():
    t = TargetIn(name="gw", kind="ping", host="10.0.0.1", port=22, expected_status=200)
    assert t.port is None and t.expected_status is None


def test_timeout_must_be_shorter_than_interval():
    with pytest.raises(ValidationError, match="timeout_s"):
        TargetIn(name="db", kind="tcp", host="db", port=5432, interval_s=5, timeout_s=5)


@pytest.mark.parametrize("field,value", [("interval_s", 4), ("interval_s", 3601), ("port", 0), ("port", 70000)])
def test_bounds(field, value):
    data = {"name": "db", "kind": "tcp", "host": "db", "port": 5432, field: value}
    with pytest.raises(ValidationError):
        TargetIn(**data)


def test_blank_name_rejected():
    with pytest.raises(ValidationError):
        TargetIn(name="   ", kind="ping", host="x")


def test_uptime_pct():
    assert uptime_pct(0, 0) is None
    assert uptime_pct(17, 20) == 85.0
    assert uptime_pct(2, 3) == 66.667
