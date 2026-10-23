"""Where events go: live dashboard clients (WebSocket), the log, and an
optional webhook (Slack, Discord, or anything that accepts a JSON POST)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .models import CheckResult, IncidentEvent, Target

log = logging.getLogger("netscope.alerts")


class Hub:
    """Fan-out of live messages to every connected dashboard.

    Each WebSocket gets its own bounded queue. A slow browser that falls behind
    has messages dropped rather than making the monitor wait for it.
    """

    def __init__(self, queue_size: int = 200) -> None:
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._queue_size = queue_size

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._queue_size)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._queues.discard(q)

    @property
    def clients(self) -> int:
        return len(self._queues)

    def publish(self, message: dict[str, Any]) -> None:
        for q in list(self._queues):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass


class Notifier:
    def __init__(
        self, hub: Hub, webhook_url: str | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self.hub = hub
        self.webhook_url = webhook_url
        self._client = client
        self.sent_alerts: list[dict[str, Any]] = []  # recent alerts, handy for tests and debugging

    def check_completed(self, target: Target, result: CheckResult, status: str) -> None:
        self.hub.publish({
            "type": "check",
            "target_id": target.id,
            "status": status,
            "ok": result.ok,
            "latency_ms": result.latency_ms,
            "status_code": result.status_code,
            "error": result.error,
            "checked_at": result.checked_at.isoformat(),
        })

    async def incident(self, target: Target, event: IncidentEvent, incident_id: int | None) -> None:
        if event.kind == "opened":
            text = f"🔴 {target.name} ({target.address}) is DOWN: {event.cause or 'checks failing'}"
            log.warning(text)
        else:
            text = f"🟢 {target.name} ({target.address}) has RECOVERED"
            log.info(text)

        payload = {
            "type": f"incident_{event.kind}",
            "incident_id": incident_id,
            "target_id": target.id,
            "target_name": target.name,
            "at": event.at.isoformat(),
            "detected_at": event.detected_at.isoformat(),
            "cause": event.cause,
            "text": text,      # Slack reads "text"
            "content": text,   # Discord reads "content"
        }
        self.sent_alerts.append(payload)
        del self.sent_alerts[:-100]
        self.hub.publish(payload)
        if self.webhook_url and self._client is not None:
            await self._post_webhook(payload)

    async def _post_webhook(self, payload: dict[str, Any]) -> None:
        # Alert delivery must never break monitoring, so failures are only logged.
        try:
            resp = await self._client.post(self.webhook_url, json=payload, timeout=5)  # type: ignore[union-attr, arg-type]
            if resp.status_code >= 400:
                log.error("webhook returned HTTP %s", resp.status_code)
        except httpx.HTTPError as exc:
            log.error("webhook delivery failed: %s", exc)
