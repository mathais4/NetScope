"""The three probe types: HTTP, TCP connect and ICMP ping.

Every probe returns an Outcome and never raises: a failure to reach the target
is a normal result to record, not an exception for the caller to handle.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import socket
import time

import httpx

from .models import Outcome, Target

_PING_TIME = re.compile(r"time[=<]([\d.]+)\s*ms")


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


async def check_http(
    client: httpx.AsyncClient, url: str, timeout_s: float, expected_status: int | None
) -> Outcome:
    start = time.perf_counter()
    try:
        resp = await client.get(url, timeout=timeout_s, follow_redirects=False)
    except httpx.TimeoutException:
        return Outcome(False, error=f"timeout after {timeout_s:g}s")
    except httpx.ConnectError as exc:
        return Outcome(False, error=f"connection failed: {_reason(exc)}")
    except httpx.HTTPError as exc:
        return Outcome(False, error=f"{type(exc).__name__}: {_reason(exc)}")

    latency = _elapsed_ms(start)
    code = resp.status_code
    if expected_status is not None:
        ok = code == expected_status
        error = None if ok else f"expected HTTP {expected_status}, got {code}"
    else:
        ok = 200 <= code < 400
        error = None if ok else f"HTTP {code}"
    return Outcome(ok, latency, code, error)


async def check_tcp(host: str, port: int, timeout_s: float) -> Outcome:
    """Succeeds if a TCP handshake completes: the port is open and something is listening."""
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout_s)
    except asyncio.TimeoutError:
        return Outcome(False, error=f"timeout after {timeout_s:g}s")
    except ConnectionRefusedError:
        return Outcome(False, error="connection refused (nothing listening on that port)")
    except socket.gaierror:
        return Outcome(False, error=f"could not resolve host {host!r}")
    except OSError as exc:
        return Outcome(False, error=f"connection failed: {exc.strerror or exc}")
    latency = _elapsed_ms(start)
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return Outcome(True, latency)


async def check_ping(host: str, timeout_s: float) -> Outcome:
    """One ICMP echo using the system `ping` binary.

    Sending ICMP directly needs a raw socket (root or CAP_NET_RAW); the ping
    binary already has the right permissions, so we shell out to it and parse
    the round-trip time it reports.
    """
    if shutil.which("ping") is None:
        return Outcome(False, error="ping is not installed on this host")
    wait = max(1, int(round(timeout_s)))
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-n", "-c", "1", "-W", str(wait), host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s + 2)
    except asyncio.TimeoutError:
        proc.kill()
        return Outcome(False, error=f"timeout after {timeout_s:g}s")

    text = out.decode(errors="replace")
    if proc.returncode == 0:
        match = _PING_TIME.search(text)
        return Outcome(True, float(match.group(1)) if match else None)
    detail = err.decode(errors="replace").strip().splitlines()
    return Outcome(False, error=detail[-1] if detail else "no reply")


async def run_check(target: Target, client: httpx.AsyncClient) -> Outcome:
    if target.kind == "http":
        return await check_http(client, target.url or "", target.timeout_s, target.expected_status)
    if target.kind == "tcp":
        return await check_tcp(target.host or "", target.port or 0, target.timeout_s)
    if target.kind == "ping":
        return await check_ping(target.host or "", target.timeout_s)
    return Outcome(False, error=f"unknown check kind {target.kind!r}")


def _reason(exc: Exception) -> str:
    text = str(exc).strip()
    return text or type(exc).__name__
