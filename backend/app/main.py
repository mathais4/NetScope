"""FastAPI application: REST API, live WebSocket feed, and background jobs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, load_settings
from .detector import IncidentDetector
from .stats import uptime_pct
from .notifier import Hub, Notifier
from .scheduler import Monitor
from .schemas import TargetIn
from .seed import demo_targets
from .store import PgStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("netscope")

RANGES: dict[str, tuple[timedelta, int]] = {
    # range -> (how far back, chart bucket size in seconds)
    "1h": (timedelta(hours=1), 60),
    "24h": (timedelta(hours=24), 15 * 60),
    "7d": (timedelta(days=7), 2 * 60 * 60),
}


async def _prune_forever(store: PgStore, retention_days: int) -> None:
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            deleted = await store.prune(cutoff)
            if deleted:
                log.info("retention: deleted %d results older than %d days", deleted, retention_days)
        except Exception:
            log.exception("retention job failed")
        await asyncio.sleep(3600)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = await PgStore.connect(settings.database_url)
        await store.migrate()
        if settings.seed_demo and await store.count_targets() == 0:
            targets = demo_targets(settings.database_url)
            for t in targets:
                await store.create_target(TargetIn(**t).model_dump())
            log.info("seeded %d demo targets", len(targets))

        http = httpx.AsyncClient(headers={"User-Agent": "NetScope/1.0"})
        hub = Hub()
        notifier = Notifier(hub, settings.alert_webhook_url, http)
        detector = IncidentDetector(settings.failure_threshold, settings.recovery_threshold)
        monitor = Monitor(
            store, detector, notifier,
            max_concurrent=settings.max_concurrent_checks, http_client=http,
        )
        await monitor.start()
        pruner = asyncio.create_task(_prune_forever(store, settings.retention_days))

        app.state.store, app.state.monitor, app.state.hub = store, monitor, hub
        try:
            yield
        finally:
            pruner.cancel()
            await monitor.stop()
            await http.aclose()
            await store.close()

    app = FastAPI(title="NetScope", version="1.0.0", lifespan=lifespan)
    if settings.public_demo_read_only:
        @app.middleware("http")
        async def protect_public_demo(request: Request, call_next):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                return JSONResponse(status_code=403, content={"detail": "This public demo is read-only. Monitoring continues automatically."})
            return await call_next(request)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=list(settings.cors_origins),
            allow_methods=["*"], allow_headers=["*"],
        )

    def store_of(request: Request) -> PgStore:
        return request.app.state.store

    def monitor_of(request: Request) -> Monitor:
        return request.app.state.monitor

    async def target_view(
        request: Request, row: dict[str, Any], stats: dict[str, Any] | None, last: dict[str, Any] | None
    ) -> dict[str, Any]:
        stats = stats or {"checks": 0, "ok_checks": 0, "avg_ms": None, "p50_ms": None, "p95_ms": None, "p99_ms": None}
        stats = {k: v for k, v in stats.items() if k != "target_id"}
        stats["uptime_pct"] = uptime_pct(stats["ok_checks"], stats["checks"])
        if last:
            last = {k: v for k, v in last.items() if k != "target_id"}
        return {**row, "status": monitor_of(request).status(row["id"]), "last": last, "stats_24h": stats}

    # ---- health & summary --------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/summary")
    async def summary(request: Request) -> dict[str, Any]:
        store, monitor = store_of(request), monitor_of(request)
        rows = await store.target_rows()
        stats = await store.stats_all(datetime.now(timezone.utc) - timedelta(hours=24))
        counts = {"up": 0, "degraded": 0, "down": 0, "unknown": 0, "paused": 0}
        for row in rows:
            counts[monitor.status(row["id"])] += 1
        checks = sum(s["checks"] for s in stats.values())
        ok = sum(s["ok_checks"] for s in stats.values())
        open_incidents = await store.list_incidents(open_only=True, limit=1000)
        return {
            "targets": len(rows),
            **counts,
            "open_incidents": len(open_incidents),
            "uptime_24h_pct": uptime_pct(ok, checks),
            "checks_24h": checks,
            "live_clients": request.app.state.hub.clients,
        }

    # ---- targets -------------------------------------------------------------

    @app.get("/api/targets")
    async def list_targets(request: Request) -> list[dict[str, Any]]:
        store = store_of(request)
        rows = await store.target_rows()
        stats = await store.stats_all(datetime.now(timezone.utc) - timedelta(hours=24))
        latest = await store.latest_results()
        return [await target_view(request, r, stats.get(r["id"]), latest.get(r["id"])) for r in rows]

    @app.post("/api/targets", status_code=201)
    async def create_target(body: TargetIn, request: Request) -> dict[str, Any]:
        target, row = await store_of(request).create_target(body.model_dump())
        monitor_of(request).upsert_target(target)
        return await target_view(request, row, None, None)

    @app.get("/api/targets/{target_id}")
    async def get_target(target_id: int, request: Request) -> dict[str, Any]:
        store = store_of(request)
        row = await store.get_target_row(target_id)
        if row is None:
            raise HTTPException(404, "target not found")
        stats = await store.stats_one(target_id, datetime.now(timezone.utc) - timedelta(hours=24))
        recent = await store.recent_results(target_id, 1)
        return await target_view(request, row, stats, recent[0] if recent else None)

    @app.put("/api/targets/{target_id}")
    async def update_target(target_id: int, body: TargetIn, request: Request) -> dict[str, Any]:
        updated = await store_of(request).update_target(target_id, body.model_dump())
        if updated is None:
            raise HTTPException(404, "target not found")
        target, row = updated
        monitor_of(request).upsert_target(target)
        return await target_view(request, row, None, None)

    @app.delete("/api/targets/{target_id}", status_code=204)
    async def delete_target(target_id: int, request: Request) -> Response:
        if not await store_of(request).delete_target(target_id):
            raise HTTPException(404, "target not found")
        monitor_of(request).remove_target(target_id)
        return Response(status_code=204)

    @app.post("/api/targets/{target_id}/check")
    async def check_now(target_id: int, request: Request) -> dict[str, Any]:
        result = await monitor_of(request).check_now(target_id)
        if result is None:
            raise HTTPException(409, "target unknown or a check is already running")
        return {
            "ok": result.ok, "latency_ms": result.latency_ms, "status_code": result.status_code,
            "error": result.error, "checked_at": result.checked_at,
            "status": monitor_of(request).status(target_id),
        }

    @app.get("/api/targets/{target_id}/results")
    async def recent_results(
        target_id: int, request: Request, limit: int = Query(50, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        return await store_of(request).recent_results(target_id, limit)

    @app.get("/api/targets/{target_id}/history")
    async def history(
        target_id: int, request: Request, range: Literal["1h", "24h", "7d"] = "24h"
    ) -> dict[str, Any]:
        window, bucket_s = RANGES[range]
        since = datetime.now(timezone.utc) - window
        buckets = await store_of(request).history(target_id, since, bucket_s)
        for b in buckets:
            b["uptime_pct"] = uptime_pct(b["ok_checks"], b["checks"])
        return {"range": range, "bucket_s": bucket_s, "since": since, "buckets": buckets}

    # ---- incidents -----------------------------------------------------------

    @app.get("/api/incidents")
    async def incidents(
        request: Request,
        target_id: int | None = None,
        open_only: bool = False,
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return await store_of(request).list_incidents(target_id, open_only, limit)

    # ---- live feed -----------------------------------------------------------

    @app.websocket("/ws")
    async def live(ws: WebSocket) -> None:
        await ws.accept()
        hub: Hub = ws.app.state.hub
        queue = hub.subscribe()

        async def pump() -> None:
            while True:
                await ws.send_json(await queue.get())

        await ws.send_json({"type": "hello"})
        sender = asyncio.create_task(pump())
        try:
            # Keep reading so a closed browser tab is noticed straight away,
            # even when there is nothing to send.
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            hub.unsubscribe(queue)

    # Register after API/WebSocket routes so all three share one HTTPS address.
    static_dir = os.getenv("STATIC_DIR")
    if static_dir and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
    return app


app = create_app()
