"""Probe tests against real sockets on localhost: a tiny HTTP server we control,
an open TCP port, and a port with nothing listening."""

import asyncio
import shutil
import socket

import httpx
import pytest

from app.checks import check_http, check_ping, check_tcp, run_check
from app.models import Target

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _start_http(status: int = 200, delay: float = 0.0):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        await reader.readuntil(b"\r\n\r\n")
        await asyncio.sleep(delay)
        writer.write(
            f"HTTP/1.1 {status} X\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok".encode()
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"http://127.0.0.1:{port}/health"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_http_ok_measures_latency():
    server, url = await _start_http(200, delay=0.05)
    async with server, httpx.AsyncClient() as client:
        o = await check_http(client, url, 2, None)
    assert o.ok and o.status_code == 200 and o.error is None
    assert o.latency_ms is not None and o.latency_ms >= 45


async def test_http_server_error_is_failure():
    server, url = await _start_http(503)
    async with server, httpx.AsyncClient() as client:
        o = await check_http(client, url, 2, None)
    assert not o.ok and o.status_code == 503 and o.error == "HTTP 503"


async def test_http_redirect_counts_as_up_by_default():
    server, url = await _start_http(302)
    async with server, httpx.AsyncClient() as client:
        o = await check_http(client, url, 2, None)
    assert o.ok


async def test_http_expected_status_is_enforced():
    server, url = await _start_http(200)
    async with server, httpx.AsyncClient() as client:
        o = await check_http(client, url, 2, 204)
    assert not o.ok and o.error == "expected HTTP 204, got 200"


async def test_http_timeout():
    server, url = await _start_http(200, delay=1.0)
    async with server, httpx.AsyncClient() as client:
        o = await check_http(client, url, 0.2, None)
    assert not o.ok and o.error == "timeout after 0.2s" and o.latency_ms is None


async def test_http_connection_refused():
    async with httpx.AsyncClient() as client:
        o = await check_http(client, f"http://127.0.0.1:{_free_port()}/", 1, None)
    assert not o.ok and o.error.startswith("connection failed")


async def test_tcp_open_port():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        o = await check_tcp("127.0.0.1", port, 1)
    assert o.ok and o.latency_ms is not None


async def test_tcp_closed_port():
    o = await check_tcp("127.0.0.1", _free_port(), 1)
    assert not o.ok and o.error.startswith("connection refused")


async def test_tcp_unknown_host():
    o = await check_tcp("no-such-host.invalid", 80, 2)
    assert not o.ok and "resolve" in o.error


@pytest.mark.skipif(shutil.which("ping") is None, reason="ping binary not installed")
async def test_ping_localhost():
    o = await check_ping("127.0.0.1", 2)
    assert o.ok and o.latency_ms is not None


async def test_ping_reports_missing_binary(monkeypatch):
    monkeypatch.setattr("app.checks.shutil.which", lambda _: None)
    o = await check_ping("127.0.0.1", 1)
    assert not o.ok and "not installed" in o.error


async def test_run_check_dispatches_by_kind():
    server, url = await _start_http(200)
    async with server, httpx.AsyncClient() as client:
        o = await run_check(Target(1, "web", "http", url=url, timeout_s=2), client)
    assert o.ok
