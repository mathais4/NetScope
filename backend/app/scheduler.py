"""The background monitor: decides when each target is due, runs checks
concurrently, records results and raises incidents.

How it works, in one loop:
  every `tick_s` seconds, for each enabled target whose next check is due and
  which isn't already being checked, start a check as its own asyncio task.

Rules that keep it well-behaved:
  * One check per target at a time (the `_in_flight` set). If a target is slow
    to time out, its next check waits rather than piling up.
  * A semaphore caps how many checks run at once across all targets.
  * The next due time is set when a check *starts*, so the schedule doesn't
    drift by the length of each check.
  * Errors from the database or a webhook are logged and never kill the loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Protocol

import httpx

from .checks import run_check
from .detector import IncidentDetector
from .models import CheckResult, Outcome, Target
from .notifier import Notifier

log = logging.getLogger("netscope.monitor")

Checker = Callable[[Target, httpx.AsyncClient], Awaitable[Outcome]]


class MonitorStore(Protocol):
    async def list_targets(self) -> list[Target]: ...
    async def open_incident_target_ids(self) -> list[int]: ...
    async def insert_result(self, result: CheckResult) -> None: ...
    async def open_incident(self, target_id: int, started_at: datetime, cause: str | None) -> int | None: ...
    async def resolve_incident(self, target_id: int, resolved_at: datetime) -> int | None: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Monitor:
    def __init__(
        self,
        store: MonitorStore,
        detector: IncidentDetector,
        notifier: Notifier,
        *,
        checker: Checker = run_check,
        max_concurrent: int = 50,
        tick_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = utc_now,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.store = store
        self.detector = detector
        self.notifier = notifier
        self.checker = checker
        self.tick_s = tick_s
        self.clock = clock
        self.wall_clock = wall_clock
        self._sem = asyncio.Semaphore(max_concurrent)
        self._targets: dict[int, Target] = {}
        self._next_due: dict[int, float] = {}
        self._in_flight: set[int] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._client = http_client
        self._owns_client = http_client is None

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(headers={"User-Agent": "NetScope/1.0"})
        for target in await self.store.list_targets():
            self.upsert_target(target)
        for target_id in await self.store.open_incident_target_ids():
            self.detector.restore_down(target_id)
        self._loop_task = asyncio.create_task(self._loop(), name="netscope-monitor")
        log.info("monitor started with %d targets", len(self._targets))

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    # ---- target registry (kept in sync by the API) ----------------------

    def upsert_target(self, target: Target) -> None:
        old = self._targets.get(target.id)
        self._targets[target.id] = target
        if old is None or old.interval_s != target.interval_s or not old.enabled:
            self._next_due[target.id] = self.clock()  # check new/changed targets straight away

    def remove_target(self, target_id: int) -> None:
        self._targets.pop(target_id, None)
        self._next_due.pop(target_id, None)
        self.detector.forget(target_id)

    def status(self, target_id: int) -> str:
        target = self._targets.get(target_id)
        if target is not None and not target.enabled:
            return "paused"
        return self.detector.status(target_id)

    # ---- scheduling ------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:  # pragma: no cover - defensive
                log.exception("monitor tick failed")
            await asyncio.sleep(self.tick_s)

    def tick(self) -> list[int]:
        """Start every check that is due. Returns the target ids started."""
        now = self.clock()
        started: list[int] = []
        for target in list(self._targets.values()):
            if not target.enabled or target.id in self._in_flight:
                continue
            if self._next_due.get(target.id, now) > now:
                continue
            self._next_due[target.id] = now + target.interval_s
            self._in_flight.add(target.id)
            task = asyncio.create_task(self._run(target))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            started.append(target.id)
        return started

    async def wait_idle(self) -> None:
        """Wait until all running checks finish (used by tests and shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def check_now(self, target_id: int) -> CheckResult | None:
        """Run one check immediately (the dashboard's "Check now" button)."""
        target = self._targets.get(target_id)
        if target is None or target_id in self._in_flight:
            return None
        self._in_flight.add(target_id)
        return await self._run(target)

    # ---- one check -------------------------------------------------------

    async def _run(self, target: Target) -> CheckResult | None:
        try:
            async with self._sem:
                assert self._client is not None, "call start() first"
                at = self.wall_clock()
                try:
                    outcome = await self.checker(target, self._client)
                except Exception as exc:  # a bug in a checker must not stop monitoring
                    log.exception("checker crashed for target %s", target.id)
                    outcome = Outcome(False, error=f"internal error: {exc}")
            if target.id not in self._targets:
                return None  # deleted while the check was running

            result = CheckResult.from_outcome(target.id, at, outcome)
            await self._record(target, result)
            return result
        finally:
            self._in_flight.discard(target.id)

    async def _record(self, target: Target, result: CheckResult) -> None:
        try:
            await self.store.insert_result(result)
        except Exception:
            log.exception("could not store result for target %s", target.id)

        event = self.detector.observe(result)
        self.notifier.check_completed(target, result, self.status(target.id))
        if event is None:
            return
        try:
            if event.kind == "opened":
                incident_id = await self.store.open_incident(target.id, event.at, event.cause)
            else:
                incident_id = await self.store.resolve_incident(target.id, event.at)
        except Exception:
            log.exception("could not store incident for target %s", target.id)
            incident_id = None
        await self.notifier.incident(target, event, incident_id)
