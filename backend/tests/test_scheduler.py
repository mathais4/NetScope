"""Monitor tests with an in-memory store and a scripted checker, so we can
control time and outcomes exactly."""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.detector import IncidentDetector
from app.models import CheckResult, Outcome, Target
from app.notifier import Hub, Notifier
from app.scheduler import Monitor

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeStore:
    def __init__(self, targets, open_ids=()):
        self.targets = list(targets)
        self.open_ids = list(open_ids)
        self.results: list[CheckResult] = []
        self.incidents: list[dict] = []
        self.fail_inserts = False

    async def list_targets(self):
        return self.targets

    async def open_incident_target_ids(self):
        return self.open_ids

    async def insert_result(self, result):
        if self.fail_inserts:
            raise ConnectionError("database down")
        self.results.append(result)

    async def open_incident(self, target_id, started_at, cause):
        if any(i["target_id"] == target_id and i["resolved_at"] is None for i in self.incidents):
            return None
        self.incidents.append({"id": len(self.incidents) + 1, "target_id": target_id,
                               "started_at": started_at, "resolved_at": None, "cause": cause})
        return len(self.incidents)

    async def resolve_incident(self, target_id, resolved_at):
        for i in self.incidents:
            if i["target_id"] == target_id and i["resolved_at"] is None:
                i["resolved_at"] = resolved_at
                return i["id"]
        return None


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class ScriptedChecker:
    """Returns outcomes from a per-target script like "ooxxx"; records calls."""

    def __init__(self, scripts, delay=0.0):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: list[int] = []
        self.delay = delay
        self.running = 0
        self.max_running = 0

    async def __call__(self, target, client):
        self.calls.append(target.id)
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            script = self.scripts.get(target.id) or ["o"]
            ch = script.pop(0) if len(script) > 1 else script[0]
            return Outcome(True, 12.5, 200) if ch == "o" else Outcome(False, error="boom")
        finally:
            self.running -= 1


def make(targets, scripts=None, open_ids=(), **kw):
    store = FakeStore(targets, open_ids)
    hub = Hub()
    notifier = Notifier(hub)
    checker = ScriptedChecker(scripts or {}, delay=kw.pop("delay", 0.0))
    clock = Clock()
    mon = Monitor(store, IncidentDetector(kw.pop("fail", 3), kw.pop("recover", 2)), notifier,
                  checker=checker, clock=clock, http_client=httpx.AsyncClient(), **kw)
    return mon, store, notifier, checker, clock, hub


async def start(mon):
    # start() also launches the real loop; cancel it so tests drive tick() by hand
    await mon.start()
    mon._loop_task.cancel()


async def run_ticks(mon, clock, n, step):
    for _ in range(n):
        mon.tick()
        await mon.wait_idle()
        clock.t += step


async def test_checks_run_on_their_own_intervals():
    mon, store, _, checker, clock, _ = make([
        Target(1, "fast", "tcp", host="a", port=1, interval_s=10),
        Target(2, "slow", "tcp", host="b", port=1, interval_s=30),
    ])
    await start(mon)
    await run_ticks(mon, clock, 60, 1)  # 60 simulated seconds
    assert checker.calls.count(1) == 6
    assert checker.calls.count(2) == 2
    assert len(store.results) == 8


async def test_disabled_targets_are_not_checked():
    mon, store, _, checker, clock, _ = make([Target(1, "off", "tcp", host="a", port=1, enabled=False)])
    await start(mon)
    await run_ticks(mon, clock, 5, 10)
    assert checker.calls == []
    assert mon.status(1) == "paused"


async def test_slow_check_is_not_started_twice():
    mon, _, _, checker, clock, _ = make([Target(1, "slow", "tcp", host="a", port=1, interval_s=5)], delay=0.05)
    await start(mon)
    assert mon.tick() == [1]
    clock.t += 10           # due again, but the first check is still running
    assert mon.tick() == []
    await mon.wait_idle()
    assert mon.tick() == [1]
    await mon.wait_idle()
    assert checker.calls == [1, 1]


async def test_concurrency_is_capped():
    targets = [Target(i, f"t{i}", "tcp", host="a", port=1) for i in range(1, 21)]
    mon, store, _, checker, _, _ = make(targets, delay=0.02, max_concurrent=4)
    await start(mon)
    mon.tick()
    await mon.wait_idle()
    assert len(store.results) == 20
    assert checker.max_running == 4


async def test_outage_opens_and_resolves_incident_with_alerts():
    mon, store, notifier, _, clock, hub = make(
        [Target(1, "web", "http", url="http://x", interval_s=10)],
        {1: "ooxxxxoo"}, fail=3, recover=2,
    )
    q = hub.subscribe()
    await start(mon)
    await run_ticks(mon, clock, 8, 10)

    assert [a["type"] for a in notifier.sent_alerts] == ["incident_opened", "incident_resolved"]
    assert len(store.incidents) == 1
    inc = store.incidents[0]
    assert inc["cause"] == "boom"
    assert inc["started_at"] == store.results[2].checked_at   # first failing check
    assert inc["resolved_at"] == store.results[6].checked_at  # first ok of the recovery
    assert mon.status(1) == "up"

    live = [q.get_nowait()["type"] for _ in range(q.qsize())]
    assert live.count("check") == 8
    assert "incident_opened" in live and "incident_resolved" in live


async def test_restart_with_open_incident_does_not_realert():
    mon, store, notifier, _, clock, _ = make(
        [Target(1, "web", "http", url="http://x", interval_s=10)], {1: "xxxx"}, open_ids=[1],
    )
    await start(mon)
    assert mon.status(1) == "down"
    await run_ticks(mon, clock, 4, 10)
    assert notifier.sent_alerts == []


async def test_database_error_does_not_stop_monitoring():
    mon, store, _, checker, clock, _ = make([Target(1, "web", "tcp", host="a", port=1, interval_s=10)])
    await start(mon)
    store.fail_inserts = True
    await run_ticks(mon, clock, 2, 10)
    store.fail_inserts = False
    await run_ticks(mon, clock, 1, 10)
    assert len(checker.calls) == 3 and len(store.results) == 1


async def test_crashing_checker_is_recorded_as_failure():
    async def broken(target, client):
        raise RuntimeError("bug")

    mon, store, *_ = make([Target(1, "web", "tcp", host="a", port=1)])
    mon.checker = broken
    await start(mon)
    mon.tick()
    await mon.wait_idle()
    assert store.results[0].ok is False
    assert "internal error" in store.results[0].error


async def test_added_target_is_checked_immediately_and_removed_one_stops():
    mon, store, _, checker, clock, _ = make([])
    await start(mon)
    mon.upsert_target(Target(5, "new", "tcp", host="a", port=1, interval_s=60))
    assert mon.tick() == [5]
    await mon.wait_idle()
    mon.remove_target(5)
    clock.t += 120
    assert mon.tick() == []
    assert mon.status(5) == "unknown"


async def test_check_now_runs_outside_schedule():
    mon, store, *_ = make([Target(1, "web", "tcp", host="a", port=1, interval_s=60)])
    await start(mon)
    result = await mon.check_now(1)
    assert result is not None and result.ok
    assert await mon.check_now(99) is None


async def test_results_use_wall_clock_time():
    mon, store, *_ = make([Target(1, "web", "tcp", host="a", port=1)])
    fixed = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    mon.wall_clock = lambda: fixed
    await start(mon)
    mon.tick()
    await mon.wait_idle()
    assert store.results[0].checked_at == fixed
